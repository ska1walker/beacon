"""Besprechungen — Liste, Suche, Vorschlag bestätigen, zuordnen.

Die Logik steht in `app/besprechungen.py`; hier stehen nur die Wege dahin.
Ein Mitglied genügt, wie beim Eingang: Ein Gespräch einem Kunden
zuzuordnen ist Vertriebsarbeit, keine Verwaltung.
"""

from datetime import date, datetime, time, timedelta
from typing import Any, Literal
from uuid import UUID

import orjson
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app import audit, besprechungen
from app.auth import CurrentUser, get_current_user
from app.db import acquire_as

router = APIRouter(prefix="/api/besprechungen", tags=["besprechungen"])

SUCHE = "to_tsvector('german', coalesce(b.titel, '') || ' ' || coalesce(b.protokoll, ''))"


class Bezug(BaseModel):
    id: UUID
    name: str


class Vorschlag(BaseModel):
    quelle: str
    grund: str
    mehrdeutig: bool = False
    company: Bezug | None = None
    kontakte: list[Bezug] = []
    deal: Bezug | None = None
    kandidaten: list[dict[str, Any]] = []
    modell: str | None = None


class Besprechung(BaseModel):
    id: UUID
    titel: str | None = None
    recorded_at: datetime | None = None
    dauer_sek: int | None = None
    vorlage: str | None = None
    beteiligte: list[str] = []
    schlagworte: list[str] = []
    status: str
    company: Bezug | None = None
    kontakte: list[Bezug] = []
    deal: Bezug | None = None
    vorschlag: Vorschlag | None = None
    created_at: datetime


class BesprechungVoll(Besprechung):
    protokoll: str = ""
    zusammenfassung: dict[str, Any] = {}
    sprecher: list[str] = []
    insilo_link: str | None = None


class Seite(BaseModel):
    eintraege: list[Besprechung]
    gesamt: int


class Anzahl(BaseModel):
    offen: int
    zugeordnet: int
    alle: int


class Zuordnung(BaseModel):
    company_id: UUID | None = None
    contact_ids: list[UUID] = Field(default_factory=list, max_length=50)
    deal_id: UUID | None = None


def _json(wert: Any) -> Any:
    return orjson.loads(wert) if isinstance(wert, str) else wert


async def _namen(conn, tabelle: str, ids: set[str]) -> dict[str, str]:
    if not ids:
        return {}
    ausdruck = (
        "trim(coalesce(first_name, '') || ' ' || coalesce(last_name, ''))"
        if tabelle == "contacts" else "name"
    )
    zeilen = await conn.fetch(
        f"select id, {ausdruck} as name from public.{tabelle} where id = any($1::uuid[]) and deleted_at is null",
        list(ids),
    )
    return {str(z["id"]): z["name"] or "—" for z in zeilen}


async def _aufbereiten(conn, zeilen: list) -> list[dict[str, Any]]:
    """Setzt Namen an alle Kennungen — der Zuordnung und des Vorschlags.

    In einem Rutsch je Tabelle, nicht je Zeile: Eine Seite hat fünfzig
    Besprechungen, und fünfzig Abfragen für Namen wären die langsamste
    Stelle der Seite.
    """
    firmen: set[str] = set()
    kontakte: set[str] = set()
    deals: set[str] = set()
    for z in zeilen:
        v = _json(z["vorschlag"]) or {}
        firmen |= {i for i in [v.get("company_id")] if i}
        kontakte |= set(v.get("contact_ids") or [])
        deals |= {i for i in [v.get("deal_id")] if i}
    firmennamen = await _namen(conn, "companies", firmen)
    kontaktnamen = await _namen(conn, "contacts", kontakte)
    dealnamen = await _namen(conn, "deals", deals)

    ergebnis = []
    for z in zeilen:
        eintrag = dict(z)
        eintrag["kontakte"] = _json(z["kontakte"]) or []
        eintrag["company"] = {"id": z["company_id"], "name": z["company_name"]} if z["company_id"] else None
        eintrag["deal"] = {"id": z["deal_id"], "name": z["deal_name"]} if z["deal_id"] else None
        v = _json(z["vorschlag"])
        if v and z["status"] == "offen":
            eintrag["vorschlag"] = {
                "quelle": v.get("quelle") or "namen",
                "grund": v.get("grund") or "",
                "mehrdeutig": bool(v.get("mehrdeutig")),
                "modell": v.get("modell"),
                "kandidaten": v.get("kandidaten") or [],
                "company": {"id": v["company_id"], "name": firmennamen[v["company_id"]]}
                if v.get("company_id") in firmennamen else None,
                "kontakte": [{"id": k, "name": kontaktnamen[k]} for k in v.get("contact_ids") or [] if k in kontaktnamen],
                "deal": {"id": v["deal_id"], "name": dealnamen[v["deal_id"]]}
                if v.get("deal_id") in dealnamen else None,
            }
        else:
            eintrag["vorschlag"] = None
        ergebnis.append(eintrag)
    return ergebnis


