"""Tickets: Anliegen aufnehmen, zuweisen, beantworten, schließen.

Der zweite Strang neben dem Verkauf. Was hier anders ist als beim Deal,
steckt in drei Dingen:

- **Die Uhr.** Jedes Ticket hat eine Frist, die aus der Dringlichkeit
  entsteht. Sie pausiert, solange wir auf den Kunden warten — die Zeit
  des Kunden ist nicht unsere Frist.
- **Die erste Antwort.** Sie wird einmal festgehalten, beim ersten
  Verlaufseintrag, der nach draußen ging. Daraus entsteht die einzige
  Kennzahl, die Kunden wirklich merken.
- **Niemand zuständig ist ein Zustand.** `owner_id is null` ist die
  Frage, die eine Warteschlange stellt, und deshalb eine eigene Ansicht.
"""

from datetime import datetime, timedelta
from typing import Any, Literal
from uuid import UUID

import orjson
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app import audit, segmente, versand
from app.auth import CurrentUser, get_current_user
from app.db import acquire_as
from app.patching import build_update

router = APIRouter(prefix="/api/tickets", tags=["tickets"])

Prioritaet = Literal["niedrig", "mittel", "hoch", "dringend"]
# „api" und „bot" kommen über den signierten Eingang herein (0016).
Quelle = Literal["manuell", "email", "telefon", "insilo", "formular", "api", "bot"]
Stufenart = Literal["neu", "offen", "wartet_auf_kontakt", "abgeschlossen"]

# Fällt der Wert in den Einstellungen aus, gilt das hier. Vier Stunden für
# „dringend" ist die Zusage, die ein Mittelständler gerade noch halten
# kann, ohne eine Nachtschicht dafür zu brauchen.
SLA_VORGABE: dict[str, int] = {"dringend": 4, "hoch": 8, "mittel": 24, "niedrig": 72}

TICKET_SQL = """
select t.*,
       s.name as stufe_name, s.art as stufe_art,
       f.name as firma_name,
       coalesce(k.first_name || ' ', '') || coalesce(k.last_name, '') as kontakt_name,
       k.email as kontakt_email,
       coalesce(u.display_name, u.olares_username) as besitzer_name,
       (select max(a.occurred_at) from public.activities a where a.ticket_id = t.id)
         as letzte_aktivitaet
from public.tickets t
join public.ticket_stages s on s.id = t.stage_id
left join public.companies f on f.id = t.company_id
left join public.contacts k on k.id = t.contact_id
left join public.users u on u.id = t.owner_id
where t.deleted_at is null
"""


# ── Formen ──────────────────────────────────────────────────────────────

class Stufe(BaseModel):
    id: UUID
    name: str
    art: Stufenart
    position: int


class Ticketpipeline(BaseModel):
    id: UUID
    name: str
    is_default: bool
    stufen: list[Stufe] = []


class Kategorie(BaseModel):
    id: UUID
    name: str
    position: int
    is_active: bool


class TicketIn(BaseModel):
    betreff: str = Field(min_length=1, max_length=200)
    beschreibung: str | None = None
    pipeline_id: UUID | None = None
    stage_id: UUID | None = None
    prioritaet: Prioritaet = "mittel"
    kategorie: str | None = None
    quelle: Quelle = "manuell"
    owner_id: UUID | None = None
    contact_id: UUID | None = None
    company_id: UUID | None = None
    deal_id: UUID | None = None
    # Wer eine eigene Frist setzt, überschreibt die aus der Dringlichkeit.
    faellig_am: datetime | None = None


class TicketPatch(BaseModel):
    betreff: str | None = Field(default=None, min_length=1, max_length=200)
    beschreibung: str | None = None
    prioritaet: Prioritaet | None = None
    kategorie: str | None = None
    owner_id: UUID | None = None
    contact_id: UUID | None = None
    company_id: UUID | None = None
    deal_id: UUID | None = None
    faellig_am: datetime | None = None
    custom: dict[str, Any] | None = None


