"""Kampagnen und Vorlagen — Marketing-Post an eine Liste.

Eine Kampagne ist Betreff, Text und eine Liste. Vor dem Start sagt die
Vorschau, wie viele gemeint sind und wie vielen man schreiben darf; die
Testmail zeigt, wie es beim Empfänger aussieht; der Start schreibt das
Buch, und die Schleife schickt. Danach zählen die Zeilen (app/kampagnen.py).
"""

from datetime import datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app import audit, kampagnen, versand
from app.auth import CurrentUser, get_current_user
from app.db import acquire_as

router = APIRouter(prefix="/api/kampagnen", tags=["kampagnen"])
vorlagen_router = APIRouter(prefix="/api/vorlagen", tags=["vorlagen"])


class KampagneIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    betreff: str = Field(default="", max_length=200)
    text: str = Field(default="", max_length=50000)
    liste_id: UUID | None = None


class KampagnePatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    betreff: str | None = Field(default=None, max_length=200)
    text: str | None = Field(default=None, max_length=50000)
    liste_id: UUID | None = None


class Kampagne(BaseModel):
    id: UUID
    name: str
    betreff: str
    text: str
    liste_id: UUID | None = None
    liste_name: str | None = None
    status: str
    gestartet_am: datetime | None = None
    empfaenger: int = 0
    uebergangen: int = 0
    gesendet: int = 0
    wartend: int = 0
    fehlgeschlagen: int = 0
    klicks: int = 0
    klicker: int = 0
    abgemeldet: int = 0
    created_at: datetime
    updated_at: datetime


class Vorschau(BaseModel):
    gemeint: int
    berechtigt: int
    uebergangen: int
    beispiel_betreff: str
    beispiel_text: str


SQL = """
select k.*, l.name as liste_name
  from public.kampagnen k
  left join public.listen l on l.id = k.liste_id and l.deleted_at is null
 where k.deleted_at is null
"""


async def _laden(conn, kampagne_id: UUID) -> dict[str, Any]:
    z = await conn.fetchrow(SQL + " and k.id = $1", kampagne_id)
    if z is None:
        raise HTTPException(404, "Kampagne nicht gefunden")
    return dict(z)


async def _aus_zeile(conn, z: dict[str, Any]) -> Kampagne:
    zahlen = await kampagnen.kennzahlen(conn, z["id"])
    return Kampagne(
        **{k: v for k, v in z.items() if k in Kampagne.model_fields and k != "status"},
        status=kampagnen.wirksamer_status(z, zahlen),
        **zahlen,
    )


@router.get("", response_model=list[Kampagne])
async def alle(user: CurrentUser = Depends(get_current_user)) -> list[Kampagne]:
    async with acquire_as(user.user_id) as conn:
        zeilen = await conn.fetch(SQL + " and k.org_id = $1 order by k.created_at desc", user.org_id)
        return [await _aus_zeile(conn, dict(z)) for z in zeilen]


@router.post("", response_model=Kampagne, status_code=201)
async def anlegen(payload: KampagneIn, user: CurrentUser = Depends(get_current_user)) -> Kampagne:
    async with acquire_as(user.user_id) as conn:
        neu = await conn.fetchval(
            """
            insert into public.kampagnen (org_id, name, betreff, text, liste_id, created_by)
            values ($1, $2, $3, $4, $5, $6) returning id
            """,
            user.org_id, payload.name.strip(), payload.betreff, payload.text, payload.liste_id, user.user_id,
        )
        await audit.log_fuer(conn, user, action="create", entity="kampagnen", entity_id=neu, diff={"name": payload.name})
        return await _aus_zeile(conn, await _laden(conn, neu))


@router.get("/{kampagne_id}", response_model=Kampagne)
async def einzeln(kampagne_id: UUID, user: CurrentUser = Depends(get_current_user)) -> Kampagne:
    async with acquire_as(user.user_id) as conn:
        return await _aus_zeile(conn, await _laden(conn, kampagne_id))


