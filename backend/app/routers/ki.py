"""Der KI-Teil.

Zwei Regeln, die überall gelten:

1. Jedes Ergebnis wird als Aktivität der Art `ai` festgehalten. Was ein
   Modell geschrieben hat, ist im Verlauf als solches zu erkennen — auch
   in einem Jahr noch.
2. Von Hand Geschriebenes wird nie überschrieben. Die Zusammenfassung
   liegt in `ai_summary`, die Beschreibung bleibt, wie sie war.
"""

from uuid import UUID

import httpx
import orjson
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.auth import CurrentUser, get_current_user
from app.db import acquire_as
from app.llm import LLMNichtEingerichtet, chat, load_llm_config

router = APIRouter(prefix="/api/ki", tags=["ki"])

SYSTEM = (
    "Du unterstützt den Vertrieb von AImighty. AImighty liefert lokal betriebene "
    "KI-Systeme an den deutschen Mittelstand — Hardware, Software und Einführung aus "
    "einer Hand, ohne Cloud. Die drei Produkte: Assistent (9.900 €, ein Werkzeug), "
    "Analyst (14.500 €, ein Kollege), Experte (14.500 € plus Leistungen, ein Prozess). "
    "Antworte auf Deutsch, in der Sie-Form, sachlich und ohne Werbesprache. "
    "Schreibe nichts, was nicht aus den übergebenen Daten hervorgeht — was du nicht "
    "weißt, benennst du als offene Frage."
)


class KIStatus(BaseModel):
    ready: bool
    model: str = ""
    hint: str = ""


class KIErgebnis(BaseModel):
    text: str
    model: str


class EntwurfIn(BaseModel):
    contact_id: UUID
    anlass: str
    kanal: str = "email"


@router.get("/status", response_model=KIStatus)
async def status(user: CurrentUser = Depends(get_current_user)) -> KIStatus:
    async with acquire_as(user.user_id) as conn:
        cfg = await load_llm_config(conn, user.org_id)
    if not cfg.eingerichtet:
        return KIStatus(
            ready=False,
            hint="Kein Sprachmodell hinterlegt. Adresse und Modellname stehen unter Einstellungen.",
        )
    return KIStatus(ready=True, model=cfg.model or "(Vorgabe des Endpunkts)")


async def _lauf(user: CurrentUser, prompt: str) -> tuple[str, str]:
    """Einen Modellaufruf ausführen und die Fehler übersetzen.

    Ein Endpunkt auf der eigenen Box ist gelegentlich einfach aus — das ist
    kein Serverfehler dieser Anwendung, und die Oberfläche soll es auch
    nicht so nennen.
    """
    async with acquire_as(user.user_id) as conn:
        cfg = await load_llm_config(conn, user.org_id)
    try:
        text = await chat(cfg, SYSTEM, prompt)
    except LLMNichtEingerichtet as exc:
        raise HTTPException(409, str(exc)) from exc
    except httpx.HTTPStatusError as exc:
        raise HTTPException(
            502, f"Der Endpunkt hat mit {exc.response.status_code} geantwortet."
        ) from exc
    except httpx.RequestError as exc:
        raise HTTPException(
            502, f"Der Endpunkt {cfg.base_url} ist nicht erreichbar: {exc}"
        ) from exc
    return text, cfg.model


async def _kontext_firma(user: CurrentUser, company_id: UUID) -> str:
    async with acquire_as(user.user_id) as conn:
        firma = await conn.fetchrow(
            "select * from public.companies where id = $1 and deleted_at is null", company_id
        )
        if firma is None:
            raise HTTPException(404, "Firma nicht gefunden")
        kontakte = await conn.fetch(
            "select first_name, last_name, job_title, buying_role from public.contacts "
            "where company_id = $1 and deleted_at is null limit 20",
            company_id,
        )
        deals = await conn.fetch(
            "select d.name, d.amount_cents, d.product, s.name as stufe from public.deals d "
            "join public.pipeline_stages s on s.id = d.stage_id "
            "where d.company_id = $1 and d.deleted_at is null limit 20",
            company_id,
        )
        verlauf = await conn.fetch(
            """
            select kind, subject, body, occurred_at from public.activities
            where company_id = $1
               or contact_id in (select id from public.contacts where company_id = $1)
               or deal_id in (select id from public.deals where company_id = $1)
            order by occurred_at desc limit 30
            """,
            company_id,
        )

    zeilen = [
        f"Firma: {firma['name']}",
        f"Branche: {firma['industry'] or 'unbekannt'}",
        f"Mitarbeiter: {firma['employee_count'] or 'unbekannt'}",
        f"Ort: {firma['city'] or 'unbekannt'}",
        f"Stufe: {firma['lifecycle_stage']}",
        f"Notiz: {firma['description'] or '—'}",
        "",
        "Kontakte:",
        *(
            [
                f"- {k['first_name'] or ''} {k['last_name'] or ''}"
                f" ({k['job_title'] or 'Rolle unbekannt'}, {k['buying_role'] or 'Kaufrolle offen'})"
                for k in kontakte
            ]
            or ["- keine"]
        ),
        "",
        "Geschäfte:",
        *(
            [
                f"- {d['name']}: {d['amount_cents'] / 100:.0f} €, {d['product']}, Stufe {d['stufe']}"
                for d in deals
            ]
            or ["- keine"]
        ),
        "",
        "Verlauf (neueste zuerst):",
        *(
            [
                f"- {v['occurred_at']:%d.%m.%Y} [{v['kind']}] {v['subject'] or ''} {(v['body'] or '')[:400]}"
                for v in verlauf
            ]
            or ["- leer"]
        ),
    ]
    return "\n".join(zeilen)