class Ticket(BaseModel):
    id: UUID
    nummer: int
    kennung: str
    betreff: str
    beschreibung: str | None = None
    pipeline_id: UUID
    stage_id: UUID
    stufe_name: str
    stufe_art: Stufenart
    prioritaet: Prioritaet
    kategorie: str | None = None
    quelle: Quelle
    # Wer geschrieben hat. Bleibt stehen, auch wenn die Adresse keinen
    # Kontakt trifft — sonst gibt es keinen Rückweg.
    absender_email: str | None = None
    absender_name: str | None = None
    owner_id: UUID | None = None
    besitzer_name: str | None = None
    contact_id: UUID | None = None
    kontakt_name: str | None = None
    kontakt_email: str | None = None
    company_id: UUID | None = None
    firma_name: str | None = None
    deal_id: UUID | None = None
    erste_antwort_am: datetime | None = None
    geschlossen_am: datetime | None = None
    faellig_am: datetime | None = None
    letzte_aktivitaet: datetime | None = None
    custom: dict[str, Any] = {}
    created_at: datetime
    updated_at: datetime
    # Gerechnet, nicht gespeichert: Die Oberfläche soll dieselbe Antwort
    # bekommen wie die Auswertung.
    offen: bool = True
    ueberfaellig: bool = False


class Spalte(BaseModel):
    stufe: Stufe
    tickets: list[Ticket]
    anzahl: int


class Brett(BaseModel):
    pipeline: Ticketpipeline
    spalten: list[Spalte]


class Verschieben(BaseModel):
    stage_id: UUID


def kennung_aus(nummer: int, angelegt: datetime) -> str:
    """T-2026-0042 — lesbar, sortierbar, in einer Mail zitierbar."""
    return f"T-{angelegt.year}-{nummer:04d}"


def _aus_zeile(row: dict[str, Any]) -> Ticket:
    custom = row.get("custom") or {}
    if isinstance(custom, str):
        custom = orjson.loads(custom)
    offen = row["stufe_art"] != "abgeschlossen"
    jetzt = datetime.now().astimezone()
    faellig = row.get("faellig_am")
    return Ticket(
        **{k: v for k, v in row.items() if k in Ticket.model_fields and k not in ("custom", "kennung", "offen", "ueberfaellig")},
        kennung=kennung_aus(row["nummer"], row["created_at"]),
        custom=custom,
        offen=offen,
        # Überfällig ist nur, was offen ist und nicht auf den Kunden
        # wartet. Sonst zeigte die Liste rot, was gar nicht an uns liegt.
        ueberfaellig=bool(
            offen and row["stufe_art"] != "wartet_auf_kontakt" and faellig and faellig < jetzt
        ),
    )


# ── Fristen ─────────────────────────────────────────────────────────────

async def _sla_stunden(conn, org_id: UUID) -> dict[str, int]:
    roh = await conn.fetchval(
        "select sla_stunden from public.org_settings where org_id = $1", org_id
    )
    werte = orjson.loads(roh) if isinstance(roh, str) else (roh or {})
    return {**SLA_VORGABE, **{k: int(v) for k, v in werte.items() if str(v).isdigit()}}


async def _frist(conn, org_id: UUID, prioritaet: str, ab: datetime | None = None) -> datetime:
    stunden = (await _sla_stunden(conn, org_id)).get(prioritaet, SLA_VORGABE["mittel"])
    return (ab or datetime.now().astimezone()) + timedelta(hours=stunden)


# ── Pipelines und Kategorien ────────────────────────────────────────────

async def _standard_pipeline(conn, org_id: UUID) -> UUID:
    pid = await conn.fetchval(
        "select id from public.ticket_pipelines where org_id = $1 and deleted_at is null "
        "order by is_default desc, position limit 1",
        org_id,
    )
    if pid is None:
        raise HTTPException(500, "Keine Ticket-Pipeline vorhanden — die Einrichtung ist unvollständig.")
    return pid


async def _pipeline_laden(conn, pid: UUID) -> Ticketpipeline:
    kopf = await conn.fetchrow(
        "select id, name, is_default from public.ticket_pipelines "
        "where id = $1 and deleted_at is null",
        pid,
    )
    if kopf is None:
        raise HTTPException(404, "Ticket-Pipeline nicht gefunden")
    stufen = await conn.fetch(
        "select id, name, art, position from public.ticket_stages "
        "where pipeline_id = $1 order by position",
        pid,
    )
    return Ticketpipeline(**dict(kopf), stufen=[Stufe(**dict(s)) for s in stufen])


