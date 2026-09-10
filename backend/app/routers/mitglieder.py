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

import json
import re
from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app import anmeldung, audit, versand
from app.auth import CurrentUser, get_current_user, verwaltet
from app.config import settings
from app.db import acquire_as

router = APIRouter(prefix="/api/mitglieder", tags=["mitglieder"])


class MitgliedIn(BaseModel):
    display_name: str = Field(min_length=2, max_length=120)
    email: str | None = None


class MitgliedPatch(BaseModel):
    display_name: str | None = Field(default=None, min_length=2, max_length=120)
    email: str | None = None


class RollePatch(BaseModel):
    # `viewer` steht im Datenbank-Typ, bewirkt aber nichts: Für die Rechte
    # ist es dasselbe wie `member` (auth.VERWALTET). Es hier anzubieten
    # hieße, eine Abstufung zu versprechen, die es nicht gibt.
    role: Literal["admin", "member"]


class Mitglied(BaseModel):
    id: UUID
    display_name: str | None = None
    email: str | None = None
    olares_username: str
    zugang: str
    role: str
    created_at: datetime
    last_seen_at: datetime | None = None
    # Nur ob, nie was. Die Oberfläche braucht es, um zu warnen, dass eine
    # Einladung hier kein Konto einrichtet, sondern eines zurücksetzt.
    passwort_gesetzt: bool = False


class Wer(BaseModel):
    """Wer gerade handelt — und über welchen Zugang."""

    user_id: UUID
    display_name: str | None = None
    org_id: UUID
    # Der Olares-Zugang, über den der Request hereinkam.
    login_username: str
    # `owner` | `admin` | `member` | `viewer`. Die Oberfläche sagt damit
    # vorher, was nicht geht, statt es den Server abweisen zu lassen.
    rolle: str = "member"
    # Hat diese Person schon ein eigenes Passwort? Solange niemand eines
    # hat, lässt der Olares-Kopf den ersten noch herein (siehe auth.py) —
    # und das soll die Oberfläche sagen, nicht verschweigen.
    passwort_gesetzt: bool = False
    # Wahr, wenn ein anderer Sitzplatz als der des Zugangs gewählt ist.
    sitzplatz_gewaehlt: bool
    # Was diese Person für sich eingestellt hat — Favoriten in der Navigation.
    einstellungen: dict[str, Any] = Field(default_factory=dict)


PFAD = re.compile(r"^/[a-z0-9-]*$")


class WerEinstellungenPatch(BaseModel):
    """Persönliche Einstellungen, teilweise: Nur gesendete Schlüssel ändern
    sich, `null` löscht einen. Unbekannte Schlüssel werden abgewiesen, damit
    das Feld nur trägt, was die Anwendung kennt."""

    model_config = ConfigDict(extra="forbid")

    favoriten: list[str] | None = None

    @field_validator("favoriten")
    @classmethod
    def _pfade(cls, wert: list[str] | None) -> list[str] | None:
        if wert is None:
            return None
        sauber: list[str] = []
        for pfad in wert:
            if not isinstance(pfad, str) or len(pfad) > 64 or not PFAD.match(pfad):
                raise ValueError(f"kein Pfad der Navigation: {pfad!r}")
            if pfad not in sauber:
                sauber.append(pfad)
        if len(sauber) > 20:
            raise ValueError("höchstens 20 Favoriten")
        return sauber


async def _einstellungen(conn, user_id: UUID) -> dict[str, Any]:
    # Kein JSON-Codec am Pool (siehe db.py): jsonb kommt als Text.
    roh = await conn.fetchval("select einstellungen from public.users where id = $1", user_id)
    daten = json.loads(roh) if isinstance(roh, str | bytes) else (roh or {})
    return daten if isinstance(daten, dict) else {}


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


