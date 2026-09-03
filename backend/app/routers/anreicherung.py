"""Anreicherung — Läufe anstoßen, Vorschläge sehen, übernehmen, verwerfen."""

from typing import Any, Literal
from uuid import UUID

import orjson
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app import anreicherung
from app.auth import CurrentUser, get_current_user
from app.db import acquire_as
from app.llm import LLMNichtEingerichtet, load_llm_config

router = APIRouter(tags=["anreicherung"])

Entity = Literal["companies", "contacts"]


class AnreicherungStatus(BaseModel):
    llm_ready: bool
    suche_eingerichtet: bool
    suche_art: str = ""
    automatisch: bool
    uebernahme: str
    hint: str = ""


class Anreicherung(BaseModel):
    id: UUID
    entity: str
    entity_id: UUID
    status: str
    quellen: list[dict[str, Any]]
    vorschlag: dict[str, dict[str, Any]]
    uebernommen: dict[str, Any]
    fehler: str | None = None
    modell: str | None = None
    created_at: Any
    updated_at: Any


class Uebernahme(BaseModel):
    # Welche Felder aus dem Vorschlag geschrieben werden. Leer heißt: alle.
    felder: list[str] | None = None


def _aus_zeile(row: dict[str, Any]) -> Anreicherung:
    def js(wert: Any) -> Any:
        return orjson.loads(wert) if isinstance(wert, str) else wert

    return Anreicherung(
        id=row["id"],
        entity=row["entity"],
        entity_id=row["entity_id"],
        status=row["status"],
        quellen=js(row["quellen"]),
        vorschlag=js(row["vorschlag"]),
        uebernommen=js(row["uebernommen"]),
        fehler=row["fehler"],
        modell=row["modell"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


@router.get("/api/anreicherung/status", response_model=AnreicherungStatus)
async def status(user: CurrentUser = Depends(get_current_user)) -> AnreicherungStatus:
    async with acquire_as(user.user_id) as conn:
        cfg = await load_llm_config(conn, user.org_id)
        einr = await anreicherung.load_einrichtung(conn, user.org_id)
    hint = ""
    if not cfg.eingerichtet:
        hint = "Kein Sprachmodell hinterlegt — ohne Modell ordnet niemand die Fundstellen den Feldern zu."
    elif not einr.suche.eingerichtet:
        hint = "Kein Suchdienst hinterlegt: Gelesen wird nur die Website der Firma, LinkedIn bleibt außen vor."
    return AnreicherungStatus(
        llm_ready=cfg.eingerichtet,
        suche_eingerichtet=einr.suche.eingerichtet,
        suche_art=einr.suche.art if einr.suche.eingerichtet else "",
        automatisch=einr.automatisch,
        uebernahme=einr.uebernahme,
        hint=hint,
    )


async def _anstossen(user: CurrentUser, entity: str, entity_id: UUID) -> Anreicherung:
    async with acquire_as(user.user_id) as conn:
        try:
            row = await anreicherung.lauf(conn, user, entity, entity_id)
        except LLMNichtEingerichtet as exc:
            raise HTTPException(409, str(exc)) from exc
        except LookupError as exc:
            raise HTTPException(404, "Datensatz nicht gefunden") from exc
    return _aus_zeile(row)


@router.post("/api/companies/{company_id}/anreichern", response_model=Anreicherung)
async def firma_anreichern(company_id: UUID, user: CurrentUser = Depends(get_current_user)) -> Anreicherung:
    return await _anstossen(user, "companies", company_id)


@router.post("/api/contacts/{contact_id}/anreichern", response_model=Anreicherung)
async def kontakt_anreichern(contact_id: UUID, user: CurrentUser = Depends(get_current_user)) -> Anreicherung:
    return await _anstossen(user, "contacts", contact_id)


@router.get("/api/anreicherungen", response_model=list[Anreicherung])
async def liste(
    entity: Entity,
    entity_id: UUID,
    limit: int = 5,
    user: CurrentUser = Depends(get_current_user),
) -> list[Anreicherung]:
    async with acquire_as(user.user_id) as conn:
        rows = await conn.fetch(
            "select * from public.anreicherungen where entity = $1 and entity_id = $2 "
            "order by created_at desc limit $3",
            entity, entity_id, max(1, min(limit, 50)),
        )
    return [_aus_zeile(dict(r)) for r in rows]


@router.post("/api/anreicherungen/{lauf_id}/uebernehmen", response_model=Anreicherung)
async def uebernehmen(
    lauf_id: UUID, payload: Uebernahme, user: CurrentUser = Depends(get_current_user)
) -> Anreicherung:
    async with acquire_as(user.user_id) as conn:
        row = await conn.fetchrow("select * from public.anreicherungen where id = $1", lauf_id)
        if row is None:
            raise HTTPException(404, "Lauf nicht gefunden")
        if row["status"] not in ("vorschlag",):
            raise HTTPException(409, "Dieser Lauf hat keinen offenen Vorschlag mehr.")
        vorschlag: dict[str, dict[str, Any]] = orjson.loads(row["vorschlag"]) if isinstance(row["vorschlag"], str) else row["vorschlag"]
        gewaehlt = payload.felder if payload.felder is not None else list(vorschlag)
        unbekannt = [f for f in gewaehlt if f not in vorschlag]
        if unbekannt:
            raise HTTPException(400, f"Nicht im Vorschlag: {', '.join(unbekannt)}")
        werte = {f: vorschlag[f]["wert"] for f in gewaehlt}
        quellen = orjson.loads(row["quellen"]) if isinstance(row["quellen"], str) else row["quellen"]
        geschrieben = await anreicherung.anwenden(
            conn, user, row["entity"], row["entity_id"], werte, quellen=len(quellen)
        )
        vorher = orjson.loads(row["uebernommen"]) if isinstance(row["uebernommen"], str) else row["uebernommen"]
        rest = {f: v for f, v in vorschlag.items() if f not in gewaehlt}
        neu = await conn.fetchrow(
            """
            update public.anreicherungen
               set uebernommen = $1::jsonb, vorschlag = $2::jsonb,
                   status = $3, updated_at = now()
             where id = $4 returning *
            """,
            orjson.dumps({**vorher, **geschrieben}).decode(),
            orjson.dumps(rest).decode(),
            # Was nicht gewählt wurde, ist damit entschieden — ein Vorschlag,
            # den man dreimal wegklicken muss, ist keiner.
            "uebernommen",
            lauf_id,
        )
    return _aus_zeile(dict(neu))


@router.post("/api/anreicherungen/{lauf_id}/verwerfen", response_model=Anreicherung)
async def verwerfen(lauf_id: UUID, user: CurrentUser = Depends(get_current_user)) -> Anreicherung:
    async with acquire_as(user.user_id) as conn:
        row = await conn.fetchrow(
            "update public.anreicherungen set status = 'verworfen', vorschlag = '{}'::jsonb, "
            "updated_at = now() where id = $1 and status = 'vorschlag' returning *",
            lauf_id,
        )
        if row is None:
            raise HTTPException(404, "Kein offener Vorschlag mit dieser Kennung")
    return _aus_zeile(dict(row))