@router.get("/pipelines", response_model=list[Ticketpipeline])
async def pipelines(user: CurrentUser = Depends(get_current_user)) -> list[Ticketpipeline]:
    async with acquire_as(user.user_id) as conn:
        ids = await conn.fetch(
            "select id from public.ticket_pipelines where org_id = $1 and deleted_at is null "
            "order by is_default desc, position",
            user.org_id,
        )
        return [await _pipeline_laden(conn, z["id"]) for z in ids]


@router.get("/kategorien", response_model=list[Kategorie])
async def kategorien(
    nur_aktive: bool = Query(True),
    user: CurrentUser = Depends(get_current_user),
) -> list[Kategorie]:
    sql = "select id, name, position, is_active from public.ticket_kategorien where org_id = $1"
    if nur_aktive:
        sql += " and is_active"
    async with acquire_as(user.user_id) as conn:
        return [Kategorie(**dict(z)) for z in await conn.fetch(sql + " order by position, name", user.org_id)]


class KategorieIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)


@router.post("/kategorien", response_model=Kategorie, status_code=201)
async def kategorie_anlegen(
    payload: KategorieIn, user: CurrentUser = Depends(get_current_user)
) -> Kategorie:
    async with acquire_as(user.user_id) as conn:
        z = await conn.fetchrow(
            "insert into public.ticket_kategorien (org_id, name, position) "
            "values ($1, $2, (select coalesce(max(position), -1) + 1 from public.ticket_kategorien where org_id = $1)) "
            "returning id, name, position, is_active",
            user.org_id,
            payload.name.strip(),
        )
    return Kategorie(**dict(z))


@router.delete("/kategorien/{kategorie_id}", status_code=204)
async def kategorie_abschalten(
    kategorie_id: UUID, user: CurrentUser = Depends(get_current_user)
) -> None:
    """Abschalten statt löschen — die Tickets behalten ihre Zuordnung."""
    async with acquire_as(user.user_id) as conn:
        weg = await conn.fetchval(
            "update public.ticket_kategorien set is_active = false where id = $1 returning id",
            kategorie_id,
        )
        if weg is None:
            raise HTTPException(404, "Kategorie nicht gefunden")


# ── Liste, Zählung, Brett ───────────────────────────────────────────────

def _bedingungen(
    sql: str,
    args: list[Any],
    q: str | None,
    offen: bool | None,
    mein: bool,
    ohne_besitzer: bool,
    user_id: UUID,
    contact_id: UUID | None,
    company_id: UUID | None,
    filter: str | None,
) -> str:
    if q:
        args.append(f"%{q}%")
        sql += (
            f" and (t.betreff ilike ${len(args)} or t.beschreibung ilike ${len(args)}"
            f" or f.name ilike ${len(args)})"
        )
    if offen is True:
        sql += " and s.art <> 'abgeschlossen'"
    elif offen is False:
        sql += " and s.art = 'abgeschlossen'"
    if mein:
        args.append(user_id)
        sql += f" and t.owner_id = ${len(args)}"
    if ohne_besitzer:
        sql += " and t.owner_id is null"
    if contact_id:
        args.append(contact_id)
        sql += f" and t.contact_id = ${len(args)}"
    if company_id:
        args.append(company_id)
        sql += f" and t.company_id = ${len(args)}"
    if filter:
        try:
            sql += segmente.filter_zu_sql("tickets", segmente.bedingungen_aus(orjson.loads(filter)), args)
        except (orjson.JSONDecodeError, segmente.Ungueltig) as exc:
            raise HTTPException(400, f"Filter nicht verwendbar: {exc}") from exc
    return sql


@router.get("", response_model=list[Ticket])
async def liste(
    user: CurrentUser = Depends(get_current_user),
    q: str | None = Query(None),
    offen: bool | None = Query(None),
    mein: bool = Query(False),
    ohne_besitzer: bool = Query(False),
    contact_id: UUID | None = Query(None),
    company_id: UUID | None = Query(None),
    filter: str | None = Query(None),
    sort: str | None = Query(None),
    richtung: str | None = Query(None),
    limit: int = Query(50, le=200),
    offset: int = Query(0, ge=0),
) -> list[Ticket]:
    args: list[Any] = []
    sql = _bedingungen(
        TICKET_SQL, args, q, offen, mein, ohne_besitzer, user.user_id, contact_id, company_id, filter
    )
    try:
        sql += segmente.sortierung_zu_sql("tickets", sort, richtung)
    except segmente.Ungueltig as exc:
        raise HTTPException(400, str(exc)) from exc
    args.extend([limit, offset])
    sql += f" limit ${len(args) - 1} offset ${len(args)}"

    async with acquire_as(user.user_id) as conn:
        return [_aus_zeile(dict(z)) for z in await conn.fetch(sql, *args)]


