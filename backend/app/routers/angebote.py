"""Angebote und der Produktkatalog.

Alle Summen werden gerechnet, keine gespeichert. Ein abgelegter
Zeilenbetrag neben Menge, Einzelpreis und Nachlass ist eine zweite
Wahrheit, und die beiden laufen beim ersten Tippfehler auseinander —
bemerkt wird das dann beim Kunden.
"""

from datetime import UTC, datetime
from uuid import UUID

import orjson
from fastapi import APIRouter, Depends, HTTPException, Query

from app import audit
from app.auth import CurrentUser, get_current_user
from app.db import acquire_as
from app.patching import build_update
from app.schemas import (
    Empfaenger,
    Product,
    ProductIn,
    ProductPatch,
    Quote,
    QuoteIn,
    QuoteItem,
    QuoteItemIn,
    QuotePatch,
    QuoteStatusIn,
)

router = APIRouter(prefix="/api", tags=["angebote"])


def zeilenbetrag(menge: float, einzelpreis: int, nachlass_prozent: float) -> int:
    """Betrag einer Position in Cent.

    Erst multiplizieren, dann runden — nicht umgekehrt. Bei drei Stück zu
    9.900 € mit 7,5 % Nachlass unterscheiden sich die beiden Wege um
    Cent-Beträge, und die stehen später in einer Rechnung.
    """
    return round(menge * einzelpreis * (1 - nachlass_prozent / 100))


def summen(items: list[QuoteItem], discount_cents: int, tax_rate: float) -> dict[str, int]:
    netto = sum(i.line_total_cents for i in items)
    # Ein Nachlass, der größer ist als die Summe, ergäbe einen negativen
    # Rechnungsbetrag. Er wird gedeckelt, nicht abgelehnt: Tippfehler im
    # Nachlassfeld sollen kein Angebot blockieren.
    nachlass = min(discount_cents, netto)
    zu_versteuern = netto - nachlass
    steuer = round(zu_versteuern * tax_rate)
    return {
        "net_cents": netto,
        "discount_total_cents": nachlass,
        "taxable_cents": zu_versteuern,
        "tax_cents": steuer,
        "gross_cents": zu_versteuern + steuer,
    }


def nummer(seq: int, erstellt: datetime) -> str:
    """AG-2026-0007 — sprechend, sortierbar, je Jahr wieder klein."""
    return f"AG-{erstellt.year}-{seq:04d}"


async def _angebot_laden(conn, quote_id: UUID) -> Quote:
    kopf = await conn.fetchrow(
        """
        select q.*, d.name as deal_name, d.company_id,
               f.name as company_name, f.street, f.postal_code, f.city, f.country
        from public.quotes q
        join public.deals d on d.id = q.deal_id
        left join public.companies f on f.id = d.company_id
        where q.id = $1 and q.deleted_at is null
        """,
        quote_id,
    )
    if kopf is None:
        raise HTTPException(404, "Angebot nicht gefunden")

    zeilen = await conn.fetch(
        "select * from public.quote_items where quote_id = $1 order by position, created_at",
        quote_id,
    )
    items = [
        QuoteItem(
            id=z["id"],
            product_id=z["product_id"],
            title=z["title"],
            description=z["description"],
            quantity=float(z["quantity"]),
            unit_price_cents=z["unit_price_cents"],
            discount_percent=float(z["discount_percent"]),
            position=z["position"],
            line_total_cents=zeilenbetrag(
                float(z["quantity"]), z["unit_price_cents"], float(z["discount_percent"])
            ),
        )
        for z in zeilen
    ]

    # Der Ansprechpartner ist der erste Kontakt der Firma mit einer
    # Entscheidungsrolle, sonst irgendeiner. Wer im Angebot oben steht,
    # ist eine fachliche Frage — deshalb hier und nicht in der Oberfläche.
    ansprechpartner = None
    if kopf["company_id"]:
        person = await conn.fetchrow(
            """
            select first_name, last_name from public.contacts
            where company_id = $1 and deleted_at is null
            order by (buying_role ilike '%entscheid%') desc, created_at
            limit 1
            """,
            kopf["company_id"],
        )
        if person:
            ansprechpartner = " ".join(
                t for t in (person["first_name"], person["last_name"]) if t
            ).strip() or None

    daten = {
        k: v
        for k, v in dict(kopf).items()
        if k not in {"street", "postal_code", "city", "country", "company_id"}
    }
    daten["tax_rate"] = float(daten["tax_rate"])
    return Quote(
        **daten,
        empfaenger=Empfaenger(
            name=kopf["company_name"],
            street=kopf["street"],
            postal_code=kopf["postal_code"],
            city=kopf["city"],
            country=kopf["country"],
            ansprechpartner=ansprechpartner,
        ),
        number=nummer(kopf["number_seq"], kopf["created_at"]),
        items=items,
        **summen(items, kopf["discount_cents"], float(kopf["tax_rate"])),
    )


