"""Der Assistent — ein Auftrag in Worten, Karten zur Bestätigung."""

from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app import assistent
from app.auth import CurrentUser, get_current_user
from app.db import acquire_as
from app.llm import LLMNichtEingerichtet, load_llm_config

router = APIRouter(prefix="/api/assistent", tags=["assistent"])


class Auftrag(BaseModel):
    nachricht: str = Field(min_length=1, max_length=2000)
    verlauf: list[dict[str, str]] = Field(default_factory=list, max_length=20)


class Antwort(BaseModel):
    antwort: str
    karten: list[dict[str, Any]]
    navigation: str | None = None
    schritte: list[str]
    modell: str


@router.post("", response_model=Antwort)
async def auftrag(payload: Auftrag, user: CurrentUser = Depends(get_current_user)) -> Antwort:
    async with acquire_as(user.user_id) as conn:
        cfg = await load_llm_config(conn, user.org_id)
        if not cfg.eingerichtet:
            raise HTTPException(409, "Es ist kein Sprachmodell hinterlegt. Ohne Modell versteht der Assistent keinen Auftrag.")
        try:
            erg = await assistent.auftrag(conn, cfg, payload.nachricht, payload.verlauf)
        except LLMNichtEingerichtet as exc:
            raise HTTPException(409, str(exc)) from exc
        except httpx.HTTPStatusError as exc:
            raise HTTPException(502, f"Der Endpunkt hat mit {exc.response.status_code} geantwortet.") from exc
        except httpx.RequestError as exc:
            raise HTTPException(502, f"Nicht erreichbar: {exc}") from exc
    return Antwort(**erg, modell=cfg.model)
