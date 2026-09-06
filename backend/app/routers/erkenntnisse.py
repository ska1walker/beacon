"""Erkenntnisse — Themen aus Gesprächsnotizen, mit den Aussagen dahinter."""

from typing import Any
from uuid import UUID

import orjson
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app import erkenntnisse
from app.auth import CurrentUser, get_current_user
from app.db import acquire_as
from app.llm import load_llm_config

router = APIRouter(prefix="/api/erkenntnisse", tags=["erkenntnisse"])


class Lauf(BaseModel):
    id: UUID
    status: str
    zeitraum_tage: int
    fortschritt: dict[str, Any]
    aussagen_anzahl: int
    themen: list[dict[str, Any]]
    fehler: str | None = None
    modell: str | None = None
    created_at: Any
    updated_at: Any


class Uebersicht(BaseModel):
    llm_ready: bool
    zeitraum_tage: int
    lauf: Lauf | None
    aussagen: list[dict[str, Any]]
    nach_art: dict[str, int]
    offene_notizen: int


class Auswertung(BaseModel):
    tage: int = Field(default=90, ge=7, le=730)


def _js(v: Any) -> Any:
    return orjson.loads(v) if isinstance(v, str | bytes) else v


def _lauf(row: Any) -> Lauf:
    return Lauf(
        id=row["id"], status=row["status"], zeitraum_tage=row["zeitraum_tage"],
        fortschritt=_js(row["fortschritt"]) or {}, aussagen_anzahl=row["aussagen_anzahl"],
        themen=_js(row["themen"]) or [], fehler=row["fehler"], modell=row["modell"],
        created_at=row["created_at"], updated_at=row["updated_at"],
    )


@router.get("", response_model=Uebersicht)
async def uebersicht(tage: int = Query(default=90, ge=7, le=730), user: CurrentUser = Depends(get_current_user)) -> Uebersicht:
    async with acquire_as(user.user_id) as conn:
        cfg = await load_llm_config(conn, user.org_id)
        row = await conn.fetchrow(
            "select * from public.themenlaeufe where org_id = $1 and zeitraum_tage = $2 order by created_at desc limit 1",
            user.org_id, tage,
        )
        aussagen = await erkenntnisse.aussagen_laden(conn, user.org_id, tage)
        offen = len(await erkenntnisse.offene_notizen(conn, user.org_id, tage))
    nach_art = dict.fromkeys(erkenntnisse.ARTEN, 0)
    for a in aussagen:
        nach_art[a["art"]] += 1
    return Uebersicht(
        llm_ready=cfg.eingerichtet, zeitraum_tage=tage, lauf=_lauf(row) if row else None,
        aussagen=[{**a, "id": str(a["id"]), "activity_id": str(a["activity_id"]),
                   "company_id": str(a["company_id"]) if a["company_id"] else None,
                   "deal_id": str(a["deal_id"]) if a.get("deal_id") else None,
                   "contact_id": str(a["contact_id"]) if a.get("contact_id") else None,
                   "occurred_at": a["occurred_at"].isoformat()} for a in aussagen],
        nach_art=nach_art, offene_notizen=offen,
    )


@router.post("/auswerten", response_model=Lauf, status_code=202)
async def auswerten(payload: Auswertung, user: CurrentUser = Depends(get_current_user)) -> Lauf:
    async with acquire_as(user.user_id) as conn:
        cfg = await load_llm_config(conn, user.org_id)
        if not cfg.eingerichtet:
            raise HTTPException(409, "Es ist kein Sprachmodell hinterlegt. Ohne Modell liest niemand die Notizen.")
        laeuft = await conn.fetchrow(
            "select id from public.themenlaeufe where org_id = $1 and status = 'laeuft' "
            "and updated_at > now() - interval '30 minutes' limit 1",
            user.org_id,
        )
        if laeuft:
            raise HTTPException(409, "Eine Auswertung läuft gerade.")
        row = await conn.fetchrow(
            "insert into public.themenlaeufe (org_id, zeitraum_tage, created_by, modell) values ($1, $2, $3, $4) returning *",
            user.org_id, payload.tage, user.user_id, cfg.model,
        )
    erkenntnisse.im_hintergrund(user, row["id"], payload.tage)
    return _lauf(row)
