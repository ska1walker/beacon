"""Das Tagesbriefing.

Die Fakten kommen aus der Datenbank, nicht aus dem Modell. Das ist die
wichtigste Entscheidung an dieser Stelle: Ein Sprachmodell, das aus einer
Datenlage eine Zahl ableitet, leitet sie manchmal falsch ab — und ein
Briefing, dem man nicht trauen kann, liest niemand zweimal.

Das Modell darf ordnen und begründen. Zählen darf es nicht.
"""

from datetime import date, datetime, timedelta

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from app.auth import CurrentUser, get_current_user
from app.db import acquire_as
from app.llm import LLMNichtEingerichtet, chat, load_llm_config
from app.routers.ki import SYSTEM

router = APIRouter(prefix="/api/briefing", tags=["briefing"])

# Ab wann ein Geschäft als verstummt gilt. Zwei Wochen ohne ein Wort sind
# im Mittelstandsvertrieb nicht ungewöhnlich — drei sind ein Signal.
STILLE_TAGE = 21


class Posten(BaseModel):
    art: str
    titel: str
    hinweis: str | None = None
    deal_id: str | None = None
    company_id: str | None = None
    betrag_cents: int | None = None
    tage: int | None = None


class Briefing(BaseModel):
    stand: datetime
    faellige_aufgaben: list[Posten] = []
    ueberfaellige_geschaefte: list[Posten] = []
    verstummte_geschaefte: list[Posten] = []
    ablaufende_angebote: list[Posten] = []
    ohne_naechsten_schritt: list[Posten] = []
    offener_eingang: list[Posten] = []
    # Wie viele Punkte insgesamt anstehen. Eine Zahl, die man morgens
    # ansieht und die einem sagt, ob es ein ruhiger Tag wird.
    gesamt: int = 0


class BriefingText(BaseModel):
    text: str
    modell: str


async def _sammeln(user: CurrentUser) -> Briefing:
    heute = date.today()
    async with acquire_as(user.user_id) as conn:
        aufgaben = await conn.fetch(
            """
            select t.id, t.title, t.due_at, t.deal_id, t.company_id
            from public.tasks t
            where t.status = 'open' and t.due_at is not null and t.due_at::date <= $1
            order by t.due_at
            """,
            heute,
        )
        ueberfaellig = await conn.fetch(
            """
            select d.id, d.name, d.amount_cents, d.close_date, d.company_id, f.name as firma
            from public.deals d
            join public.pipeline_stages s on s.id = d.stage_id
            left join public.companies f on f.id = d.company_id
            where d.deleted_at is null and s.kind = 'open'
              and d.close_date is not null and d.close_date < $1
            order by d.close_date
            """,
            heute,
        )
        verstummt = await conn.fetch(
            """
            select d.id, d.name, d.amount_cents, d.company_id, f.name as firma,
                   greatest(
                     coalesce(max(a.occurred_at), d.created_at), d.created_at
                   ) as zuletzt
            from public.deals d
            join public.pipeline_stages s on s.id = d.stage_id
            left join public.companies f on f.id = d.company_id
            left join public.activities a on a.deal_id = d.id
            where d.deleted_at is null and s.kind = 'open'
            group by d.id, d.name, d.amount_cents, d.company_id, f.name, d.created_at
            having greatest(coalesce(max(a.occurred_at), d.created_at), d.created_at)
                   < now() - ($1 || ' days')::interval
            order by zuletzt
            """,
            str(STILLE_TAGE),
        )
        angebote = await conn.fetch(
            """
            select q.id, q.number_seq, q.created_at, q.valid_until, q.deal_id,
                   d.name as deal_name, f.name as firma
            from public.quotes q
            join public.deals d on d.id = q.deal_id
            left join public.companies f on f.id = d.company_id
            where q.deleted_at is null and q.status = 'sent'
              and q.valid_until is not null
              and q.valid_until between $1 and $2
            order by q.valid_until
            """,
            heute,
            heute + timedelta(days=7),
        )
        eingang = await conn.fetch(
            """
            select e.id, e.event, e.titel, e.created_at, e.zuordnung_grund
            from public.eingang e where e.status = 'offen' order by e.created_at desc limit 20
            """
        )
        ohne_schritt = await conn.fetch(
            """
            select d.id, d.name, d.amount_cents, d.company_id, f.name as firma, s.name as stufe
            from public.deals d
            join public.pipeline_stages s on s.id = d.stage_id
            left join public.companies f on f.id = d.company_id
            where d.deleted_at is null and s.kind = 'open' and s.probability >= 0.4
              and (d.next_step is null or btrim(d.next_step) = '')
            order by d.amount_cents desc
            """
        )

    from app.routers.angebote import nummer

    briefing = Briefing(
        stand=datetime.now(),
        faellige_aufgaben=[
            Posten(
                art="aufgabe",
                titel=z["title"],
                hinweis="überfällig" if z["due_at"].date() < heute else "heute fällig",
                deal_id=str(z["deal_id"]) if z["deal_id"] else None,
                company_id=str(z["company_id"]) if z["company_id"] else None,
                tage=(heute - z["due_at"].date()).days,
            )
            for z in aufgaben
        ],
        ueberfaellige_geschaefte=[
            Posten(
                art="geschaeft",
                titel=z["name"],
                hinweis=f"{z['firma'] or 'ohne Firma'} — Abschluss war {z['close_date']:%d.%m.}",
                deal_id=str(z["id"]),
                company_id=str(z["company_id"]) if z["company_id"] else None,
                betrag_cents=z["amount_cents"],
                tage=(heute - z["close_date"]).days,
            )
            for z in ueberfaellig
        ],
        verstummte_geschaefte=[
            Posten(
                art="stille",
                titel=z["name"],
                hinweis=f"{z['firma'] or 'ohne Firma'} — zuletzt {z['zuletzt']:%d.%m.%Y}",
                deal_id=str(z["id"]),
                company_id=str(z["company_id"]) if z["company_id"] else None,
                betrag_cents=z["amount_cents"],
                tage=(datetime.now(z["zuletzt"].tzinfo) - z["zuletzt"]).days,
            )
            for z in verstummt
        ],
        ablaufende_angebote=[
            Posten(
                art="angebot",
                titel=nummer(z["number_seq"], z["created_at"]),
                hinweis=f"{z['firma'] or 'ohne Firma'} — Frist bis {z['valid_until']:%d.%m.}",
                deal_id=str(z["deal_id"]),
                tage=(z["valid_until"] - heute).days,
            )
            for z in angebote
        ],
        offener_eingang=[
            Posten(
                art="eingang",
                titel=z["titel"] or z["event"],
                hinweis=z["zuordnung_grund"],
                tage=(datetime.now(z["created_at"].tzinfo) - z["created_at"]).days,
            )
            for z in eingang
        ],
        ohne_naechsten_schritt=[
            Posten(
                art="ohne_schritt",
                titel=z["name"],
                hinweis=f"{z['firma'] or 'ohne Firma'} — Stufe {z['stufe']}, kein nächster Schritt",
                deal_id=str(z["id"]),
                company_id=str(z["company_id"]) if z["company_id"] else None,
                betrag_cents=z["amount_cents"],
            )
            for z in ohne_schritt
        ],
    )
    briefing.gesamt = (
        len(briefing.faellige_aufgaben)
        + len(briefing.ueberfaellige_geschaefte)
        + len(briefing.verstummte_geschaefte)
        + len(briefing.ablaufende_angebote)
        + len(briefing.ohne_naechsten_schritt)
        + len(briefing.offener_eingang)
    )
    return briefing


