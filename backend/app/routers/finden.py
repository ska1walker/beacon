"""Beschreiben statt tippen — drei Endpunkte für die Maske „Anlegen“.

Nichts hier schreibt in die Datenbank. Die Antworten füllen die Maske;
Anlegen läuft über die gewohnten Endpunkte. Was den Suchdienst verlassen
hat, steht in `quellen` (Art `suche`, Feld `anfrage`) — das ist der
Nachweis, den „Wohin Daten gehen“ verspricht.
"""

from typing import Any, Literal

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app import anreicherung, finden
from app.anreicherung import Ergebnis
from app.auth import CurrentUser, get_current_user
from app.db import acquire_as
from app.llm import LLMNichtEingerichtet, load_llm_config
from app.routers.erfassen import _dublette

router = APIRouter(prefix="/api/finden", tags=["finden"])


class Beschreibung(BaseModel):
    beschreibung: str = Field(min_length=3, max_length=300)


class Kandidat(BaseModel):
    name: str
    website: str
    ort: str | None = None
    grund: str = ""
    quelle: str


class Kandidatenantwort(BaseModel):
    kandidaten: list[Kandidat]
    person: dict[str, str]
    quellen: list[dict[str, Any]]
    hinweise: list[str]
    modell: str


class Firmenwahl(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    website: str = Field(min_length=3, max_length=300)


class Personenwahl(BaseModel):
    firma: Firmenwahl
    person: dict[str, str] = Field(default_factory=dict)
    # Wenn die Firma schon feststeht, tippt jemand nur „Geschäftsführer,
    # heißt vermutlich Sebastian“ — das geht als Rolle in die Suche.
    beschreibung: str | None = Field(default=None, max_length=300)


class Fund(BaseModel):
    """Dieselbe Form wie ein Erfassungsvorschlag — plus Belege.

    So kann die Maske denselben Weg nehmen wie beim Hineinwerfen einer
    Signatur: übernehmen, was leer ist, und den Rest zeigen.
    """
    art: Literal["contact", "company"]
    felder: dict[str, Any]
    belege: dict[str, dict[str, Any]]
    quellen: list[dict[str, Any]]
    hinweise: list[str]
    rest: str | None = None
    modell: str
    dublette: dict[str, Any] | None = None


async def _einrichtung(user: CurrentUser):
    async with acquire_as(user.user_id) as conn:
        cfg = await load_llm_config(conn, user.org_id)
        einr = await anreicherung.load_einrichtung(conn, user.org_id)
    if not cfg.eingerichtet:
        raise HTTPException(
            409, "Es ist kein Sprachmodell hinterlegt. Ohne Modell liest niemand die Treffer."
        )
    return cfg, einr


def _fund(art: Literal["contact", "company"], erg: Ergebnis, modell: str, **mehr: Any) -> Fund:
    if erg.fehler:
        erg.hinweise.append(erg.fehler)
    felder = {feld: v["wert"] for feld, v in erg.vorschlag.items()}
    felder.update({k: v for k, v in mehr.items() if v})
    return Fund(
        art=art,
        felder=felder,
        belege={feld: {"quelle": v["quelle"], "belegt": v["belegt"]} for feld, v in erg.vorschlag.items()},
        quellen=[q.als_json() for q in erg.quellen],
        hinweise=erg.hinweise,
        modell=modell,
    )


@router.post("/kandidaten", response_model=Kandidatenantwort)
async def kandidaten(payload: Beschreibung, user: CurrentUser = Depends(get_current_user)) -> Kandidatenantwort:
    cfg, einr = await _einrichtung(user)
    try:
        async with anreicherung.http_client() as client:
            erg = await finden.kandidaten(client, cfg, einr, payload.beschreibung)
    except anreicherung.SucheNichtEingerichtet as exc:
        raise HTTPException(409, str(exc)) from exc
    except anreicherung.SucheGestoert as exc:
        raise HTTPException(503, str(exc)) from exc
    except LLMNichtEingerichtet as exc:
        raise HTTPException(409, str(exc)) from exc
    except httpx.HTTPStatusError as exc:
        raise HTTPException(502, f"Der Endpunkt hat mit {exc.response.status_code} geantwortet.") from exc
    except httpx.RequestError as exc:
        raise HTTPException(502, f"Nicht erreichbar: {exc}") from exc
    if erg.fehler:
        erg.hinweise.append(erg.fehler)
    return Kandidatenantwort(
        kandidaten=[Kandidat(name=k.name, website=k.website, ort=k.ort, grund=k.grund, quelle=k.quelle) for k in erg.kandidaten],
        person=erg.person,
        quellen=[q.als_json() for q in erg.quellen],
        hinweise=erg.hinweise,
        modell=cfg.model,
    )


async def _laufen(user: CurrentUser, arbeit) -> tuple[Ergebnis, str]:
    cfg, einr = await _einrichtung(user)
    try:
        async with anreicherung.http_client() as client:
            return await arbeit(client, cfg, einr), cfg.model
    except LLMNichtEingerichtet as exc:
        raise HTTPException(409, str(exc)) from exc
    except httpx.HTTPStatusError as exc:
        raise HTTPException(502, f"Der Endpunkt hat mit {exc.response.status_code} geantwortet.") from exc
    except httpx.RequestError as exc:
        raise HTTPException(502, f"Nicht erreichbar: {exc}") from exc


@router.post("/firma", response_model=Fund)
async def firma(payload: Firmenwahl, user: CurrentUser = Depends(get_current_user)) -> Fund:
    erg, modell = await _laufen(user, lambda c, cfg, e: finden.firma(c, cfg, e, payload.name, payload.website))
    fund = _fund("company", erg, modell)
    async with acquire_as(user.user_id) as conn:
        fund.dublette = await _dublette(conn, "company", fund.felder, user.org_id)
    return fund


@router.post("/kontakt", response_model=Fund)
async def kontakt(payload: Personenwahl, user: CurrentUser = Depends(get_current_user)) -> Fund:
    hinweis = {k: v for k, v in payload.person.items() if k in ("vorname", "nachname", "rolle") and v.strip()}
    if not hinweis and payload.beschreibung and payload.beschreibung.strip():
        hinweis = {"rolle": " ".join(payload.beschreibung.split())[:120]}
    erg, modell = await _laufen(
        user,
        lambda c, cfg, e: finden.person(c, cfg, e, payload.firma.name, payload.firma.website, hinweis),
    )
    fund = _fund(
        "contact", erg, modell,
        firma_name=payload.firma.name, firma_domain=finden.domain_aus(payload.firma.website),
    )
    if not erg.vorschlag:
        # Ohne Person bleibt die Firma trotzdem in der Maske — sie ist
        # gewählt, nicht erfunden.
        return fund
    async with acquire_as(user.user_id) as conn:
        fund.dublette = await _dublette(conn, "contact", fund.felder, user.org_id)
    return fund