# ── Produktkatalog ──────────────────────────────────────────────────────

@router.get("/products", response_model=list[Product])
async def list_products(
    user: CurrentUser = Depends(get_current_user),
    nur_aktive: bool = Query(True),
) -> list[Product]:
    sql = "select * from public.products"
    if nur_aktive:
        sql += " where is_active"
    sql += " order by position, name"
    async with acquire_as(user.user_id) as conn:
        rows = await conn.fetch(sql)
    return [Product(**dict(r)) for r in rows]


@router.post("/products", response_model=Product, status_code=201)
async def create_product(
    payload: ProductIn,
    user: CurrentUser = Depends(get_current_user),
) -> Product:
    async with acquire_as(user.user_id) as conn:
        row = await conn.fetchrow(
            """
            insert into public.products
              (org_id, key, name, description, kind, list_price_cents,
               default_service_days, position)
            values ($1,$2,$3,$4,$5::public.product_kind,$6,$7,$8)
            returning *
            """,
            user.org_id,
            payload.key,
            payload.name,
            payload.description,
            payload.kind,
            payload.list_price_cents,
            payload.default_service_days,
            payload.position,
        )
    return Product(**dict(row))


@router.patch("/products/{product_id}", response_model=Product)
async def update_product(
    product_id: UUID,
    payload: ProductPatch,
    user: CurrentUser = Depends(get_current_user),
) -> Product:
    try:
        zuweisungen, args = build_update(payload)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    args.append(product_id)
    async with acquire_as(user.user_id) as conn:
        row = await conn.fetchrow(
            f"update public.products set {zuweisungen} where id = ${len(args)} returning *", *args
        )
    if row is None:
        raise HTTPException(404, "Produkt nicht gefunden")
    return Product(**dict(row))


# ── Angebote ────────────────────────────────────────────────────────────

@router.get("/quotes", response_model=list[Quote])
async def list_quotes(
    user: CurrentUser = Depends(get_current_user),
    deal_id: UUID | None = Query(None),
    status: str | None = Query(None),
    limit: int = Query(50, le=200),
) -> list[Quote]:
    # Jedes Angebot wird einzeln geladen, weil die Summen aus den
    # Positionen entstehen. Bei fünfzig ist das unauffällig, bei
    # tausend wäre es das nicht — daher die Obergrenze.
    sql = "select q.id from public.quotes q where q.deleted_at is null"
    args: list[object] = []
    if deal_id:
        args.append(deal_id)
        sql += f" and q.deal_id = ${len(args)}"
    if status:
        args.append(status)
        sql += f" and q.status = ${len(args)}::public.quote_status"
    args.append(limit)
    sql += f" order by q.number_seq desc limit ${len(args)}"

    async with acquire_as(user.user_id) as conn:
        ids = await conn.fetch(sql, *args)
        return [await _angebot_laden(conn, z["id"]) for z in ids]


@router.get("/quotes/{quote_id}", response_model=Quote)
async def get_quote(quote_id: UUID, user: CurrentUser = Depends(get_current_user)) -> Quote:
    async with acquire_as(user.user_id) as conn:
        return await _angebot_laden(conn, quote_id)