@router.get("/anzahl")
async def anzahl(
    user: CurrentUser = Depends(get_current_user),
    q: str | None = Query(None),
    offen: bool | None = Query(None),
    mein: bool = Query(False),
    ohne_besitzer: bool = Query(False),
    contact_id: UUID | None = Query(None),
    company_id: UUID | None = Query(None),
    filter: str | None = Query(None),
) -> dict[str, int]:
    args: list[Any] = []
    sql = _bedingungen(
        "select count(*) from public.tickets t "
        "join public.ticket_stages s on s.id = t.stage_id "
        "left join public.companies f on f.id = t.company_id "
        "where t.deleted_at is null",
        args, q, offen, mein, ohne_besitzer, user.user_id, contact_id, company_id, filter,
    )
    async with acquire_as(user.user_id) as conn:
        return {"anzahl": await conn.fetchval(sql, *args) or 0}


@router.get("/brett", response_model=Brett)
async def brett(
    user: CurrentUser = Depends(get_current_user),
    pipeline_id: UUID | None = Query(None),
    mein: bool = Query(False),
    ohne_besitzer: bool = Query(False),
    q: str | None = Query(None),
) -> Brett:
    """Eine Spalte je Stufe. Die Zahl darüber ist die volle Zahl.

    Gezeigt werden höchstens hundert Karten je Spalte — darüber hinaus
    scrollt niemand mehr, und die Zahl im Kopf sagt trotzdem die Wahrheit.
    """
    async with acquire_as(user.user_id) as conn:
        pid = pipeline_id or await _standard_pipeline(conn, user.org_id)
        pipeline = await _pipeline_laden(conn, pid)

        args: list[Any] = []
        sql = _bedingungen(
            TICKET_SQL, args, q, None, mein, ohne_besitzer, user.user_id, None, None, None
        )
        args.append(pid)
        sql += f" and t.pipeline_id = ${len(args)} order by t.updated_at desc"
        zeilen = await conn.fetch(sql, *args)

    nach_stufe: dict[UUID, list[Ticket]] = {}
    for z in zeilen:
        t = _aus_zeile(dict(z))
        nach_stufe.setdefault(t.stage_id, []).append(t)

    return Brett(
        pipeline=pipeline,
        spalten=[
            Spalte(
                stufe=s,
                tickets=nach_stufe.get(s.id, [])[:100],
                anzahl=len(nach_stufe.get(s.id, [])),
            )
            for s in pipeline.stufen
        ],
    )


@router.get("/{ticket_id}", response_model=Ticket)
async def einzeln(ticket_id: UUID, user: CurrentUser = Depends(get_current_user)) -> Ticket:
    async with acquire_as(user.user_id) as conn:
        z = await conn.fetchrow(TICKET_SQL + " and t.id = $1", ticket_id)
    if z is None:
        raise HTTPException(404, "Ticket nicht gefunden")
    return _aus_zeile(dict(z))


# ── Anlegen, ändern, verschieben ────────────────────────────────────────

async def _erste_stufe(conn, pipeline_id: UUID) -> UUID:
    sid = await conn.fetchval(
        "select id from public.ticket_stages where pipeline_id = $1 order by position limit 1",
        pipeline_id,
    )
    if sid is None:
        raise HTTPException(400, "Diese Pipeline hat keine Stufen.")
    return sid