def _wer(
    user: CurrentUser,
    einstellungen: dict[str, Any],
    rolle: str = "member",
    passwort_gesetzt: bool = False,
) -> Wer:
    return Wer(
        user_id=user.user_id,
        display_name=user.display_name,
        org_id=user.org_id,
        login_username=user.login_username or user.olares_username,
        sitzplatz_gewaehlt=user.sitzplatz,
        einstellungen=einstellungen,
        rolle=rolle,
        passwort_gesetzt=passwort_gesetzt,
    )


async def _rolle(conn, user: CurrentUser) -> str:
    return await conn.fetchval(
        "select role::text from public.user_org_roles where user_id = $1 and org_id = $2",
        user.user_id, user.org_id,
    ) or "member"


async def _hat_passwort(conn, user: CurrentUser) -> bool:
    return bool(await conn.fetchval(
        "select passwort_hash is not null from public.users where id = $1", user.handelnder
    ))


@router.get("/wer", response_model=Wer)
async def wer(user: CurrentUser = Depends(get_current_user)) -> Wer:
    async with acquire_as(user.user_id) as conn:
        einst = await _einstellungen(conn, user.user_id)
        rolle = await _rolle(conn, user)
        hat = await _hat_passwort(conn, user)
    return _wer(user, einst, rolle, hat)


@router.patch("/wer/einstellungen", response_model=Wer)
async def einstellungen_aendern(
    payload: WerEinstellungenPatch, user: CurrentUser = Depends(get_current_user)
) -> Wer:
    """Ändert, was die handelnde Person für sich eingestellt hat.

    Persönlich, nicht organisationsweit: `user.user_id` ist der gewählte
    Sitzplatz. Kein Protokolleintrag — eine Vorliebe in der Oberfläche ist
    kein Geschäftsdatum, und ein Verlauf voller Sternklicks hülfe niemandem.
    """
    felder = payload.model_dump(exclude_unset=True)
    if not felder:
        raise HTTPException(400, "Nichts zu ändern.")
    async with acquire_as(user.user_id) as conn:
        roh = await conn.fetchval(
            """
            update public.users
               set einstellungen = jsonb_strip_nulls(einstellungen || $2::jsonb)
             where id = $1 and deleted_at is null
            returning einstellungen
            """,
            user.user_id, json.dumps(felder),
        )
    if roh is None:
        raise HTTPException(404, "Person nicht gefunden")
    async with acquire_as(user.user_id) as conn:
        rolle = await _rolle(conn, user)
        hat = await _hat_passwort(conn, user)
    daten = json.loads(roh) if isinstance(roh, str | bytes) else roh
    return _wer(user, daten if isinstance(daten, dict) else {}, rolle, hat)