GRUNDABFRAGE = """
select b.id, b.titel, b.recorded_at, b.dauer_sek, b.vorlage, b.beteiligte, b.schlagworte,
       b.status::text as status, b.company_id, f.name as company_name,
       b.deal_id, d.name as deal_name, b.vorschlag, b.created_at,
       coalesce((
         select json_agg(json_build_object(
           'id', c.id,
           'name', trim(coalesce(c.first_name, '') || ' ' || coalesce(c.last_name, ''))))
         from public.besprechung_kontakte k
         join public.contacts c on c.id = k.contact_id
         where k.besprechung_id = b.id
       ), '[]') as kontakte
from public.besprechungen b
left join public.companies f on f.id = b.company_id
left join public.deals d on d.id = b.deal_id
"""


@router.get("", response_model=Seite)
async def liste(
    user: CurrentUser = Depends(get_current_user),
    q: str = "",
    status: Literal["alle", "offen", "zugeordnet", "verworfen"] = "alle",
    von: date | None = None,
    bis: date | None = None,
    company_id: UUID | None = None,
    contact_id: UUID | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> Seite:
    bedingungen = ["b.deleted_at is null"]
    args: list[Any] = []

    def arg(wert: Any) -> str:
        args.append(wert)
        return f"${len(args)}"

    if status == "alle":
        bedingungen.append("b.status <> 'verworfen'")
    else:
        bedingungen.append(f"b.status = {arg(status)}::public.besprechung_status")
    if q.strip():
        # Volltext für ganze Wörter, dazu ein Teilwort im Titel — wer „Brink"
        # tippt, sucht Brinkmann und denkt nicht an Wortstämme.
        p_q = arg(q.strip())
        p_like = arg(f"%{q.strip()}%")
        bedingungen.append(f"({SUCHE} @@ websearch_to_tsquery('german', {p_q}) or b.titel ilike {p_like})")
    if von:
        bedingungen.append(f"b.recorded_at >= {arg(datetime.combine(von, time.min))}")
    if bis:
        bedingungen.append(f"b.recorded_at < {arg(datetime.combine(bis + timedelta(days=1), time.min))}")
    if company_id:
        bedingungen.append(f"b.company_id = {arg(company_id)}")
    if contact_id:
        bedingungen.append(
            f"exists (select 1 from public.besprechung_kontakte k where k.besprechung_id = b.id and k.contact_id = {arg(contact_id)})"
        )

    wo = " where " + " and ".join(bedingungen)
    async with acquire_as(user.user_id) as conn:
        gesamt = await conn.fetchval(f"select count(*) from public.besprechungen b {wo}", *args)
        zeilen = await conn.fetch(
            f"{GRUNDABFRAGE} {wo} order by b.recorded_at desc nulls last, b.created_at desc "
            f"limit {arg(limit)} offset {arg(offset)}",
            *args,
        )
        eintraege = await _aufbereiten(conn, zeilen)
    return Seite(eintraege=[Besprechung(**e) for e in eintraege], gesamt=gesamt)


@router.get("/anzahl", response_model=Anzahl)
async def anzahl(user: CurrentUser = Depends(get_current_user)) -> Anzahl:
    async with acquire_as(user.user_id) as conn:
        z = await conn.fetchrow(
            "select count(*) filter (where status = 'offen') as offen, "
            "count(*) filter (where status = 'zugeordnet') as zugeordnet, "
            "count(*) filter (where status <> 'verworfen') as alle "
            "from public.besprechungen where deleted_at is null"
        )
    return Anzahl(**dict(z))


@router.get("/{besprechung_id}", response_model=BesprechungVoll)
async def eine(besprechung_id: UUID, user: CurrentUser = Depends(get_current_user)) -> BesprechungVoll:
    async with acquire_as(user.user_id) as conn:
        zeile = await conn.fetchrow(
            f"{GRUNDABFRAGE} where b.id = $1 and b.deleted_at is null", besprechung_id
        )
        if zeile is None:
            raise HTTPException(404, "Besprechung nicht gefunden")
        mehr = await conn.fetchrow(
            "select b.protokoll, b.zusammenfassung, b.sprecher, b.external_id, s.oberflaeche_url "
            "from public.besprechungen b left join public.webhook_sources s on s.id = b.source_id "
            "where b.id = $1",
            besprechung_id,
        )
        [eintrag] = await _aufbereiten(conn, [zeile])

    link = None
    if mehr["oberflaeche_url"]:
        link = f"{mehr['oberflaeche_url'].rstrip('/')}/m/{mehr['external_id']}"
    return BesprechungVoll(
        **eintrag,
        protokoll=mehr["protokoll"] or "",
        zusammenfassung=_json(mehr["zusammenfassung"]) or {},
        sprecher=mehr["sprecher"] or [],
        insilo_link=link,
    )


@router.post("/{besprechung_id}/zuordnen", response_model=BesprechungVoll)
async def zuordnen(
    besprechung_id: UUID,
    payload: Zuordnung,
    user: CurrentUser = Depends(get_current_user),
) -> BesprechungVoll:
    async with acquire_as(user.user_id) as conn:
        try:
            aktivitaet = await besprechungen.zuordnen(
                conn, user.user_id, user.org_id, besprechung_id,
                payload.company_id, payload.contact_ids, payload.deal_id,
            )
        except besprechungen.NichtGefunden as exc:
            raise HTTPException(404, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        await audit.log_fuer(
            conn, user, action="update", entity="besprechungen", entity_id=besprechung_id,
            diff={
                "zugeordnet": True,
                "company_id": str(payload.company_id) if payload.company_id else None,
                "contact_ids": [str(c) for c in payload.contact_ids],
                "deal_id": str(payload.deal_id) if payload.deal_id else None,
                "activity_id": str(aktivitaet),
            },
        )
    return await eine(besprechung_id, user)


@router.post("/{besprechung_id}/loesen", response_model=BesprechungVoll)
async def loesen(besprechung_id: UUID, user: CurrentUser = Depends(get_current_user)) -> BesprechungVoll:
    async with acquire_as(user.user_id) as conn:
        try:
            await besprechungen.loesen(conn, besprechung_id)
        except besprechungen.NichtGefunden as exc:
            raise HTTPException(404, str(exc)) from exc
        await besprechungen.vorschlagen(conn, besprechung_id)
        await audit.log_fuer(
            conn, user, action="update", entity="besprechungen", entity_id=besprechung_id,
            diff={"zugeordnet": False},
        )
    return await eine(besprechung_id, user)


@router.post("/{besprechung_id}/verwerfen", status_code=204)
async def verwerfen(besprechung_id: UUID, user: CurrentUser = Depends(get_current_user)) -> None:
    async with acquire_as(user.user_id) as conn:
        weg = await conn.fetchval(
            "update public.besprechungen set status = 'verworfen', updated_at = now() "
            "where id = $1 and status = 'offen' and deleted_at is null returning id",
            besprechung_id,
        )
    if weg is None:
        raise HTTPException(404, "Nicht gefunden oder nicht mehr offen")


@router.post("/{besprechung_id}/vorschlagen", response_model=BesprechungVoll)
async def neu_vorschlagen(besprechung_id: UUID, user: CurrentUser = Depends(get_current_user)) -> BesprechungVoll:
    """Fragt noch einmal — etwa nachdem ein fehlender Kontakt angelegt wurde."""
    async with acquire_as(user.user_id) as conn:
        vorhanden = await conn.fetchval(
            "select 1 from public.besprechungen where id = $1 and deleted_at is null", besprechung_id
        )
        if not vorhanden:
            raise HTTPException(404, "Besprechung nicht gefunden")
        vorschlag = await besprechungen.vorschlagen(conn, besprechung_id)
        if besprechungen.braucht_modell(vorschlag):
            await besprechungen.vorschlag_ueber_modell(conn, user.org_id, besprechung_id)
    return await eine(besprechung_id, user)