@router.patch("/{kampagne_id}", response_model=Kampagne)
async def aendern(kampagne_id: UUID, payload: KampagnePatch, user: CurrentUser = Depends(get_current_user)) -> Kampagne:
    felder = payload.model_dump(exclude_unset=True)
    async with acquire_as(user.user_id) as conn:
        alt = await _laden(conn, kampagne_id)
        if alt["status"] != "entwurf" and any(k in felder for k in ("betreff", "text", "liste_id")):
            raise HTTPException(409, "Eine gestartete Kampagne lässt sich nicht mehr ändern — nur umbenennen.")
        for name, wert in felder.items():
            await conn.execute(f"update public.kampagnen set {name} = $1, updated_at = now() where id = $2", wert, kampagne_id)
        await audit.log_fuer(conn, user, action="update", entity="kampagnen", entity_id=kampagne_id, diff={k: str(v)[:80] for k, v in felder.items()})
        return await _aus_zeile(conn, await _laden(conn, kampagne_id))


@router.delete("/{kampagne_id}", status_code=204)
async def loeschen(kampagne_id: UUID, user: CurrentUser = Depends(get_current_user)) -> None:
    async with acquire_as(user.user_id) as conn:
        await _laden(conn, kampagne_id)
        await conn.execute("update public.kampagnen set deleted_at = now() where id = $1", kampagne_id)
        await audit.log_fuer(conn, user, action="delete", entity="kampagnen", entity_id=kampagne_id, diff={})


@router.get("/{kampagne_id}/vorschau", response_model=Vorschau)
async def vorschau(kampagne_id: UUID, user: CurrentUser = Depends(get_current_user)) -> Vorschau:
    """Wie viele, und wie es aussieht — am ersten berechtigten Empfänger."""
    async with acquire_as(user.user_id) as conn:
        k = await _laden(conn, kampagne_id)
        liste = await kampagnen.liste_laden(conn, k["liste_id"]) if k["liste_id"] else None
        zahlen = await kampagnen.vorschau(conn, liste)
        beispiel = None
        if liste is not None:
            beispiel = next((e for e in await kampagnen.empfaenger(conn, liste, hoechstens=200) if kampagnen.darf(e)), None)
    werte = versand.platzhalter_aus(beispiel or {"first_name": "Erika", "last_name": "Muster", "company_name": "Muster GmbH"},
                                    abmeldelink="https://…/o/abmelden/…")
    return Vorschau(**zahlen, beispiel_betreff=versand.rendern(k["betreff"], werte), beispiel_text=versand.rendern(k["text"], werte))


@router.post("/{kampagne_id}/testen")
async def testen(kampagne_id: UUID, user: CurrentUser = Depends(get_current_user)) -> dict:
    """Die Kampagne an die eigene Absenderadresse — mit Musterwerten, ohne Zählung."""
    async with acquire_as(user.user_id) as conn:
        k = await _laden(conn, kampagne_id)
        einst = await versand._einstellungen(conn, user.org_id)
        konto = versand.marketing_konto(einst)
        if konto is None:
            raise HTTPException(409, "Kein Versandweg für Marketing-Post — SMTP-Konto oder Brevo unter Einstellungen.")
        werte = versand.platzhalter_aus({"first_name": "Erika", "last_name": "Muster", "company_name": "Muster GmbH"})
        mail_id = await versand.einreihen(
            conn, user.org_id, art="marketing", an=konto.absender,
            betreff="[Test] " + versand.rendern(k["betreff"] or k["name"], werte),
            text=versand.rendern(k["text"], werte), created_by=user.user_id, payload={"zweck": "kampagnen-test"},
        )
        try:
            zeile = await versand.versenden(conn, user.org_id, mail_id)
        except versand.Unmoeglich as exc:
            raise HTTPException(409, str(exc)) from exc
    if zeile["status"] != "gesendet":
        raise HTTPException(502, f"Der Versand hat abgelehnt: {zeile['fehler']}")
    return {"gesendet": True, "an": zeile["an"]}


@router.post("/{kampagne_id}/starten", response_model=Kampagne)
async def starten(kampagne_id: UUID, user: CurrentUser = Depends(get_current_user)) -> Kampagne:
    async with acquire_as(user.user_id) as conn:
        k = await _laden(conn, kampagne_id)
        try:
            bilanz = await kampagnen.starten(conn, user.org_id, k, actor=user.user_id)
        except versand.Unmoeglich as exc:
            raise HTTPException(409, str(exc)) from exc
        await audit.log_fuer(conn, user, action="update", entity="kampagnen", entity_id=kampagne_id, diff={"gestartet": bilanz})
        return await _aus_zeile(conn, await _laden(conn, kampagne_id))


