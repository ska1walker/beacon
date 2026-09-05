"""Listen — wen man meint, statisch oder als Frage an den Bestand.

Statisch: eine Menge von Hand, bis jemand sie ändert. Aktiv: ein Filter
im Format der Ansichten; wer ihn erfüllt, ist drin. Beide tragen eine
Kampagne; ob den Leuten geschrieben werden darf, sagt der Kontakt, nicht
die Liste (app/kampagnen.py).
"""

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

import orjson
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app import audit, kampagnen, segmente
from app.auth import CurrentUser, get_current_user
from app.db import acquire_as

router = APIRouter(prefix="/api/listen", tags=["listen"])


class Bedingung(BaseModel):
    feld: str
    operator: str
    wert: Any = None


class ListeIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    beschreibung: str | None = None
    art: Literal["statisch", "aktiv"] = "statisch"
    filter: list[Bedingung] = []
    verknuepfung: Literal["und", "oder"] = "und"


class ListePatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    beschreibung: str | None = None
    filter: list[Bedingung] | None = None
    verknuepfung: Literal["und", "oder"] | None = None


class Liste(BaseModel):
    id: UUID
    name: str
    beschreibung: str | None = None
    art: str
    filter: list[Bedingung]
    verknuepfung: str
    # Gerechnet: wie viele die Liste meint, wie vielen man schreiben darf.
    gemeint: int = 0
    berechtigt: int = 0
    created_at: datetime
    updated_at: datetime


class Mitglied(BaseModel):
    id: UUID
    first_name: str | None = None
    last_name: str | None = None
    email: str | None = None
    company_name: str | None = None
    einwilligung: str
    hinzugefuegt_am: datetime | None = None


class MitgliederIn(BaseModel):
    contact_ids: list[UUID] = Field(min_length=1, max_length=500)


def _pruefen(bedingungen: list[Bedingung], verknuepfung: str) -> None:
    try:
        args: list[Any] = []
        segmente.filter_zu_sql(
            "contacts", [segmente.Bedingung(b.feld, b.operator, b.wert) for b in bedingungen], args,
            verknuepfung=verknuepfung,
        )
    except segmente.Ungueltig as exc:
        raise HTTPException(400, str(exc)) from exc


async def _aus_zeile(conn, z: dict[str, Any]) -> Liste:
    roh = z["filter"]
    if isinstance(roh, str | bytes):
        roh = orjson.loads(roh)
    zahlen = await kampagnen.vorschau(conn, z)
    return Liste(
        id=z["id"], name=z["name"], beschreibung=z["beschreibung"], art=z["art"],
        filter=[Bedingung(**b) for b in roh], verknuepfung=z["verknuepfung"],
        gemeint=zahlen["gemeint"], berechtigt=zahlen["berechtigt"],
        created_at=z["created_at"], updated_at=z["updated_at"],
    )


async def _laden(conn, liste_id: UUID) -> dict[str, Any]:
    z = await kampagnen.liste_laden(conn, liste_id)
    if z is None:
        raise HTTPException(404, "Liste nicht gefunden")
    return z


@router.get("", response_model=list[Liste])
async def alle(user: CurrentUser = Depends(get_current_user)) -> list[Liste]:
    async with acquire_as(user.user_id) as conn:
        zeilen = await conn.fetch(
            "select * from public.listen where org_id = $1 and deleted_at is null order by name", user.org_id
        )
        return [await _aus_zeile(conn, dict(z)) for z in zeilen]


@router.post("", response_model=Liste, status_code=201)
async def anlegen(payload: ListeIn, user: CurrentUser = Depends(get_current_user)) -> Liste:
    if payload.art == "aktiv":
        _pruefen(payload.filter, payload.verknuepfung)
    async with acquire_as(user.user_id) as conn:
        neu = await conn.fetchval(
            """
            insert into public.listen (org_id, name, beschreibung, art, filter, verknuepfung, created_by)
            values ($1, $2, $3, $4::public.listen_art, $5::jsonb, $6, $7) returning id
            """,
            user.org_id, payload.name.strip(), payload.beschreibung, payload.art,
            orjson.dumps([b.model_dump() for b in payload.filter]).decode(), payload.verknuepfung, user.user_id,
        )
        await audit.log_fuer(conn, user, action="create", entity="listen", entity_id=neu, diff={"name": payload.name})
        return await _aus_zeile(conn, await _laden(conn, neu))


@router.get("/von/{contact_id}", response_model=list[Liste])
async def von_kontakt(contact_id: UUID, user: CurrentUser = Depends(get_current_user)) -> list[Liste]:
    """Die statischen Listen, in denen dieser Kontakt steht."""
    async with acquire_as(user.user_id) as conn:
        zeilen = await conn.fetch(
            """
            select l.* from public.listen l
              join public.listen_mitglieder m on m.liste_id = l.id
             where m.contact_id = $1 and l.deleted_at is null order by l.name
            """,
            contact_id,
        )
        return [await _aus_zeile(conn, dict(z)) for z in zeilen]


