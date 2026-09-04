"""Aus Hingeworfenem wird ein sauberer Datensatz.

Der Weg, auf dem Kontakte wirklich ins CRM kommen, ist keine Maske mit
vierzehn Feldern. Es ist eine E-Mail-Signatur in der Zwischenablage, ein
abfotografiertes Visitenkärtchen, drei Zeilen aus einem Messeprotokoll.
Wer das abtippen muss, tippt es nicht ab.

Also: hineinwerfen, was da ist — Text oder Bild — und das Modell ordnet
es Feldern zu. Zwei Regeln machen den Unterschied zwischen Hilfe und
Ärgernis:

- **Nichts wird gespeichert, was niemand gesehen hat.** Das Ergebnis
  füllt die Maske, ein Mensch drückt auf Anlegen.
- **Nichts wird erfunden.** Was nicht dasteht, bleibt leer. Eine
  erratene E-Mail-Adresse ist schlimmer als ein leeres Feld, weil sie
  plausibel aussieht und im ersten Anschreiben abprallt.
"""

import base64
from typing import Any, Literal

import httpx
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field

from app.auth import CurrentUser, get_current_user
from app.db import acquire_as
from app.llm import LLMNichtEingerichtet, chat, json_aus_antwort, load_llm_config

router = APIRouter(prefix="/api/erfassen", tags=["erfassen"])

# Ein Screenshot einer Signatur ist selten größer. Die Grenze steht hier
# und nicht erst beim Modell: Ein 20-MB-Foto würde erst nach dem
# vollständigen Hochladen abgelehnt.
BILD_MAX_BYTES = 6 * 1024 * 1024
ERLAUBTE_TYPEN = {"image/png", "image/jpeg", "image/webp", "image/gif"}

SYSTEM = (
    "Du liest hingeworfene Angaben zu einer Person oder einer Firma — eine "
    "E-Mail-Signatur, eine Visitenkarte, eine Notiz — und ordnest sie Feldern zu. "
    "Du erfindest nichts: Was nicht dasteht, lässt du weg. Du rätst keine "
    "E-Mail-Adresse aus einem Namen und keine Firma aus einer Domain, wenn sie "
    "nicht genannt ist. Antworte ausschließlich als JSON-Objekt."
)

KONTAKT_FELDER = (
    '  "first_name", "last_name", "email", "phone", "mobile", "job_title",\n'
    '  "linkedin_url", "firma_name" (nur der Name, nicht die Kennung),\n'
    '  "firma_domain", "firma_strasse", "firma_plz", "firma_ort", "firma_telefon",\n'
    '  "notizen" (was sonst noch dasteht und in kein Feld passt)\n'
)

FIRMEN_FELDER = (
    '  "name", "domain", "website", "industry", "street", "postal_code", "city",\n'
    '  "country" (ISO-Kürzel wie DE), "phone", "linkedin_url",\n'
    '  "description" (zwei Sätze, was die Firma tut)\n'
)


class Vorschlag(BaseModel):
    art: Literal["contact", "company"]
    felder: dict[str, Any]
    # Was im Text stand und in kein Feld passte. Wird nicht verschluckt:
    # Der Mensch soll entscheiden, ob es in die Notizen gehört.
    rest: str | None = None
    modell: str
    # Ein bestehender Datensatz, der dasselbe sein könnte. Verhindert den
    # dritten „Meyer Präzisionstechnik" im Bestand.
    dublette: dict[str, Any] | None = None


async def _dublette(conn, art: str, felder: dict[str, Any], org_id) -> dict[str, Any] | None:
    """Gibt es das schon? Gesucht wird über das, was eindeutig ist."""
    if art == "contact":
        if felder.get("email"):
            z = await conn.fetchrow(
                "select id, first_name, last_name, email from public.contacts "
                "where lower(email) = lower($1) and deleted_at is null limit 1",
                felder["email"],
            )
            if z:
                return {**dict(z), "grund": "gleiche E-Mail-Adresse"}
        if felder.get("first_name") and felder.get("last_name"):
            z = await conn.fetchrow(
                "select id, first_name, last_name, email from public.contacts "
                "where lower(first_name) = lower($1) and lower(last_name) = lower($2) "
                "and deleted_at is null limit 1",
                felder["first_name"], felder["last_name"],
            )
            if z:
                return {**dict(z), "grund": "gleicher Name"}
        return None

    if felder.get("domain"):
        z = await conn.fetchrow(
            "select id, name, domain from public.companies "
            "where lower(domain) = lower($1) and deleted_at is null limit 1",
            felder["domain"],
        )
        if z:
            return {**dict(z), "grund": "gleiche Domain"}
    if felder.get("name"):
        z = await conn.fetchrow(
            "select id, name, domain from public.companies "
            "where lower(name) = lower($1) and deleted_at is null limit 1",
            felder["name"],
        )
        if z:
            return {**dict(z), "grund": "gleicher Name"}
    return None


