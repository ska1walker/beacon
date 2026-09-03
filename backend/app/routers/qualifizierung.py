"""Qualifizierung, Verlustgründe und Prognose."""

from datetime import date
from uuid import UUID

import orjson
from fastapi import APIRouter, Depends, HTTPException, Query

from app import audit, qualifizierung
from app.auth import CurrentUser, get_current_user
from app.db import acquire_as
from app.schemas import (
    DealVerloren,
    Monatswert,
    Produktanteil,
    Prognose,
    Qualifizierung,
    QualifizierungAntwort,
    Verlustanteil,
    Verlustgrund,
)

router = APIRouter(prefix="/api", tags=["qualifizierung"])

FELDER = ("bedarf", "ausloeser", "entscheider", "budget_geklaert", "zeitrahmen", "standort_geklaert")


def _antwort(zeile) -> QualifizierungAntwort:
    q = Qualifizierung(**{f: zeile[f] for f in FELDER})
    return QualifizierungAntwort(
        **q.model_dump(),
        punkte=qualifizierung.punkte(q),
        qualifikation_am=zeile["qualifikation_am"],
        offen=qualifizierung.offen(q),
    )


@router.get("/qualifizierung/schema", response_model=list[dict])
async def schema() -> list[dict]:
    """Felder, Gewichte und Fragen — die eine Quelle für beide Seiten.

    Ohne das stünden die Gewichte auch in der Oberfläche, damit sie beim
    Tippen eine Vorschau rechnen kann. Zwei Listen, die dasselbe bedeuten
    sollen, laufen auseinander — und dann zeigt die Maske 70 an, während
    die Prognose mit 55 rechnet.
    """
    return [
        {
            "feld": feld,
            "gewicht": gewicht,
            "frage": frage,
            "art": "ja_nein" if feld.endswith("_geklaert") else "text",
        }
        for feld, gewicht, frage in qualifizierung.GEWICHTE
    ]


@router.get("/deals/{deal_id}/qualifizierung", response_model=QualifizierungAntwort)
async def lesen(deal_id: UUID, user: CurrentUser = Depends(get_current_user)) -> QualifizierungAntwort:
    async with acquire_as(user.user_id) as conn:
        zeile = await conn.fetchrow(
            f"select {', '.join(FELDER)}, qualifikation_am from public.deals "
            f"where id = $1 and deleted_at is null",
            deal_id,
        )
    if zeile is None:
        raise HTTPException(404, "Deal nicht gefunden")
    return _antwort(zeile)


@router.put("/deals/{deal_id}/qualifizierung", response_model=QualifizierungAntwort)
async def schreiben(
    deal_id: UUID,
    payload: Qualifizierung,
    user: CurrentUser = Depends(get_current_user),
) -> QualifizierungAntwort:
    wert = qualifizierung.punkte(payload)
    async with acquire_as(user.user_id) as conn:
        zeile = await conn.fetchrow(
            """
            update public.deals
               set bedarf = $1, ausloeser = $2, entscheider = $3, budget_geklaert = $4,
                   zeitrahmen = $5, standort_geklaert = $6,
                   qualifikation_punkte = $7, qualifikation_am = now()
             where id = $8 and deleted_at is null
            returning bedarf, ausloeser, entscheider, budget_geklaert, zeitrahmen,
                      standort_geklaert, qualifikation_am
            """,
            payload.bedarf,
            payload.ausloeser,
            payload.entscheider,
            payload.budget_geklaert,
            payload.zeitrahmen,
            payload.standort_geklaert,
            wert,
            deal_id,
        )
        if zeile is None:
            raise HTTPException(404, "Deal nicht gefunden")
        await audit.log_fuer(
            conn,
            user,
            action="update",
            entity="deals",
            entity_id=deal_id,
            diff={"qualifikation_punkte": wert},
        )
    return _antwort(zeile)


# ── Verlustgründe ───────────────────────────────────────────────────────

@router.get("/verlustgruende", response_model=list[Verlustgrund])
async def verlustgruende(user: CurrentUser = Depends(get_current_user)) -> list[Verlustgrund]:
    async with acquire_as(user.user_id) as conn:
        zeilen = await conn.fetch(
            "select * from public.loss_reasons where is_active order by position, name"
        )
    return [Verlustgrund(**dict(z)) for z in zeilen]