@router.get("", response_model=list[Mitglied])
async def liste(user: CurrentUser = Depends(get_current_user)) -> list[Mitglied]:
    async with acquire_as(user.user_id) as conn:
        zeilen = await conn.fetch(
            """
            select u.id, u.display_name, u.email, u.olares_username, u.zugang,
                   r.role::text as role, u.created_at, u.last_seen_at,
                   u.passwort_hash is not null as passwort_gesetzt
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
    user: CurrentUser = Depends(verwaltet),
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


@router.patch("/{mitglied_id}", response_model=Mitglied)
async def umbenennen(
    mitglied_id: UUID,
    payload: MitgliedPatch,
    user: CurrentUser = Depends(verwaltet),
) -> Mitglied:
    """Gibt einer Person einen Namen — auch der mit eigenem Zugang.

    Der Olares-Zugang bringt nur die Kennung mit („kaivostudio"); wer
    dahinter sitzt, weiß Olares nicht. Die Kennung bleibt, wie sie ist:
    Sie ist der Schlüssel für Besitz, Protokoll und die spätere
    Anmeldung. Nur der Anzeigename ändert sich.
    """
    felder = payload.model_dump(exclude_unset=True)
    if not felder:
        raise HTTPException(400, "Keine Änderung übergeben")
    if "display_name" in felder:
        felder["display_name"] = felder["display_name"].strip()

    async with acquire_as(user.user_id) as conn:
        zeile = await conn.fetchrow(
            """
            update public.users u
               set display_name = coalesce($1, u.display_name),
                   email = case when $3 then $2 else u.email end
              from public.user_org_roles r
             where u.id = $4 and r.user_id = u.id and r.org_id = $5 and u.deleted_at is null
            returning u.id, u.display_name, u.email, u.olares_username, u.zugang,
                      r.role::text as role, u.created_at, u.last_seen_at
            """,
            felder.get("display_name"),
            felder.get("email"),
            "email" in felder,
            mitglied_id,
            user.org_id,
        )
        if zeile is None:
            raise HTTPException(404, "Nicht in dieser Organisation")
        await audit.log_fuer(
            conn, user, action="update", entity="users", entity_id=mitglied_id, diff=felder
        )
    return Mitglied(**dict(zeile))


@router.delete("/{mitglied_id}", status_code=204)
async def entfernen(mitglied_id: UUID, user: CurrentUser = Depends(verwaltet)) -> None:
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


@router.patch("/{mitglied_id}/rolle", response_model=Mitglied)
async def rolle_setzen(
    mitglied_id: UUID,
    payload: RollePatch,
    user: CurrentUser = Depends(get_current_user),
) -> Mitglied:
    """Macht jemanden zum Verwalter — oder nimmt es zurück.

    **Nur die Eigentümerin.** Ein Verwalter darf schon alles, was ein
    Eigentümer darf (`auth.VERWALTET`); dürfte er auch Rollen setzen,
    könnte er die Eigentümerin herabstufen und sich die Organisation
    aneignen. Der Eigentum bleibt der eine Punkt, an dem eine Rolle nicht
    reicht.

    Drei Dinge gehen deshalb nicht: die eigene Rolle ändern (der Weg,
    sich selbst auszusperren), die Rolle der Eigentümerin ändern, und
    `owner` vergeben — eine Übergabe des Eigentums ist etwas anderes als
    eine Rolle und braucht ihren eigenen Weg.

    Wofür das da ist: Auf einer fremden Box hilft nur jemand, der die
    Einstellungen sieht. Bis 0.9.2 bekam jede angelegte Person fest
    `member`, und es gab keinen Endpunkt, der das ändert — Hilfe hieß
    dann, dem Helfer das Passwort der Eigentümerin zu geben.
    """
    async with acquire_as(user.user_id) as conn:
        meine = await conn.fetchval(
            "select role::text from public.user_org_roles where user_id = $1 and org_id = $2",
            user.handelnder,
            user.org_id,
        )
        if meine != "owner":
            raise HTTPException(
                403,
                "Rollen vergibt nur die Person, der diese Organisation gehört.",
            )
        if mitglied_id == user.handelnder:
            raise HTTPException(
                400,
                "Die eigene Rolle lässt sich nicht ändern — sonst könnte sich der "
                "Eigentümer aus seiner eigenen Organisation aussperren.",
            )

        zeile = await conn.fetchrow(
            """
            update public.user_org_roles r
               set role = $1::public.user_role
              from public.users u
             where r.user_id = $2 and r.org_id = $3 and u.id = r.user_id
               and u.deleted_at is null and r.role <> 'owner'
            returning u.id, u.display_name, u.email, u.olares_username, u.zugang,
                      r.role::text as role, u.created_at, u.last_seen_at
            """,
            payload.role,
            mitglied_id,
            user.org_id,
        )
        if zeile is None:
            # Beide Fälle einzeln zu unterscheiden hieße, einem Fremden zu
            # verraten, wem die Organisation gehört. Hier ist niemand
            # fremd — der Satz nennt deshalb beide Möglichkeiten.
            raise HTTPException(
                404,
                "Nicht in dieser Organisation, oder es ist die Eigentümerin — "
                "deren Rolle steht fest.",
            )

        await audit.log_fuer(
            conn,
            user,
            action="update",
            entity="users",
            entity_id=mitglied_id,
            diff={"role": payload.role},
        )
    return Mitglied(**dict(zeile))


@router.post("/{mitglied_id}/einladung", status_code=201)
async def einladen(mitglied_id: UUID, user: CurrentUser = Depends(verwaltet)) -> dict[str, Any]:
    """Erzeugt einen Einladungslink für eine Person der Organisation.

    Zurück kommt ein **Link zum Weitergeben**, keine Mail: SMTP ist auf
    einer frischen Box nicht eingerichtet, und ein Zugang, der am
    Mailversand hängt, wäre genau dann nicht da, wenn man ihn braucht.
    Wer den Link hat, setzt das Passwort — er gilt einmal und läuft ab.

    Ältere Einladungen derselben Person werden dabei entwertet.
    """
    async with acquire_as(user.user_id) as conn:
        person = await conn.fetchrow(
            """
            select u.id, u.display_name, u.olares_username
              from public.users u
              join public.user_org_roles r on r.user_id = u.id
             where u.id = $1 and r.org_id = $2 and u.deleted_at is null
            """,
            mitglied_id, user.org_id,
        )
        if person is None:
            raise HTTPException(404, "Diese Person gehört nicht zu Ihrer Organisation.")
        token = await anmeldung.einladung_anlegen(conn, mitglied_id, user.org_id, user.user_id)
        await audit.log_fuer(
            conn, user, action="update", entity="users", entity_id=mitglied_id,
            diff={"einladung": "erzeugt"},
        )
    return {
        "pfad": f"/einladung/{token}",
        "name": person["display_name"] or person["olares_username"],
        "gilt_tage": settings.einladung_tage,
    }


ABSENDERSPALTEN = (
    "absender_email", "absender_name", "smtp_host", "smtp_port",
    "smtp_benutzer", "smtp_passwort", "smtp_sicherheit",
)


class Absenderkonto(BaseModel):
    """Womit diese Person schickt. Leere Felder heißen: wie die Organisation."""

    absender_email: str | None = None
    absender_name: str | None = None
    smtp_host: str | None = None
    smtp_port: int | None = None
    smtp_benutzer: str | None = None
    # Beim Lesen nie das Passwort, nur ob eines liegt.
    smtp_passwort_set: bool = False
    smtp_sicherheit: str | None = None
    # Der Absender der Organisation — als Vergleich in der Oberfläche.
    haus_absender: str | None = None
    # Liest Beacon ein Postfach? Nur dann trägt eine Mail `Reply-To` zurück,
    # und nur dann darf die Oberfläche das versprechen.
    postfach_aktiv: bool = False


class AbsenderkontoPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    absender_email: str | None = None
    absender_name: str | None = None
    smtp_host: str | None = None
    smtp_port: int | None = None
    smtp_benutzer: str | None = None
    # `null` lässt es stehen, "" löscht es — dasselbe Muster wie bei den
    # Schlüsseln der Organisation.
    smtp_passwort: str | None = None
    smtp_sicherheit: str | None = None


@router.get("/wer/absender", response_model=Absenderkonto)
async def absender_lesen(user: CurrentUser = Depends(get_current_user)) -> Absenderkonto:
    async with acquire_as(user.user_id) as conn:
        z = await conn.fetchrow(
            "select absender_email, absender_name, smtp_host, smtp_port, smtp_benutzer, "
            "       smtp_passwort is not null and smtp_passwort <> '' as pw, smtp_sicherheit "
            "from public.users where id = $1",
            user.user_id,
        )
        haus = await conn.fetchrow(
            "select smtp_absender, coalesce(imap_host, '') <> '' as postfach "
            "from public.org_settings where org_id = $1",
            user.org_id,
        )
    return Absenderkonto(
        absender_email=z["absender_email"], absender_name=z["absender_name"],
        smtp_host=z["smtp_host"], smtp_port=z["smtp_port"], smtp_benutzer=z["smtp_benutzer"],
        smtp_passwort_set=bool(z["pw"]), smtp_sicherheit=z["smtp_sicherheit"],
        haus_absender=haus["smtp_absender"] if haus else None,
        postfach_aktiv=bool(haus and haus["postfach"]),
    )


@router.put("/wer/absender", response_model=Absenderkonto)
async def absender_setzen(
    payload: AbsenderkontoPatch, user: CurrentUser = Depends(get_current_user)
) -> Absenderkonto:
    """Setzt die Absenderadresse der handelnden Person.

    Geschrieben wird `user.user_id` — dieselbe Person, die auch in
    `mails.created_by` landet. Beides muss übereinstimmen, sonst setzt man
    eine Adresse und schickt unter einer anderen. Bei einem geteilten
    Olares-Zugang ist das der gewählte Sitzplatz; mit eigener Anmeldung
    greift der Sitzplatz nicht mehr, dann ist es man selbst.

    Es gibt **keinen** Weg, die Adresse einer beliebigen anderen Person zu
    setzen: Der Pfad kennt keine Kennung, nur „wer gerade handelt".

    Die Domainprüfung greift hier schon: Wer auf dem gemeinsamen Konto
    schreibt, bleibt bei dessen Domain. Wer eigene Zugangsdaten hinterlegt,
    meldet sich selbst an und darf führen, was sein Anbieter durchlässt.
    """
    felder = payload.model_dump(exclude_unset=True)
    if not felder:
        raise HTTPException(400, "Nichts zu ändern.")

    for schluessel in ("absender_email", "absender_name", "smtp_host", "smtp_benutzer"):
        if isinstance(felder.get(schluessel), str):
            felder[schluessel] = felder[schluessel].strip() or None

    adresse = felder.get("absender_email")
    if adresse and "@" not in adresse:
        raise HTTPException(422, "Das ist keine E-Mail-Adresse.")

    if felder.get("smtp_sicherheit") and felder["smtp_sicherheit"] not in versand.SICHERHEIT:
        raise HTTPException(422, "Sicherheit muss starttls, ssl oder keine sein.")

    async with acquire_as(user.user_id) as conn:
        vorher = dict(await conn.fetchrow(
            "select absender_email, absender_name, smtp_host, smtp_port, smtp_benutzer, "
            "       smtp_passwort, smtp_sicherheit from public.users where id = $1",
            user.user_id,
        ))
        nachher = {**vorher, **{k: v for k, v in felder.items() if k != "smtp_passwort"}}
        if "smtp_passwort" in felder:
            nachher["smtp_passwort"] = felder["smtp_passwort"] or None

        haus = await conn.fetchval(
            "select smtp_absender from public.org_settings where org_id = $1", user.org_id
        )
        ziel = (nachher.get("absender_email") or "").strip()
        if ziel and not (nachher.get("smtp_host") or "").strip():
            hausdomain = versand.domain_von((haus or "").strip())
            if hausdomain and versand.domain_von(ziel) != hausdomain:
                raise HTTPException(
                    422,
                    f"„{ziel}“ gehört nicht zu {hausdomain}. Auf dem gemeinsamen Konto geht "
                    "nur eine Adresse derselben Domain. Für eine andere hinterlegen Sie "
                    "eigene Zugangsdaten.",
                )

        # Der Spaltenname geht in den SQL-Text, also kommt er aus einer
        # festen Liste und nicht aus der Anfrage. Das Modell verbietet
        # zwar fremde Felder; eine Liste hier hängt nicht davon ab.
        for schluessel in ABSENDERSPALTEN:
            if vorher[schluessel] != nachher[schluessel]:
                await conn.execute(
                    f"update public.users set {schluessel} = $2 where id = $1",  # noqa: S608
                    user.user_id, nachher[schluessel],
                )
        await audit.log_fuer(
            conn, user, action="update", entity="users", entity_id=user.user_id,
            diff={"absender": ziel or "(Organisation)"},
        )
    return await absender_lesen(user)
