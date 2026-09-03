"""Die Menschen, die in dieser Organisation arbeiten.

Zwei Sorten, und der Unterschied ist wichtig genug, um ihn sichtbar zu
halten:

- **eigener Zugang** — meldet sich selbst über Olares an, der Name kommt
  aus `X-Bfl-User`.
- **Sitzplatz** — eine Person ohne eigenen Olares-Zugang. Sie existiert,
  damit ihr Arbeit zugeschrieben werden kann. Wer den geteilten Zugang
  hat, kann jeden Sitzplatz einnehmen; das ist Zuschreibung und keine
  Anmeldung, und die Oberfläche sagt das auch so.
"""

import re
from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app import audit
from app.auth import CurrentUser, get_current_user
from app.db import acquire_as

router = APIRouter(prefix="/api/mitglieder", tags=["mitglieder"])


class MitgliedIn(BaseModel):
    display_name: str = Field(min_length=2, max_length=120)
    email: str | None = None


class Mitglied(BaseModel):
    id: UUID
    display_name: str | None = None
    email: str | None = None
    olares_username: str
    zugang: str
    role: str
    created_at: datetime
    last_seen_at: datetime | None = None


class Wer(BaseModel):
    """Wer gerade handelt — und über welchen Zugang."""

    user_id: UUID
    display_name: str | None = None
    org_id: UUID
    # Der Olares-Zugang, über den der Request hereinkam.
    login_username: str
    # Wahr, wenn ein anderer Sitzplatz als der des Zugangs gewählt ist.
    sitzplatz_gewaehlt: bool


def _kennung(name: str) -> str:
    """Aus „Marc Bayer" wird „marc-bayer".

    Der Name ist zugleich die Kennung, unter der sich diese Person später
    selbst anmelden könnte: Bekommt Marc irgendwann ein eigenes
    Olares-Konto mit demselben Namen, greift sein Sitzplatz automatisch
    — aus der zugeschriebenen Person wird eine angemeldete, ohne dass
    Besitz oder Protokoll umgeschrieben werden müssen.
    """
    klein = name.strip().lower()
    ersetzt = (
        klein.replace("ä", "ae").replace("ö", "oe").replace("ü", "ue").replace("ß", "ss")
    )
    return re.sub(r"[^a-z0-9]+", "-", ersetzt).strip("-") or "person"


@router.get("/wer", response_model=Wer)
async def wer(user: CurrentUser = Depends(get_current_user)) -> Wer:
    return Wer(
        user_id=user.user_id,
        display_name=user.display_name,
        org_id=user.org_id,
        login_username=user.login_username or user.olares_username,
        sitzplatz_gewaehlt=user.sitzplatz,
    )


@router.get("", response_model=list[Mitglied])
async def liste(user: CurrentUser = Depends(get_current_user)) -> list[Mitglied]:
    async with acquire_as(user.user_id) as conn:
        zeilen = await conn.fetch(
            """
            select u.id, u.display_name, u.email, u.olares_username, u.zugang,
                   r.role::text as role, u.created_at, u.last_seen_at
            from public.users u
            join public.user_org_roles r on r.user_id = u.id
            where r.org_id = $1 and u.deleted_at is null
            order by u.created_at
            """,
            user.org_id,
        )
    return [Mitglied(**dict(z)) for z in zeilen]


@router.post("", response_model=Mitglied, status_code=201)
async def anlegen(
    payload: MitgliedIn,
    user: CurrentUser = Depends(get_current_user),
) -> Mitglied:
    """Legt eine Person ohne eigenen Olares-Zugang an.

    Sie wird Mitglied dieser Organisation mit der Rolle `member` — dass
    beide alles sehen und ändern, entscheiden die Policies, nicht die
    Rolle. Die Rolle steht für später bereit.
    """
    kennung = _kennung(payload.display_name)

    # Die users-Tabelle liegt außerhalb der Zeilensicherheit für Fachdaten
    # (siehe 0002), aber die Rollenzeile nicht — deshalb beides im Kontext
    # des Handelnden, in einer Transaktion.
    async with acquire_as(user.user_id) as conn:
        vorhanden = await conn.fetchrow(
            """
            select u.id from public.users u
            join public.user_org_roles r on r.user_id = u.id
            where u.olares_username = $1 and r.org_id = $2
            """,
            kennung,
            user.org_id,
        )
        if vorhanden:
            raise HTTPException(
                409,
                f'„{payload.display_name}“ ist in dieser Organisation schon angelegt.',
            )

        person = await conn.fetchrow(
            """
            insert into public.users (olares_username, display_name, email, zugang)
            values ($1, $2, $3, 'sitzplatz')
            on conflict (olares_username) do update
              set display_name = coalesce(public.users.display_name, excluded.display_name)
            returning id, display_name, email, olares_username, zugang, created_at, last_seen_at
            """,
            kennung,
            payload.display_name.strip(),
            payload.email,
        )
        await conn.execute(
            "insert into public.user_org_roles (user_id, org_id, role) values ($1,$2,'member') "
            "on conflict (user_id, org_id) do nothing",
            person["id"],
            user.org_id,
        )
        await audit.log_fuer(
            conn,
            user,
            action="create",
            entity="users",
            entity_id=person["id"],
            diff={"display_name": payload.display_name, "zugang": "sitzplatz"},
        )

    return Mitglied(**dict(person), role="member")


@router.delete("/{mitglied_id}", status_code=204)
async def entfernen(mitglied_id: UUID, user: CurrentUser = Depends(get_current_user)) -> None:
    """Nimmt eine Person aus der Organisation.

    Der Nutzer selbst kann sich nicht entfernen, und eine Person mit
    eigenem Olares-Zugang auch nicht: Sie würde beim nächsten Request
    ohnehin wieder angelegt. Die Datensätze, die ihr gehören, bleiben ihr
    zugeschrieben — Besitz umzuschreiben wäre eine Geschichtsfälschung.
    """
    if mitglied_id == user.user_id:
        raise HTTPException(400, "Sich selbst kann man nicht entfernen.")

    async with acquire_as(user.user_id) as conn:
        person = await conn.fetchrow(
            """
            select u.zugang from public.users u
            join public.user_org_roles r on r.user_id = u.id
            where u.id = $1 and r.org_id = $2
            """,
            mitglied_id,
            user.org_id,
        )
        if person is None:
            raise HTTPException(404, "Nicht in dieser Organisation")
        if person["zugang"] == "olares":
            raise HTTPException(
                400,
                "Diese Person meldet sich über Olares selbst an und würde beim nächsten "
                "Aufruf wieder erscheinen. Der Zugang wird in den Olares-Einstellungen "
                "entfernt, nicht hier.",
            )

        await conn.execute(
            "delete from public.user_org_roles where user_id = $1 and org_id = $2",
            mitglied_id,
            user.org_id,
        )
        await audit.log_fuer(
            conn, user, action="delete", entity="users", entity_id=mitglied_id
        )