def _saubern(art: str, roh: dict[str, Any]) -> dict[str, Any]:
    """Nur bekannte Felder, nur brauchbare Werte."""
    erlaubt = {
        "contact": {
            "first_name", "last_name", "email", "phone", "mobile", "job_title",
            "linkedin_url", "firma_name", "firma_domain", "firma_strasse",
            "firma_plz", "firma_ort", "firma_telefon", "notizen",
        },
        "company": {
            "name", "domain", "website", "industry", "street", "postal_code",
            "city", "country", "phone", "linkedin_url", "description",
        },
    }[art]

    sauber: dict[str, Any] = {}
    for schluessel, wert in (roh or {}).items():
        if schluessel not in erlaubt or wert is None:
            continue
        text = str(wert).strip()
        if not text or text.lower() in ("null", "none", "unbekannt", "-", "n/a", "k. a."):
            continue
        if schluessel in ("email",) and "@" not in text:
            continue
        if schluessel == "linkedin_url" and "linkedin.com" not in text.lower():
            continue
        if schluessel == "country":
            text = text.upper()[:2]
        sauber[schluessel] = text[:300]
    return sauber


async def _lesen(
    user: CurrentUser,
    art: str,
    text: str,
    bilder: list[str],
) -> Vorschlag:
    async with acquire_as(user.user_id) as conn:
        cfg = await load_llm_config(conn, user.org_id)

    if not cfg.eingerichtet:
        raise HTTPException(
            409,
            "Es ist kein Sprachmodell hinterlegt. Adresse und Modellname stehen unter Einstellungen.",
        )

    felderliste = KONTAKT_FELDER if art == "contact" else FIRMEN_FELDER
    was = "eine Person" if art == "contact" else "eine Firma"
    frage = (
        f"Hier stehen Angaben über {was}. Ordne sie diesen Feldern zu:\n{felderliste}\n"
        'Antworte als {"felder": {…}, "rest": "was in kein Feld passte"}.\n'
        "Lass jedes Feld weg, für das nichts dasteht. Rate nichts.\n\n"
    )
    frage += f"Angaben:\n{text}" if text.strip() else "Die Angaben stehen im Bild."

    try:
        antwort = await chat(cfg, SYSTEM, frage, temperature=0.0, max_tokens=6000, bilder=bilder or None)
    except LLMNichtEingerichtet as exc:
        raise HTTPException(409, str(exc)) from exc
    except httpx.HTTPStatusError as exc:
        # Ein Modell ohne Augen antwortet auf ein Bild mit 400. Das ist
        # eine andere Auskunft als „Endpunkt aus" und gehört so gesagt.
        if bilder and exc.response.status_code in (400, 415, 422):
            raise HTTPException(
                422,
                "Das eingestellte Modell kann keine Bilder lesen. Tragen Sie unter "
                "Einstellungen ein Modell mit Bildverständnis ein, oder fügen Sie den "
                "Text ein statt des Bildes.",
            ) from exc
        raise HTTPException(502, f"Der Endpunkt hat mit {exc.response.status_code} geantwortet.") from exc
    except httpx.RequestError as exc:
        raise HTTPException(502, f"Der Endpunkt {cfg.base_url} ist nicht erreichbar: {exc}") from exc

    try:
        roh = json_aus_antwort(antwort)
    except ValueError as exc:
        raise HTTPException(502, f"Das Modell hat kein verwertbares Ergebnis geliefert: {exc}") from exc

    felder = _saubern(art, roh.get("felder") if isinstance(roh, dict) else {})
    if not felder:
        raise HTTPException(
            422,
            "Daraus ließ sich nichts lesen. Steht ein Name darin, oder ist das Bild zu unscharf?",
        )

    async with acquire_as(user.user_id) as conn:
        gefunden = await _dublette(conn, art, felder, user.org_id)

    rest = roh.get("rest") if isinstance(roh, dict) else None
    return Vorschlag(
        art=art,
        felder=felder,
        rest=str(rest).strip()[:2000] if rest else None,
        modell=cfg.model,
        dublette={k: (str(v) if v is not None else None) for k, v in gefunden.items()} if gefunden else None,
    )


class TextEingabe(BaseModel):
    art: Literal["contact", "company"] = "contact"
    text: str = Field(min_length=3, max_length=20000)


@router.post("/text", response_model=Vorschlag)
async def aus_text(
    payload: TextEingabe,
    user: CurrentUser = Depends(get_current_user),
) -> Vorschlag:
    """Eine Signatur, ein Messezettel, drei Zeilen aus einer Mail."""
    return await _lesen(user, payload.art, payload.text, [])


@router.post("/bild", response_model=Vorschlag)
async def aus_bild(
    art: Literal["contact", "company"] = Form("contact"),
    text: str = Form(""),
    datei: UploadFile = File(...),
    user: CurrentUser = Depends(get_current_user),
) -> Vorschlag:
    """Ein Screenshot oder das Foto einer Visitenkarte.

    Das Bild wird nicht abgelegt. Es geht einmal an das Modell und ist
    danach vergessen — ein CRM ist kein Bildarchiv, und ein Foto, das
    niemand mehr ansieht, ist nur noch ein Datenschutzrisiko.
    """
    if datei.content_type not in ERLAUBTE_TYPEN:
        raise HTTPException(
            415,
            f"„{datei.content_type}“ lässt sich nicht lesen. PNG, JPEG, WebP oder GIF.",
        )
    roh = await datei.read(BILD_MAX_BYTES + 1)
    if len(roh) > BILD_MAX_BYTES:
        raise HTTPException(413, "Das Bild ist größer als 6 MB. Ein Ausschnitt genügt meist.")
    if not roh:
        raise HTTPException(400, "Die Datei ist leer.")

    daten_url = f"data:{datei.content_type};base64,{base64.b64encode(roh).decode()}"
    return await _lesen(user, art, text, [daten_url])