@router.post("/quotes", response_model=Quote, status_code=201)
async def create_quote(payload: QuoteIn, user: CurrentUser = Depends(get_current_user)) -> Quote:
    async with acquire_as(user.user_id) as conn:
        deal = await conn.fetchrow(
            "select id from public.deals where id = $1 and deleted_at is null", payload.deal_id
        )
        if deal is None:
            raise HTTPException(404, "Deal nicht gefunden")

        # Die Nummer wird unter einer Sperre auf die Organisation vergeben.
        # Ohne sie bekämen zwei gleichzeitige Anlagen dieselbe Nummer, und
        # der eindeutige Index ließe die zweite scheitern — mit einem
        # Fehler, den niemand deuten kann.
        await conn.execute("select id from public.orgs where id = $1 for update", user.org_id)
        seq = await conn.fetchval(
            "select coalesce(max(number_seq), 0) + 1 from public.quotes where org_id = $1",
            user.org_id,
        )

        kopf = await conn.fetchrow(
            """
            insert into public.quotes
              (org_id, deal_id, number_seq, title, intro_text, terms_text,
               discount_cents, tax_rate, valid_until, created_by)
            values ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)
            returning id
            """,
            user.org_id,
            payload.deal_id,
            seq,
            payload.title,
            payload.intro_text,
            payload.terms_text,
            payload.discount_cents,
            payload.tax_rate,
            payload.valid_until,
            user.user_id,
        )
        await _zeilen_schreiben(conn, user, kopf["id"], payload.items)

        await audit.log(
            conn,
            org_id=user.org_id,
            actor_id=user.user_id,
            action="create",
            entity="quotes",
            entity_id=kopf["id"],
            diff={"deal_id": str(payload.deal_id), "positionen": len(payload.items)},
        )
        return await _angebot_laden(conn, kopf["id"])


async def _zeilen_schreiben(
    conn, user: CurrentUser, quote_id: UUID, items: list[QuoteItemIn]
) -> None:
    for position, item in enumerate(items):
        await conn.execute(
            """
            insert into public.quote_items
              (org_id, quote_id, product_id, position, title, description,
               quantity, unit_price_cents, discount_percent)
            values ($1,$2,$3,$4,$5,$6,$7,$8,$9)
            """,
            user.org_id,
            quote_id,
            item.product_id,
            item.position or position,
            item.title,
            item.description,
            item.quantity,
            item.unit_price_cents,
            item.discount_percent,
        )


@router.put("/quotes/{quote_id}/positionen", response_model=Quote)
async def zeilen_ersetzen(
    quote_id: UUID,
    items: list[QuoteItemIn],
    user: CurrentUser = Depends(get_current_user),
) -> Quote:
    """Ersetzt alle Positionen auf einmal.

    Einzelne Positionen zu ändern wäre feiner, aber die Oberfläche
    bearbeitet ohnehin die ganze Liste — und ein Austausch in einer
    Transaktion kann nicht auf halbem Weg stehenbleiben.
    """
    async with acquire_as(user.user_id) as conn:
        offen = await conn.fetchval(
            "select status from public.quotes where id = $1 and deleted_at is null", quote_id
        )
        if offen is None:
            raise HTTPException(404, "Angebot nicht gefunden")
        if offen != "draft":
            raise HTTPException(
                409,
                "Dieses Angebot ist schon heraus. Was beim Kunden liegt, wird nicht "
                "nachträglich geändert — legen Sie ein neues an.",
            )
        await conn.execute("delete from public.quote_items where quote_id = $1", quote_id)
        await _zeilen_schreiben(conn, user, quote_id, items)
        return await _angebot_laden(conn, quote_id)


@router.patch("/quotes/{quote_id}", response_model=Quote)
async def update_quote(
    quote_id: UUID,
    payload: QuotePatch,
    user: CurrentUser = Depends(get_current_user),
) -> Quote:
    try:
        zuweisungen, args = build_update(payload)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    args.append(quote_id)
    async with acquire_as(user.user_id) as conn:
        geaendert = await conn.fetchval(
            f"update public.quotes set {zuweisungen} "
            f"where id = ${len(args)} and deleted_at is null returning id",
            *args,
        )
        if geaendert is None:
            raise HTTPException(404, "Angebot nicht gefunden")
        return await _angebot_laden(conn, quote_id)