@router.get("", response_model=Briefing)
async def briefing(user: CurrentUser = Depends(get_current_user)) -> Briefing:
    """Was heute ansteht — gezählt, nicht geschätzt."""
    return await _sammeln(user)


@router.post("/text", response_model=BriefingText)
async def briefing_text(
    user: CurrentUser = Depends(get_current_user),
    umfang: int = Query(8, ge=3, le=20, description="Höchstzahl der Punkte"),
) -> BriefingText:
    """Dieselben Fakten, vom Modell in eine Reihenfolge gebracht.

    Das Modell bekommt die fertige Liste und darf sie ordnen und
    begründen. Es zählt nichts und rechnet nichts — was es sagt, muss in
    der Liste darüber wiederzufinden sein.
    """
    daten = await _sammeln(user)
    if daten.gesamt == 0:
        return BriefingText(text="Nichts liegt an. Ein guter Tag, um jemanden anzurufen.", modell="")

    async with acquire_as(user.user_id) as conn:
        cfg = await load_llm_config(conn, user.org_id)

    def zeilen(titel: str, posten: list[Posten]) -> list[str]:
        if not posten:
            return []
        return [f"{titel}:"] + [
            f"- {p.titel}"
            + (f" ({p.hinweis})" if p.hinweis else "")
            + (f", {p.betrag_cents / 100:.0f} €" if p.betrag_cents else "")
            for p in posten
        ]

    lage = "\n".join(
        [
            *zeilen("Fällige Aufgaben", daten.faellige_aufgaben),
            *zeilen("Geschäfte mit verstrichenem Abschlussdatum", daten.ueberfaellige_geschaefte),
            *zeilen(f"Seit über {STILLE_TAGE} Tagen ohne ein Wort", daten.verstummte_geschaefte),
            *zeilen("Angebote, deren Bindefrist abläuft", daten.ablaufende_angebote),
            *zeilen("Fortgeschritten, aber ohne nächsten Schritt", daten.ohne_naechsten_schritt),
            *zeilen("Im Eingang, noch niemandem zugeordnet", daten.offener_eingang),
        ]
    )

    try:
        text = await chat(
            cfg,
            SYSTEM,
            f"Ordne die folgende Lage nach Dringlichkeit und nenne höchstens {umfang} Punkte. "
            "Je Punkt eine Zeile: was zu tun ist und warum es heute dran ist. "
            "Erfinde nichts hinzu und nenne keine Zahl, die unten nicht steht.\n\n" + lage,
            temperature=0.2,
        )
    except LLMNichtEingerichtet as exc:
        raise HTTPException(409, str(exc)) from exc
    except httpx.HTTPStatusError as exc:
        raise HTTPException(502, f"Der Endpunkt hat mit {exc.response.status_code} geantwortet.") from exc
    except httpx.RequestError as exc:
        raise HTTPException(502, f"Der Endpunkt {cfg.base_url} ist nicht erreichbar: {exc}") from exc

    return BriefingText(text=text, modell=cfg.model)