@router.post("", response_model=Ticket, status_code=201)
async def anlegen(payload: TicketIn, user: CurrentUser = Depends(get_current_user)) -> Ticket:
    async with acquire_as(user.user_id) as conn:
        pid = payload.pipeline_id or await _standard_pipeline(conn, user.org_id)
        sid = payload.stage_id or await _erste_stufe(conn, pid)
        faellig = payload.faellig_am or await _frist(conn, user.org_id, payload.prioritaet)

        # Die Nummer entsteht in derselben Transaktion wie die Zeile; der
        # eindeutige Index fängt ab, was ein Wettlauf übrig lässt.
        async with conn.transaction():
            nummer = await conn.fetchval(
                "select coalesce(max(nummer), 0) + 1 from public.tickets where org_id = $1",
                user.org_id,
            )
            neu = await conn.fetchval(
                """
                insert into public.tickets
                  (org_id, nummer, betreff, beschreibung, pipeline_id, stage_id, prioritaet,
                   kategorie, quelle, owner_id, contact_id, company_id, deal_id, faellig_am,
                   created_by)
                values ($1,$2,$3,$4,$5,$6,$7::public.ticket_prioritaet,$8,
                        $9::public.ticket_quelle,$10,$11,$12,$13,$14,$15)
                returning id
                """,
                user.org_id, nummer, payload.betreff.strip(), payload.beschreibung, pid, sid,
                payload.prioritaet, payload.kategorie, payload.quelle, payload.owner_id,
                payload.contact_id, payload.company_id, payload.deal_id, faellig, user.user_id,
            )

        await audit.log_fuer(
            conn, user, action="create", entity="tickets", entity_id=neu,
            diff=payload.model_dump(mode="json", exclude_none=True),
        )
        z = await conn.fetchrow(TICKET_SQL + " and t.id = $1", neu)
    return _aus_zeile(dict(z))


@router.patch("/{ticket_id}", response_model=Ticket)
async def aendern(
    ticket_id: UUID,
    payload: TicketPatch,
    user: CurrentUser = Depends(get_current_user),
) -> Ticket:
    try:
        zuweisungen, args = build_update(payload)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc

    async with acquire_as(user.user_id) as conn:
        # Ändert sich die Dringlichkeit, wandert die Frist mit — außer
        # jemand hat sie von Hand gesetzt. Eine Frist, die zur alten
        # Dringlichkeit gehört, wäre die falsche Zusage.
        if payload.prioritaet and payload.faellig_am is None:
            alt = await conn.fetchrow(
                "select created_at, geschlossen_am from public.tickets where id = $1", ticket_id
            )
            if alt and alt["geschlossen_am"] is None:
                args.append(await _frist(conn, user.org_id, payload.prioritaet, alt["created_at"]))
                zuweisungen += f", faellig_am = ${len(args)}"

        args.append(ticket_id)
        neu = await conn.fetchval(
            f"update public.tickets set {zuweisungen}, updated_at = now() "
            f"where id = ${len(args)} and deleted_at is null returning id",
            *args,
        )
        if neu is None:
            raise HTTPException(404, "Ticket nicht gefunden")
        await audit.log_fuer(
            conn, user, action="update", entity="tickets", entity_id=ticket_id,
            diff=payload.model_dump(mode="json", exclude_unset=True),
        )
        z = await conn.fetchrow(TICKET_SQL + " and t.id = $1", ticket_id)
    return _aus_zeile(dict(z))


@router.post("/{ticket_id}/stufe", response_model=Ticket)
async def verschieben(
    ticket_id: UUID,
    payload: Verschieben,
    user: CurrentUser = Depends(get_current_user),
) -> Ticket:
    """Ein Ticket in eine andere Stufe — mit Eintrag im Verlauf.

    Der Wechsel setzt auch die Uhr: In eine abgeschlossene Stufe heißt
    geschlossen, zurück heraus heißt wieder offen. Wer das getrennt
    pflegen müsste, hätte irgendwann geschlossene Tickets in der offenen
    Spalte.
    """
    async with acquire_as(user.user_id) as conn:
        vorher = await conn.fetchrow(
            "select t.stage_id, t.pipeline_id, s.name as stufe_name, s.art as stufe_art "
            "from public.tickets t join public.ticket_stages s on s.id = t.stage_id "
            "where t.id = $1 and t.deleted_at is null",
            ticket_id,
        )
        if vorher is None:
            raise HTTPException(404, "Ticket nicht gefunden")

        ziel = await conn.fetchrow(
            "select id, name, art, pipeline_id from public.ticket_stages where id = $1",
            payload.stage_id,
        )
        if ziel is None:
            raise HTTPException(404, "Stufe nicht gefunden")
        if ziel["pipeline_id"] != vorher["pipeline_id"]:
            raise HTTPException(400, "Die Stufe gehört zu einer anderen Pipeline.")

        schliesst = ziel["art"] == "abgeschlossen"
        await conn.execute(
            """
            update public.tickets
               set stage_id = $1,
                   geschlossen_am = case when $2 then coalesce(geschlossen_am, now()) else null end,
                   updated_at = now()
             where id = $3
            """,
            payload.stage_id, schliesst, ticket_id,
        )

        if vorher["stage_id"] != payload.stage_id:
            await conn.execute(
                """
                insert into public.activities
                  (org_id, kind, subject, ticket_id, payload, created_by)
                values ($1, 'stage_change', $2, $3, $4::jsonb, $5)
                """,
                user.org_id,
                f"{vorher['stufe_name']} → {ziel['name']}",
                ticket_id,
                orjson.dumps({"von": vorher["stufe_name"], "nach": ziel["name"]}).decode(),
                user.user_id,
            )
            await audit.log_fuer(
                conn, user, action="update", entity="tickets", entity_id=ticket_id,
                diff={"stufe": ziel["name"]},
            )
        z = await conn.fetchrow(TICKET_SQL + " and t.id = $1", ticket_id)
    return _aus_zeile(dict(z))


