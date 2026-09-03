"""Sicherung, Ausfuhr und Wiederherstellung."""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app import sicherung
from app.auth import CurrentUser, get_current_user
from app.db import acquire_as

router = APIRouter(prefix="/api/sicherung", tags=["sicherung"])


class Stand(BaseModel):
    name: str
    groesse_bytes: int
    erstellt_am: str


class Bilanz(BaseModel):
    datei: str | None = None
    # Beim Sichern: wie viele Zeilen im Abzug stehen.
    zeilen: dict[str, int] = {}


class Wiederherstellung(BaseModel):
    datei: str | None = None
    geschrieben: dict[str, int] = {}
    # Was schon da war. Steht getrennt, weil „nichts geschrieben" und
    # „alles wiederhergestellt" zwei sehr verschiedene Nachrichten sind.
    uebersprungen: dict[str, int] = {}


@router.get("/staende", response_model=list[Stand])
async def liste(user: CurrentUser = Depends(get_current_user)) -> list[Stand]:
    return [Stand(**s) for s in sicherung.staende()]


@router.post("", response_model=Bilanz, status_code=201)
async def jetzt_sichern(user: CurrentUser = Depends(get_current_user)) -> Bilanz:
    """Schreibt einen Abzug neben die Daten — dorthin, wo er eine
    Deinstallation überlebt."""
    async with acquire_as(user.user_id) as conn:
        daten = await sicherung.abzug_erstellen(conn, user.org_id)
        slug = daten["organisation"].get("slug")
    pfad = sicherung.abzug_schreiben(daten, slug)
    return Bilanz(
        datei=pfad.name,
        zeilen={t: len(z) for t, z in daten["tabellen"].items()},
    )


@router.get("/ausfuhr")
async def ausfuhr(user: CurrentUser = Depends(get_current_user)) -> JSONResponse:
    """Derselbe Abzug, aber zum Herunterladen statt zum Ablegen.

    Der Schlüssel zum Sprachmodell fliegt hier heraus: Diese Datei geht
    durch den Browser und landet auf einem Rechner, der nicht die Box ist.
    Die Sicherung auf der Box behält ihn, weil sie ohne ihn nach einer
    Neuinstallation unvollständig wäre.
    """
    async with acquire_as(user.user_id) as conn:
        daten = await sicherung.abzug_erstellen(conn, user.org_id)
    daten["einstellungen"].pop("llm_api_key", None)
    daten["hinweis_schluessel"] = "Der Zugangsschlüssel ist in dieser Ausfuhr nicht enthalten."

    name = f"aicrm-ausfuhr-{daten['organisation'].get('slug') or 'org'}.json"
    return JSONResponse(
        content=daten,
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
    )


@router.post("/wiederherstellen", response_model=Wiederherstellung)
async def wiederherstellen(
    name: str,
    user: CurrentUser = Depends(get_current_user),
) -> Wiederherstellung:
    """Spielt einen Stand von der Box zurück.

    Es wird nichts überschrieben: Was heute schon da ist, bleibt. Die
    Wiederherstellung füllt auf, was fehlt — sonst wäre ein versehentlicher
    Aufruf schlimmer als der Verlust, gegen den sie hilft.
    """
    try:
        daten = sicherung.abzug_lesen(name)
    except FileNotFoundError:
        raise HTTPException(404, f"Kein Stand namens {name!r}") from None

    async with acquire_as(user.user_id) as conn:
        try:
            ergebnis = await sicherung.zurueckspielen(conn, daten, user.org_id, user.user_id)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
    return Wiederherstellung(datei=name, **ergebnis)


@router.post("/einlesen", response_model=Wiederherstellung)
async def einlesen(
    datei: UploadFile,
    user: CurrentUser = Depends(get_current_user),
) -> Wiederherstellung:
    """Spielt eine hochgeladene Ausfuhr zurück — etwa auf eine neue Box."""
    import json

    try:
        daten: dict[str, Any] = json.loads(await datei.read())
    except json.JSONDecodeError as exc:
        raise HTTPException(400, f"Das ist kein lesbares JSON: {exc}") from exc

    async with acquire_as(user.user_id) as conn:
        try:
            ergebnis = await sicherung.zurueckspielen(conn, daten, user.org_id, user.user_id)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
    return Wiederherstellung(datei=datei.filename, **ergebnis)