@router.post("/companies/{company_id}/zusammenfassung", response_model=KIErgebnis)
async def firma_zusammenfassen(
    company_id: UUID,
    user: CurrentUser = Depends(get_current_user),
) -> KIErgebnis:
    kontext = await _kontext_firma(user, company_id)
    text, model = await _lauf(
        user,
        "Fasse den Stand dieser Firma für das nächste Gespräch zusammen. Höchstens acht "
        "Sätze. Danach zwei eigene Zeilen, die mit 'Nächster Schritt:' und "
        "'Offene Frage:' beginnen.\n\n" + kontext,
    )

    async with acquire_as(user.user_id) as conn:
        await conn.execute(
            "update public.companies set ai_summary = $1, ai_summary_at = now() where id = $2",
            text,
            company_id,
        )
        await conn.execute(
            """
            insert into public.activities (org_id, kind, subject, body, company_id, payload, created_by)
            values ($1, 'ai', 'Zusammenfassung erzeugt', $2, $3, $4::jsonb, $5)
            """,
            user.org_id,
            text,
            company_id,
            orjson.dumps({"modell": model}).decode(),
            user.user_id,
        )
    return KIErgebnis(text=text, model=model)


@router.post("/deals/{deal_id}/naechster-schritt", response_model=KIErgebnis)
async def deal_naechster_schritt(
    deal_id: UUID,
    user: CurrentUser = Depends(get_current_user),
) -> KIErgebnis:
    async with acquire_as(user.user_id) as conn:
        deal = await conn.fetchrow(
            "select d.*, f.name as firma, s.name as stufe, s.probability from public.deals d "
            "left join public.companies f on f.id = d.company_id "
            "join public.pipeline_stages s on s.id = d.stage_id "
            "where d.id = $1 and d.deleted_at is null",
            deal_id,
        )
        if deal is None:
            raise HTTPException(404, "Deal nicht gefunden")
        verlauf = await conn.fetch(
            "select kind, subject, body, occurred_at from public.activities "
            "where deal_id = $1 order by occurred_at desc limit 20",
            deal_id,
        )

    kontext = "\n".join(
        [
            f"Geschäft: {deal['name']}",
            f"Firma: {deal['firma'] or 'ohne Firma'}",
            f"Produkt: {deal['product']}",
            f"Betrag: {deal['amount_cents'] / 100:.0f} €",
            f"Stufe: {deal['stufe']} (Wahrscheinlichkeit {float(deal['probability']):.0%})",
            f"Abschluss geplant: {deal['close_date'] or 'offen'}",
            f"Bisher notierter nächster Schritt: {deal['next_step'] or '—'}",
            "",
            "Verlauf:",
            *(
                [
                    f"- {v['occurred_at']:%d.%m.%Y} [{v['kind']}] {v['subject'] or ''} {(v['body'] or '')[:300]}"
                    for v in verlauf
                ]
                or ["- leer"]
            ),
        ]
    )

    text, model = await _lauf(
        user,
        "Nenne den einen nächsten Schritt, der dieses Geschäft weiterbringt, und begründe "
        "ihn in höchstens drei Sätzen. Nenne danach das größte Risiko.\n\n" + kontext,
    )

    async with acquire_as(user.user_id) as conn:
        await conn.execute(
            "update public.deals set ai_summary = $1, ai_summary_at = now() where id = $2",
            text,
            deal_id,
        )
        await conn.execute(
            """
            insert into public.activities (org_id, kind, subject, body, deal_id, payload, created_by)
            values ($1, 'ai', 'Nächster Schritt vorgeschlagen', $2, $3, $4::jsonb, $5)
            """,
            user.org_id,
            text,
            deal_id,
            orjson.dumps({"modell": model}).decode(),
            user.user_id,
        )
    return KIErgebnis(text=text, model=model)


@router.post("/entwurf", response_model=KIErgebnis)
async def entwurf(payload: EntwurfIn, user: CurrentUser = Depends(get_current_user)) -> KIErgebnis:
    """Anschreiben-Entwurf. Er wird nirgends versendet, nur hingelegt."""
    async with acquire_as(user.user_id) as conn:
        kontakt = await conn.fetchrow(
            "select k.*, f.name as firma, f.industry, f.employee_count from public.contacts k "
            "left join public.companies f on f.id = k.company_id "
            "where k.id = $1 and k.deleted_at is null",
            payload.contact_id,
        )
        if kontakt is None:
            raise HTTPException(404, "Kontakt nicht gefunden")

    kontext = "\n".join(
        [
            f"Empfänger: {kontakt['first_name'] or ''} {kontakt['last_name'] or ''}",
            f"Position: {kontakt['job_title'] or 'unbekannt'}",
            f"Firma: {kontakt['firma'] or 'unbekannt'}",
            f"Branche: {kontakt['industry'] or 'unbekannt'}",
            f"Mitarbeiter: {kontakt['employee_count'] or 'unbekannt'}",
            f"Notizen: {kontakt['notes'] or '—'}",
            f"Anlass: {payload.anlass}",
            f"Kanal: {payload.kanal}",
        ]
    )
    text, model = await _lauf(
        user,
        "Schreibe einen Entwurf für diese Ansprache. Höchstens 150 Wörter, ein konkreter "
        "Bezug zum Empfänger, genau eine Frage am Schluss. Keine Superlative.\n\n" + kontext,
    )

    async with acquire_as(user.user_id) as conn:
        await conn.execute(
            """
            insert into public.activities (org_id, kind, subject, body, contact_id, payload, created_by)
            values ($1, 'ai', 'Entwurf erzeugt', $2, $3, $4::jsonb, $5)
            """,
            user.org_id,
            text,
            payload.contact_id,
            orjson.dumps({"modell": model, "anlass": payload.anlass}).decode(),
            user.user_id,
        )
    return KIErgebnis(text=text, model=model)