class AntwortIn(BaseModel):
    text: str = Field(min_length=1, max_length=20000)
    betreff: str | None = Field(default=None, max_length=200)


@router.post("/{ticket_id}/antworten", response_model=Ticket)
async def antworten(
    ticket_id: UUID,
    payload: AntwortIn,
    user: CurrentUser = Depends(get_current_user),
) -> Ticket:
    """Eine Antwort an den, der geschrieben hat — per Mail, am Faden.

    Der Empfänger ist der Kontakt, sonst die Absenderadresse aus dem
    Eingang. Kam das Ticket per Mail, hängt die Antwort mit `In-Reply-To`
    an der Anfrage; die Kennung im Betreff hält den Faden auch dann, wenn
    ein Mailprogramm die Kopfzeile verliert. Danach: erste Antwort
    festgehalten, Ticket in „wartet auf Kontakt“, Eintrag im Verlauf.
    """
    fehler = None
    async with acquire_as(user.user_id) as conn:
        t = await conn.fetchrow(TICKET_SQL + " and t.id = $1", ticket_id)
        if t is None:
            raise HTTPException(404, "Ticket nicht gefunden")
        an = (t["kontakt_email"] or t["absender_email"] or "").strip()
        if not an:
            raise HTTPException(409, "Dieses Ticket hat keine Adresse, an die eine Antwort gehen könnte.")

        # Die Message-ID der Anfrage — wenn sie über den Eingang kam.
        anfrage = await conn.fetchval(
            "select external_id from public.eingang where ticket_id = $1 and external_id like '<%>' "
            "order by created_at limit 1",
            ticket_id,
        )
        kennung = kennung_aus(t["nummer"], t["created_at"])
        betreff = (payload.betreff or "").strip() or f"AW: {t['betreff']}"
        if kennung not in betreff:
            betreff = f"{betreff} [{kennung}]"

        try:
            mail_id = await versand.einreihen(
                conn, user.org_id, art="transaktional", an=an, betreff=betreff, text=payload.text,
                contact_id=t["contact_id"], ticket_id=ticket_id, in_reply_to=anfrage,
                created_by=user.user_id, payload={"zweck": "ticket-antwort"},
            )
            zeile = await versand.versenden(conn, user.org_id, mail_id)
        except versand.Unmoeglich as exc:
            raise HTTPException(409, str(exc)) from exc
        if zeile["status"] != "gesendet":
            # Bleibt im Buch, wird wiederholt. Verlauf und Uhr warten auf
            # den Versand — eine Antwort, die nicht ankam, ist keine. Der
            # Fehler geht erst nach der Transaktion hinaus, sonst nähme er
            # die Zeile mit.
            fehler = zeile["fehler"]
    if fehler:
        raise HTTPException(502, f"Die Antwort ging noch nicht hinaus, sie wird wiederholt: {fehler}")
    async with acquire_as(user.user_id) as conn:
        await conn.execute(
            """
            insert into public.activities
              (org_id, kind, subject, body, ticket_id, contact_id, company_id, payload, created_by)
            values ($1, 'email', $2, $3, $4, $5, $6, $7::jsonb, $8)
            """,
            user.org_id, f"An {an}: {betreff}", payload.text, ticket_id, t["contact_id"], t["company_id"],
            orjson.dumps({"richtung": "ausgehend", "an": an, "message_id": zeile["message_id"],
                          "mail_id": str(mail_id)}).decode(),
            user.user_id,
        )
        # Die erste Antwort zählt einmal; danach wartet das Ticket auf den
        # Kunden — falls die Pipeline eine solche Stufe kennt.
        wartestufe = await conn.fetchval(
            "select id from public.ticket_stages where pipeline_id = $1 and art = 'wartet_auf_kontakt' "
            "order by position limit 1",
            t["pipeline_id"],
        )
        await conn.execute(
            """
            update public.tickets
               set erste_antwort_am = coalesce(erste_antwort_am, now()),
                   stage_id = case when $2::uuid is not null and geschlossen_am is null then $2 else stage_id end,
                   updated_at = now()
             where id = $1
            """,
            ticket_id, wartestufe,
        )
        await audit.log_fuer(
            conn, user, action="update", entity="tickets", entity_id=ticket_id,
            diff={"antwort": "per Mail", "an": an},
        )
        z = await conn.fetchrow(TICKET_SQL + " and t.id = $1", ticket_id)
    return _aus_zeile(dict(z))