@router.get("/{liste_id}", response_model=Liste)
async def einzeln(liste_id: UUID, user: CurrentUser = Depends(get_current_user)) -> Liste:
    async with acquire_as(user.user_id) as conn:
        return await _aus_zeile(conn, await _laden(conn, liste_id))


@router.patch("/{liste_id}", response_model=Liste)
async def aendern(liste_id: UUID, payload: ListePatch, user: CurrentUser = Depends(get_current_user)) -> Liste:
    felder = payload.model_dump(exclude_unset=True)
    async with acquire_as(user.user_id) as conn:
        alt = await _laden(conn, liste_id)
        if "filter" in felder or "verknuepfung" in felder:
            bed = payload.filter if payload.filter is not None else [Bedingung(**b) for b in (orjson.loads(alt["filter"]) if isinstance(alt["filter"], str) else alt["filter"])]
            _pruefen(bed, payload.verknuepfung or alt["verknuepfung"])
        for name, wert in felder.items():
            if name == "filter":
                wert = orjson.dumps([b.model_dump() if hasattr(b, "model_dump") else b for b in wert]).decode()
                await conn.execute("update public.listen set filter = $1::jsonb, updated_at = now() where id = $2", wert, liste_id)
            else:
                await conn.execute(f"update public.listen set {name} = $1, updated_at = now() where id = $2", wert, liste_id)
        await audit.log_fuer(conn, user, action="update", entity="listen", entity_id=liste_id, diff={k: str(v)[:80] for k, v in felder.items()})
        return await _aus_zeile(conn, await _laden(conn, liste_id))


@router.delete("/{liste_id}", status_code=204)
async def loeschen(liste_id: UUID, user: CurrentUser = Depends(get_current_user)) -> None:
    async with acquire_as(user.user_id) as conn:
        await _laden(conn, liste_id)
        await conn.execute("update public.listen set deleted_at = now() where id = $1", liste_id)
        await audit.log_fuer(conn, user, action="delete", entity="listen", entity_id=liste_id, diff={})


@router.get("/{liste_id}/mitglieder", response_model=list[Mitglied])
async def mitglieder(
    liste_id: UUID,
    q: str | None = Query(default=None, max_length=100),
    user: CurrentUser = Depends(get_current_user),
) -> list[Mitglied]:
    """Wen die Liste meint — bei aktiven Listen die aktuelle Antwort des Filters."""
    async with acquire_as(user.user_id) as conn:
        liste = await _laden(conn, liste_id)
        alle = await kampagnen.empfaenger(conn, liste, hoechstens=500)
        if liste["art"] == "statisch":
            wann = {z["contact_id"]: z["hinzugefuegt_am"] for z in await conn.fetch(
                "select contact_id, hinzugefuegt_am from public.listen_mitglieder where liste_id = $1", liste_id)}
        else:
            wann = {}
    if q:
        s = q.lower()
        alle = [k for k in alle if s in f"{k.get('first_name') or ''} {k.get('last_name') or ''} {k.get('email') or ''} {k.get('company_name') or ''}".lower()]
    return [Mitglied(**{k: v for k, v in z.items() if k in Mitglied.model_fields}, hinzugefuegt_am=wann.get(z["id"])) for z in alle]


@router.post("/{liste_id}/mitglieder", response_model=Liste)
async def hinzufuegen(liste_id: UUID, payload: MitgliederIn, user: CurrentUser = Depends(get_current_user)) -> Liste:
    async with acquire_as(user.user_id) as conn:
        liste = await _laden(conn, liste_id)
        if liste["art"] != "statisch":
            raise HTTPException(400, "Eine aktive Liste füllt sich aus ihrem Filter — hier kann niemand von Hand hinein.")
        await conn.executemany(
            """
            insert into public.listen_mitglieder (liste_id, contact_id, hinzugefuegt_von)
            select $1, id, $3 from public.contacts where id = $2 and deleted_at is null
            on conflict do nothing
            """,
            [(liste_id, cid, user.user_id) for cid in payload.contact_ids],
        )
        await conn.execute("update public.listen set updated_at = now() where id = $1", liste_id)
        await audit.log_fuer(conn, user, action="update", entity="listen", entity_id=liste_id, diff={"hinzugefuegt": len(payload.contact_ids)})
        return await _aus_zeile(conn, await _laden(conn, liste_id))


@router.delete("/{liste_id}/mitglieder/{contact_id}", response_model=Liste)
async def entfernen(liste_id: UUID, contact_id: UUID, user: CurrentUser = Depends(get_current_user)) -> Liste:
    async with acquire_as(user.user_id) as conn:
        await _laden(conn, liste_id)
        await conn.execute("delete from public.listen_mitglieder where liste_id = $1 and contact_id = $2", liste_id, contact_id)
        await conn.execute("update public.listen set updated_at = now() where id = $1", liste_id)
        return await _aus_zeile(conn, await _laden(conn, liste_id))