@router.post("/quotes/{quote_id}/status", response_model=Quote)
async def status_setzen(
    quote_id: UUID,
    payload: QuoteStatusIn,
    user: CurrentUser = Depends(get_current_user),
) -> Quote:
    """Verschickt, angenommen, abgelehnt.

    Jeder Schritt hinterlässt eine Aktivität am Geschäft. „Seit wann liegt
    das Angebot beim Kunden" ist die Frage, die im Vertrieb am häufigsten
    gestellt wird; sie muss aus der Zeitleiste zu beantworten sein.
    """
    async with acquire_as(user.user_id) as conn:
        angebot = await conn.fetchrow(
            "select status, deal_id, number_seq, created_at from public.quotes "
            "where id = $1 and deleted_at is null",
            quote_id,
        )
        if angebot is None:
            raise HTTPException(404, "Angebot nicht gefunden")

        entschieden = payload.status in ("accepted", "rejected")
        await conn.execute(
            """
            update public.quotes
               set status = $1::public.quote_status,
                   sent_at = case when $1 = 'sent' then now() else sent_at end,
                   decided_at = case when $2 then now() else null end,
                   decision_note = coalesce($3, decision_note)
             where id = $4
            """,
            payload.status,
            entschieden,
            payload.decision_note,
            quote_id,
        )

        texte = {
            "sent": "Angebot verschickt",
            "accepted": "Angebot angenommen",
            "rejected": "Angebot abgelehnt",
            "expired": "Bindefrist abgelaufen",
            "draft": "Angebot zurück in Arbeit",
        }
        await conn.execute(
            """
            insert into public.activities (org_id, kind, subject, body, deal_id, payload, created_by)
            values ($1, 'quote', $2, $3, $4, $5::jsonb, $6)
            """,
            user.org_id,
            f"{texte[payload.status]}: {nummer(angebot['number_seq'], angebot['created_at'])}",
            payload.decision_note,
            angebot["deal_id"],
            orjson.dumps({"angebot": str(quote_id), "status": payload.status}).decode(),
            user.user_id,
        )
        await audit.log(
            conn,
            org_id=user.org_id,
            actor_id=user.user_id,
            action="update",
            entity="quotes",
            entity_id=quote_id,
            diff={"status": [angebot["status"], payload.status]},
        )
        return await _angebot_laden(conn, quote_id)


@router.delete("/quotes/{quote_id}", status_code=204)
async def delete_quote(quote_id: UUID, user: CurrentUser = Depends(get_current_user)) -> None:
    async with acquire_as(user.user_id) as conn:
        weg = await conn.fetchval(
            "update public.quotes set deleted_at = now() "
            "where id = $1 and deleted_at is null returning id",
            quote_id,
        )
        if weg is None:
            raise HTTPException(404, "Angebot nicht gefunden")


# Aufräumen der Bindefristen: Ein Angebot, dessen Frist verstrichen ist,
# steht sonst ewig auf „verschickt" und verfälscht jede Prognose.
@router.post("/quotes/fristen-pruefen", response_model=dict)
async def fristen_pruefen(user: CurrentUser = Depends(get_current_user)) -> dict:
    async with acquire_as(user.user_id) as conn:
        zeilen = await conn.fetch(
            """
            update public.quotes
               set status = 'expired'
             where status = 'sent'
               and valid_until is not null
               and valid_until < current_date
               and deleted_at is null
            returning id, deal_id, number_seq, created_at
            """
        )
        for z in zeilen:
            await conn.execute(
                """
                insert into public.activities (org_id, kind, subject, deal_id, payload, created_by)
                values ($1, 'quote', $2, $3, $4::jsonb, $5)
                """,
                user.org_id,
                f"Bindefrist abgelaufen: {nummer(z['number_seq'], z['created_at'])}",
                z["deal_id"],
                orjson.dumps({"angebot": str(z["id"]), "status": "expired"}).decode(),
                user.user_id,
            )
    return {"abgelaufen": len(zeilen), "geprueft_am": datetime.now(UTC).isoformat()}