@router.post("/deals/{deal_id}/verloren", response_model=dict)
async def verloren(
    deal_id: UUID,
    payload: DealVerloren,
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    """Setzt den Grund an einem verlorenen Geschäft.

    Getrennt vom Stufenwechsel, weil der Grund oft erst später bekannt
    wird — im Moment der Absage sagt niemand die Wahrheit, drei Tage
    später am Telefon schon.
    """
    async with acquire_as(user.user_id) as conn:
        if payload.lost_reason_id:
            bekannt = await conn.fetchval(
                "select 1 from public.loss_reasons where id = $1", payload.lost_reason_id
            )
            if not bekannt:
                raise HTTPException(400, "Diesen Verlustgrund gibt es nicht.")

        zeile = await conn.fetchrow(
            """
            update public.deals
               set lost_reason_id = $1, lost_reason = coalesce($2, lost_reason)
             where id = $3 and deleted_at is null
            returning id
            """,
            payload.lost_reason_id,
            payload.lost_reason,
            deal_id,
        )
        if zeile is None:
            raise HTTPException(404, "Deal nicht gefunden")

        name = None
        if payload.lost_reason_id:
            name = await conn.fetchval(
                "select name from public.loss_reasons where id = $1", payload.lost_reason_id
            )
        await conn.execute(
            """
            insert into public.activities (org_id, kind, subject, body, deal_id, payload, created_by)
            values ($1, 'system', $2, $3, $4, $5::jsonb, $6)
            """,
            user.org_id,
            f"Verlustgrund: {name or 'ohne Kategorie'}",
            payload.lost_reason,
            deal_id,
            orjson.dumps({"grund": name}).decode(),
            user.user_id,
        )
    return {"gespeichert": True, "grund": name}


# ── Prognose ────────────────────────────────────────────────────────────

@router.get("/prognose", response_model=Prognose)
async def prognose(
    user: CurrentUser = Depends(get_current_user),
    von: date | None = Query(None, description="Vorgabe: Anfang des laufenden Jahres"),
    bis: date | None = Query(None),
) -> Prognose:
    """Was offen ist, was entschieden wurde und woran es lag.

    Der Zeitraum gilt für die *entschiedenen* Geschäfte — offene zählen
    immer alle, unabhängig vom Zeitraum. Ein Filter auf offene Geschäfte
    nach Abschlussdatum verstecke sonst genau die, deren Datum längst
    verstrichen ist.
    """
    heute = date.today()
    von = von or date(heute.year, 1, 1)
    bis = bis or date(heute.year, 12, 31)

    async with acquire_as(user.user_id) as conn:
        offene = await conn.fetch(
            """
            select d.amount_cents, d.close_date, s.probability
            from public.deals d
            join public.pipeline_stages s on s.id = d.stage_id
            where d.deleted_at is null and s.kind = 'open'
            """
        )
        entschieden = await conn.fetch(
            """
            select d.amount_cents, d.product, d.created_at, d.closed_at,
                   s.kind, g.name as grund
            from public.deals d
            join public.pipeline_stages s on s.id = d.stage_id
            left join public.loss_reasons g on g.id = d.lost_reason_id
            where d.deleted_at is null and s.kind in ('won','lost')
              and d.closed_at is not null
              and d.closed_at::date between $1 and $2
            """,
            von,
            bis,
        )

    offen_cents = sum(z["amount_cents"] for z in offene)
    gewichtet = sum(round(z["amount_cents"] * float(z["probability"])) for z in offene)

    # Nach Monat des geplanten Abschlusses. Was kein Datum hat, taucht
    # nirgends auf — und genau das ist die Aussage: Ein Geschäft ohne
    # Abschlussdatum lässt sich nicht prognostizieren.
    nach_monat: dict[str, Monatswert] = {}
    for z in offene:
        if not z["close_date"]:
            continue
        schluessel = z["close_date"].strftime("%Y-%m")
        eintrag = nach_monat.setdefault(
            schluessel, Monatswert(monat=schluessel, offen_cents=0, gewichtet_cents=0, anzahl=0)
        )
        eintrag.offen_cents += z["amount_cents"]
        eintrag.gewichtet_cents += round(z["amount_cents"] * float(z["probability"]))
        eintrag.anzahl += 1

    gewonnen = [z for z in entschieden if z["kind"] == "won"]
    verloren = [z for z in entschieden if z["kind"] == "lost"]

    gruende: dict[str, Verlustanteil] = {}
    for z in verloren:
        name = z["grund"] or "ohne Kategorie"
        eintrag = gruende.setdefault(name, Verlustanteil(grund=name, anzahl=0, summe_cents=0))
        eintrag.anzahl += 1
        eintrag.summe_cents += z["amount_cents"]

    produkte: dict[str, Produktanteil] = {}
    for z in entschieden:
        eintrag = produkte.setdefault(
            z["product"],
            Produktanteil(produkt=z["product"], gewonnen=0, verloren=0, gewonnen_cents=0),
        )
        if z["kind"] == "won":
            eintrag.gewonnen += 1
            eintrag.gewonnen_cents += z["amount_cents"]
        else:
            eintrag.verloren += 1

    dauern = [
        (z["closed_at"].date() - z["created_at"].date()).days
        for z in gewonnen
        if z["closed_at"] and z["created_at"]
    ]
    ueberfaellig = [z for z in offene if z["close_date"] and z["close_date"] < heute]

    return Prognose(
        offen_cents=offen_cents,
        gewichtet_cents=gewichtet,
        anzahl_offen=len(offene),
        gewonnen_cents=sum(z["amount_cents"] for z in gewonnen),
        anzahl_gewonnen=len(gewonnen),
        verloren_cents=sum(z["amount_cents"] for z in verloren),
        anzahl_verloren=len(verloren),
        # None, nicht 0: „noch kein Abschluss" und „nichts gewonnen" sind
        # zwei sehr verschiedene Nachrichten.
        trefferquote=(len(gewonnen) / len(entschieden)) if entschieden else None,
        durchschnittsdauer_tage=(sum(dauern) / len(dauern)) if dauern else None,
        durchschnittswert_cents=(
            round(sum(z["amount_cents"] for z in gewonnen) / len(gewonnen)) if gewonnen else None
        ),
        monate=sorted(nach_monat.values(), key=lambda m: m.monat),
        verlustgruende=sorted(gruende.values(), key=lambda g: -g.anzahl),
        produkte=sorted(produkte.values(), key=lambda p: -p.gewonnen_cents),
        ueberfaellig_anzahl=len(ueberfaellig),
        ueberfaellig_cents=sum(z["amount_cents"] for z in ueberfaellig),
    )
