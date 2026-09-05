"""Fragen an den eigenen Bestand.

Kein Vektorindex. Der wäre der übliche Weg, aber er kostet eine
Erweiterung, ein Einbettungsmodell und einen Hintergrundlauf, der die
Einbettungen aktuell hält — für einen Bestand, den zwei Leute pflegen,
ist das viel Maschinerie für wenig Gewinn. Gesucht wird mit dem, was
Postgres ohnehin kann: Wortsuche über die Felder, in denen die Antwort
stehen kann.

Geantwortet wird ausschließlich aus dem Gefundenen. Was nicht in den
Fundstellen steht, ist keine Antwort — auch wenn das Modell es zu wissen
glaubt.
"""

from typing import Any
from uuid import UUID

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.auth import CurrentUser, get_current_user
from app.db import acquire_as
from app.llm import LLMNichtEingerichtet, chat, load_llm_config

router = APIRouter(prefix="/api/fragen", tags=["fragen"])

# Wörter, die in jeder Frage vorkommen und nichts eingrenzen. Ohne diese
# Liste sucht „Welche Firma hat das größte Geschäft?" nach „welche" und
# findet alles.
FUELLWOERTER = {
    "welche", "welcher", "welches", "wer", "was", "wann", "wie", "warum", "wo", "wieso",
    "hat", "haben", "habe", "ist", "sind", "war", "waren", "wird", "werden", "wurde",
    "der", "die", "das", "den", "dem", "des", "ein", "eine", "einer", "eines", "einem",
    "und", "oder", "aber", "nicht", "kein", "keine", "mit", "ohne", "von", "vom", "zum",
    "zur", "bei", "für", "auf", "aus", "über", "unter", "durch", "gegen", "noch", "schon",
    "alle", "allen", "aller", "mir", "mich", "wir", "uns", "ich", "sie", "ihr", "man",
    "gibt", "sich", "auch", "mehr", "sehr", "viel", "viele", "letzten", "letzte", "diesem",
}

MINDESTLAENGE = 3


# Ab dieser Länge wird zusätzlich mit dem Wortanfang gesucht.
KOMPOSITUM_AB = 9
KOMPOSITUM_KOPF = 6


def suchbegriffe(frage: str) -> list[str]:
    """Die Wörter, mit denen sich suchen lässt."""
    roh = "".join(z if z.isalnum() or z.isspace() else " " for z in frage.lower())
    return [
        w for w in roh.split() if len(w) >= MINDESTLAENGE and w not in FUELLWOERTER
    ][:8]


def suchmuster(begriffe: list[str]) -> list[str]:
    """Aus Begriffen werden Muster — und zwar mehr als eines je Begriff.

    Deutsch setzt Wörter zusammen. Eine Notiz, in der „die Kammer verlangt"
    steht, wird von `%kammerauflage%` nicht gefunden, obwohl sie genau die
    gesuchte Stelle ist. Deshalb sucht ein langer Begriff zusätzlich mit
    seinem Anfang: `%kammer%` findet beides.

    Das holt Treffer herein, die nicht gemeint waren — bei einem Bestand,
    den zwei Leute pflegen, ist das der richtige Tausch. Aussortieren kann
    das Modell; was gar nicht gefunden wurde, kann es nicht.
    """
    muster: list[str] = []
    for begriff in begriffe:
        muster.append(f"%{begriff}%")
        if len(begriff) >= KOMPOSITUM_AB:
            kopf = f"%{begriff[:KOMPOSITUM_KOPF]}%"
            if kopf not in muster:
                muster.append(kopf)
    return muster


class Fundstelle(BaseModel):
    art: str
    id: UUID | None = None
    titel: str
    text: str


class Antwort(BaseModel):
    antwort: str
    fundstellen: list[Fundstelle] = []
    modell: str
    # Wenn nichts gefunden wurde, wird gar nicht erst gefragt. Ein Modell,
    # das ohne Fundstellen antwortet, antwortet aus dem Gedächtnis — und
    # das kennt diesen Vertrieb nicht.
    hinweis: str | None = None


class Frage(BaseModel):
    frage: str = Field(min_length=3, max_length=500)
    hoechstens: int = Field(default=25, ge=5, le=60)