@router.post("/{kampagne_id}/abbrechen", response_model=Kampagne)
async def abbrechen(kampagne_id: UUID, user: CurrentUser = Depends(get_current_user)) -> Kampagne:
    """Was noch wartet, geht nicht mehr hinaus. Was draußen ist, ist draußen."""
    async with acquire_as(user.user_id) as conn:
        k = await _laden(conn, kampagne_id)
        if k["status"] != "laeuft":
            raise HTTPException(409, "Nur eine laufende Kampagne lässt sich abbrechen.")
        await conn.execute(
            "update public.mails set status = 'fehlgeschlagen', fehler = 'Kampagne abgebrochen' "
            "where kampagne_id = $1 and status = 'wartend'",
            kampagne_id,
        )
        await conn.execute("update public.kampagnen set status = 'abgebrochen', updated_at = now() where id = $1", kampagne_id)
        await audit.log_fuer(conn, user, action="update", entity="kampagnen", entity_id=kampagne_id, diff={"status": "abgebrochen"})
        return await _aus_zeile(conn, await _laden(conn, kampagne_id))


# ── Vorlagen ────────────────────────────────────────────────────────────

class VorlageIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    betreff: str = Field(min_length=1, max_length=200)
    text: str = Field(min_length=1, max_length=50000)


class VorlagePatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    betreff: str | None = Field(default=None, min_length=1, max_length=200)
    text: str | None = Field(default=None, min_length=1, max_length=50000)


class Vorlage(BaseModel):
    id: UUID
    name: str
    betreff: str
    text: str
    created_at: datetime
    updated_at: datetime


@vorlagen_router.get("", response_model=list[Vorlage])
async def vorlagen(user: CurrentUser = Depends(get_current_user)) -> list[Vorlage]:
    async with acquire_as(user.user_id) as conn:
        zeilen = await conn.fetch("select * from public.vorlagen where org_id = $1 and deleted_at is null order by name", user.org_id)
    return [Vorlage(**{k: v for k, v in dict(z).items() if k in Vorlage.model_fields}) for z in zeilen]


@vorlagen_router.post("", response_model=Vorlage, status_code=201)
async def vorlage_anlegen(payload: VorlageIn, user: CurrentUser = Depends(get_current_user)) -> Vorlage:
    async with acquire_as(user.user_id) as conn:
        z = await conn.fetchrow(
            "insert into public.vorlagen (org_id, name, betreff, text, created_by) values ($1, $2, $3, $4, $5) returning *",
            user.org_id, payload.name.strip(), payload.betreff, payload.text, user.user_id,
        )
        await audit.log_fuer(conn, user, action="create", entity="vorlagen", entity_id=z["id"], diff={"name": payload.name})
    return Vorlage(**{k: v for k, v in dict(z).items() if k in Vorlage.model_fields})


@vorlagen_router.patch("/{vorlage_id}", response_model=Vorlage)
async def vorlage_aendern(vorlage_id: UUID, payload: VorlagePatch, user: CurrentUser = Depends(get_current_user)) -> Vorlage:
    felder = payload.model_dump(exclude_unset=True)
    async with acquire_as(user.user_id) as conn:
        for name, wert in felder.items():
            await conn.execute(f"update public.vorlagen set {name} = $1, updated_at = now() where id = $2 and deleted_at is null", wert, vorlage_id)
        z = await conn.fetchrow("select * from public.vorlagen where id = $1 and deleted_at is null", vorlage_id)
        if z is None:
            raise HTTPException(404, "Vorlage nicht gefunden")
        await audit.log_fuer(conn, user, action="update", entity="vorlagen", entity_id=vorlage_id, diff={k: str(v)[:80] for k, v in felder.items()})
    return Vorlage(**{k: v for k, v in dict(z).items() if k in Vorlage.model_fields})


@vorlagen_router.delete("/{vorlage_id}", status_code=204)
async def vorlage_loeschen(vorlage_id: UUID, user: CurrentUser = Depends(get_current_user)) -> None:
    async with acquire_as(user.user_id) as conn:
        n = await conn.execute("update public.vorlagen set deleted_at = now() where id = $1 and deleted_at is null", vorlage_id)
        if n.endswith(" 0"):
            raise HTTPException(404, "Vorlage nicht gefunden")
        await audit.log_fuer(conn, user, action="delete", entity="vorlagen", entity_id=vorlage_id, diff={})