@router.delete("/{ticket_id}", status_code=204)
async def loeschen(ticket_id: UUID, user: CurrentUser = Depends(get_current_user)) -> None:
    async with acquire_as(user.user_id) as conn:
        weg = await conn.fetchval(
            "update public.tickets set deleted_at = now() "
            "where id = $1 and deleted_at is null returning id",
            ticket_id,
        )
        if weg is None:
            raise HTTPException(404, "Ticket nicht gefunden")
        await audit.log_fuer(conn, user, action="delete", entity="tickets", entity_id=ticket_id)


# ── Stapel ──────────────────────────────────────────────────────────────

class Stapel(BaseModel):
    ids: list[UUID]


class StapelAenderung(Stapel):
    prioritaet: Prioritaet | None = None
    owner_id: UUID | None = None
    kategorie: str | None = None
    stage_id: UUID | None = None


@router.post("/mehrere")
async def mehrere_aendern(
    payload: StapelAenderung, user: CurrentUser = Depends(get_current_user)
) -> dict[str, int]:
    if not payload.ids:
        raise HTTPException(400, "Keine Tickets gewählt")
    felder = payload.model_dump(exclude_unset=True, exclude={"ids"})
    if not felder:
        raise HTTPException(400, "Keine Änderung übergeben")

    zuweisungen: list[str] = []
    args: list[Any] = []
    for name, wert in felder.items():
        args.append(wert)
        guss = "::public.ticket_prioritaet" if name == "prioritaet" else ""
        zuweisungen.append(f"{name} = ${len(args)}{guss}")
    args.append(payload.ids)

    async with acquire_as(user.user_id) as conn:
        rows = await conn.fetch(
            f"update public.tickets set {', '.join(zuweisungen)}, updated_at = now() "
            f"where id = any(${len(args)}::uuid[]) and deleted_at is null returning id",
            *args,
        )
        # Landen sie in einer abgeschlossenen Stufe, stoppt auch die Uhr.
        if payload.stage_id:
            await conn.execute(
                """
                update public.tickets t
                   set geschlossen_am = case when s.art = 'abgeschlossen'
                                             then coalesce(t.geschlossen_am, now()) else null end
                  from public.ticket_stages s
                 where s.id = t.stage_id and t.id = any($1::uuid[])
                """,
                payload.ids,
            )
        for r in rows:
            await audit.log_fuer(
                conn, user, action="update", entity="tickets", entity_id=r["id"], diff=felder
            )
    return {"geaendert": len(rows)}


@router.post("/mehrere/loeschen")
async def mehrere_loeschen(
    payload: Stapel, user: CurrentUser = Depends(get_current_user)
) -> dict[str, int]:
    if not payload.ids:
        raise HTTPException(400, "Keine Tickets gewählt")
    async with acquire_as(user.user_id) as conn:
        rows = await conn.fetch(
            "update public.tickets set deleted_at = now() "
            "where id = any($1::uuid[]) and deleted_at is null returning id",
            payload.ids,
        )
        for r in rows:
            await audit.log_fuer(conn, user, action="delete", entity="tickets", entity_id=r["id"])
    return {"geloescht": len(rows)}