async def _suchen(conn, begriffe: list[str], grenze: int) -> list[Fundstelle]:
    if not begriffe:
        return []

    muster = suchmuster(begriffe)
    treffer: list[Fundstelle] = []

    firmen = await conn.fetch(
        """
        select id, name, industry, city, description, ai_summary, lifecycle_stage
        from public.companies
        where deleted_at is null
          and (name ilike any($1) or industry ilike any($1) or city ilike any($1)
               or description ilike any($1) or ai_summary ilike any($1)
               or custom::text ilike any($1))
        limit $2
        """,
        muster,
        grenze,
    )
    treffer += [
        Fundstelle(
            art="Firma",
            id=z["id"],
            titel=z["name"],
            text=f"{z['industry'] or 'Branche unbekannt'}, {z['city'] or 'Ort unbekannt'}, "
            f"Stufe {z['lifecycle_stage']}. {z['description'] or ''} {z['ai_summary'] or ''}".strip(),
        )
        for z in firmen
    ]

    kontakte = await conn.fetch(
        """
        select k.id, k.first_name, k.last_name, k.job_title, k.buying_role, k.email,
               k.notes, f.name as firma
        from public.contacts k
        left join public.companies f on f.id = k.company_id
        where k.deleted_at is null
          and (k.first_name ilike any($1) or k.last_name ilike any($1)
               or k.job_title ilike any($1) or k.email ilike any($1)
               or k.notes ilike any($1) or f.name ilike any($1)
               or k.custom::text ilike any($1))
        limit $2
        """,
        muster,
        grenze,
    )
    treffer += [
        Fundstelle(
            art="Kontakt",
            id=z["id"],
            titel=" ".join(t for t in (z["first_name"], z["last_name"]) if t).strip() or "Ohne Namen",
            text=f"{z['job_title'] or 'Rolle unbekannt'} bei {z['firma'] or 'unbekannt'}, "
            f"Kaufrolle {z['buying_role'] or 'offen'}. {z['notes'] or ''}".strip(),
        )
        for z in kontakte
    ]

    deals = await conn.fetch(
        """
        select d.id, d.name, d.amount_cents, d.product, d.next_step, d.bedarf, d.ausloeser,
               d.entscheider, d.close_date, s.name as stufe, f.name as firma
        from public.deals d
        join public.pipeline_stages s on s.id = d.stage_id
        left join public.companies f on f.id = d.company_id
        where d.deleted_at is null
          and (d.name ilike any($1) or d.next_step ilike any($1) or d.bedarf ilike any($1)
               or d.ausloeser ilike any($1) or d.entscheider ilike any($1)
               or f.name ilike any($1) or d.product::text ilike any($1)
               or d.custom::text ilike any($1))
        limit $2
        """,
        muster,
        grenze,
    )
    treffer += [
        Fundstelle(
            art="Lead",
            id=z["id"],
            titel=z["name"],
            text=f"{z['firma'] or 'ohne Firma'}, {z['amount_cents'] / 100:.0f} €, "
            f"Produkt {z['product']}, Stufe {z['stufe']}, "
            f"Abschluss {z['close_date'] or 'offen'}. "
            f"Bedarf: {z['bedarf'] or '—'}. Auslöser: {z['ausloeser'] or '—'}. "
            f"Entscheider: {z['entscheider'] or '—'}. "
            f"Nächster Schritt: {z['next_step'] or '—'}",
        )
        for z in deals
    ]

    aktivitaeten = await conn.fetch(
        """
        select a.id, a.kind, a.subject, a.body, a.occurred_at,
               coalesce(f.name, ff.name, fd.name) as firma
        from public.activities a
        left join public.companies f on f.id = a.company_id
        left join public.contacts k on k.id = a.contact_id
        left join public.companies ff on ff.id = k.company_id
        left join public.deals d on d.id = a.deal_id
        left join public.companies fd on fd.id = d.company_id
        where a.subject ilike any($1) or a.body ilike any($1)
        order by a.occurred_at desc
        limit $2
        """,
        muster,
        grenze,
    )
    treffer += [
        Fundstelle(
            art="Verlauf",
            id=z["id"],
            titel=f"{z['occurred_at']:%d.%m.%Y} {z['subject'] or z['kind']}"
            + (f" — {z['firma']}" if z["firma"] else ""),
            text=(z["body"] or "")[:800],
        )
        for z in aktivitaeten
    ]

    return treffer[:grenze]


@router.post("", response_model=Antwort)
async def fragen(payload: Frage, user: CurrentUser = Depends(get_current_user)) -> Antwort:
    begriffe = suchbegriffe(payload.frage)

    async with acquire_as(user.user_id) as conn:
        cfg = await load_llm_config(conn, user.org_id)
        fundstellen = await _suchen(conn, begriffe, payload.hoechstens)

    if not fundstellen:
        return Antwort(
            antwort="",
            modell=cfg.model,
            hinweis="Dazu steht nichts im Bestand. Es wurde kein Modell gefragt — eine "
            "Antwort ohne Fundstelle wäre aus dem Gedächtnis geraten, und das kennt "
            "diesen Vertrieb nicht.",
        )

    if not cfg.eingerichtet:
        # Ohne Modell trotzdem brauchbar: Die Fundstellen sind das
        # Ergebnis, nur eben unkommentiert.
        return Antwort(
            antwort="",
            fundstellen=fundstellen,
            modell="",
            hinweis="Kein Sprachmodell hinterlegt. Unten stehen die Fundstellen, die zur "
            "Frage passen.",
        )

    belege = "\n\n".join(
        f"[{i + 1}] {f.art}: {f.titel}\n{f.text}" for i, f in enumerate(fundstellen)
    )

    from app.routers.ki import SYSTEM

    try:
        text = await chat(
            cfg,
            SYSTEM,
            "Beantworte die Frage ausschließlich aus den Fundstellen unten. "
            "Verweise auf die Nummern in eckigen Klammern. Was dort nicht steht, "
            "beantwortest du mit dem Satz, dass es im Bestand nicht steht — rate nicht.\n\n"
            f"Frage: {payload.frage}\n\nFundstellen:\n{belege}",
            temperature=0.1,
        )
    except LLMNichtEingerichtet as exc:
        raise HTTPException(409, str(exc)) from exc
    except httpx.HTTPStatusError as exc:
        raise HTTPException(502, f"Der Endpunkt hat mit {exc.response.status_code} geantwortet.") from exc
    except httpx.RequestError as exc:
        raise HTTPException(502, f"Der Endpunkt {cfg.base_url} ist nicht erreichbar: {exc}") from exc

    return Antwort(antwort=text, fundstellen=fundstellen, modell=cfg.model)


@router.get("/probe", response_model=dict[str, Any])
async def probe(frage: str, _user: CurrentUser = Depends(get_current_user)) -> dict[str, Any]:
    """Zeigt, wonach eine Frage tatsächlich sucht.

    Nützlich, wenn eine Frage nichts findet: Meist liegt es daran, dass
    alle tragenden Wörter Füllwörter waren.
    """
    return {"frage": frage, "begriffe": suchbegriffe(frage)}
