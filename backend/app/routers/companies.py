"""Firmen."""

from typing import Any
from uuid import UUID

import orjson
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from app import anreicherung, audit, segmente
from app.auth import CurrentUser, get_current_user
from app.db import acquire_as
from app.patching import build_update
from app.schemas import Company, CompanyIn, CompanyPatch

router = APIRouter(prefix="/api/companies", tags=["companies"])

# Zahlen zur Firma kommen aus Unterabfragen statt aus drei Joins mit
# GROUP BY: die Liste bleibt sonst bei jedem zusätzlichen Feld eine neue
# Gruppierungsdiskussion.
LIST_SQL = """
select c.*,
       (select count(*) from public.contacts k
         where k.company_id = c.id and k.deleted_at is null) as contact_count,
       (select count(*) from public.deals d
         join public.pipeline_stages s on s.id = d.stage_id
         where d.company_id = c.id and d.deleted_at is null and s.kind = 'open') as open_deal_count,
       (select coalesce(sum(d.amount_cents), 0) from public.deals d
         join public.pipeline_stages s on s.id = d.stage_id
         where d.company_id = c.id and d.deleted_at is null and s.kind = 'open') as open_amount_cents
from public.companies c
where c.deleted_at is null
"""


async def _custom_pruefen(conn, entity: str, werte: dict | None) -> str:
    """Prüft eigene Eigenschaften gegen ihre Definition, gibt JSON zurück."""
    import json

    from app import eigenschaften

    try:
        geprueft = eigenschaften.pruefen(werte or {}, await eigenschaften.definitionen(conn, entity))
    except eigenschaften.Ungueltig as exc:
        raise HTTPException(400, str(exc)) from exc
    return json.dumps(geprueft)


def _bedingungen(sql: str, args: list[Any], q: str | None, stage: str | None, filter: str | None) -> str:
    """Freitext, Stufe und das Segment — in dieser Reihenfolge."""
    if q:
        args.append(f"%{q}%")
        sql += f" and (c.name ilike ${len(args)} or c.domain ilike ${len(args)} or c.city ilike ${len(args)})"
    if stage:
        args.append(stage)
        sql += f" and c.lifecycle_stage = ${len(args)}::public.lifecycle_stage"
    if filter:
        try:
            bedingungen = segmente.bedingungen_aus(orjson.loads(filter))
            sql += segmente.filter_zu_sql("companies", bedingungen, args)
        except (orjson.JSONDecodeError, segmente.Ungueltig) as exc:
            raise HTTPException(400, f"Filter nicht verwendbar: {exc}") from exc
    return sql


def abfrage_sql(
    args: list[Any], q: str | None, filter: str | None,
    sort: str | None, richtung: str | None, stage: str | None = None,
) -> str:
    """Die vollständige Abfrage ohne `limit` — Liste, Zählung und Ausfuhr.

    Die Ausfuhr soll exakt das liefern, was die Tabelle zeigt. Ein
    zweiter Filterbauer daneben wäre die Stelle, an der beide
    auseinanderlaufen, ohne dass es jemand merkt.
    """
    sql = _bedingungen(LIST_SQL, args, q, stage, filter)
    try:
        return sql + segmente.sortierung_zu_sql("companies", sort, richtung)
    except segmente.Ungueltig as exc:
        raise HTTPException(400, str(exc)) from exc


async def einfuegen(conn, user: CurrentUser, payload: CompanyIn, custom_json: str) -> UUID:
    """Legt eine Firma an und protokolliert es. Ohne Anreicherung.

    Der Endpunkt stößt danach die Anreicherung an, die Einfuhr nicht —
    siehe `contacts.einfuegen` für den Grund.
    """
    new_id = await conn.fetchval(
        """
        insert into public.companies
          (org_id, name, domain, industry, employee_count, city, country, phone,
           website, lifecycle_stage, source, description, owner_id, created_by, custom,
           street, postal_code, linkedin_url)
        values ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10::public.lifecycle_stage,$11,$12,$13,$14,$15::jsonb,
                $16,$17,$18)
        returning id
        """,
        user.org_id,
        payload.name,
        payload.domain,
        payload.industry,
        payload.employee_count,
        payload.city,
        payload.country,
        payload.phone,
        payload.website,
        payload.lifecycle_stage,
        payload.source,
        payload.description,
        payload.owner_id or user.user_id,
        user.user_id,
        custom_json,
        payload.street,
        payload.postal_code,
        payload.linkedin_url,
    )
    await audit.log_fuer(
        conn, user, action="create", entity="companies", entity_id=new_id,
        diff=payload.model_dump(mode="json"),
    )
    return new_id


@router.get("", response_model=list[Company])
async def list_companies(
    user: CurrentUser = Depends(get_current_user),
    q: str | None = Query(None, description="Freitext über Name, Domain, Ort"),
    stage: str | None = Query(None),
    filter: str | None = Query(None, description="Bedingungen als JSON-Liste"),
    sort: str | None = Query(None),
    richtung: str | None = Query(None),
    limit: int = Query(50, le=200),
    offset: int = Query(0, ge=0),
) -> list[Company]:
    args: list[Any] = []
    sql = abfrage_sql(args, q, filter, sort, richtung, stage)
    args.extend([limit, offset])
    sql += f" limit ${len(args) - 1} offset ${len(args)}"

    async with acquire_as(user.user_id) as conn:
        rows = await conn.fetch(sql, *args)
    return [Company(**dict(r)) for r in rows]


@router.get("/anzahl")
async def anzahl_companies(
    user: CurrentUser = Depends(get_current_user),
    q: str | None = Query(None),
    stage: str | None = Query(None),
    filter: str | None = Query(None),
) -> dict[str, int]:
    """Wie viele es insgesamt sind — die Liste selbst ist begrenzt."""
    args: list[Any] = []
    sql = _bedingungen(
        "select count(*) from public.companies c where c.deleted_at is null",
        args, q, stage, filter,
    )
    async with acquire_as(user.user_id) as conn:
        return {"anzahl": await conn.fetchval(sql, *args) or 0}


class Stapel(BaseModel):
    ids: list[UUID]


class StapelAenderung(Stapel):
    lifecycle_stage: str | None = None
    owner_id: UUID | None = None
    industry: str | None = None
    source: str | None = None


@router.post("/mehrere")
async def mehrere_aendern(
    payload: StapelAenderung,
    user: CurrentUser = Depends(get_current_user),
) -> dict[str, int]:
    """Setzt ein Feld an vielen Firmen auf einmal."""
    if not payload.ids:
        raise HTTPException(400, "Keine Firmen gewählt")
    if len(payload.ids) > 500:
        raise HTTPException(400, "Höchstens 500 auf einmal")

    felder = payload.model_dump(exclude_unset=True, exclude={"ids"})
    if not felder:
        raise HTTPException(400, "Keine Änderung übergeben")

    zuweisungen: list[str] = []
    args: list[Any] = []
    for name, wert in felder.items():
        args.append(wert)
        guss = "::public.lifecycle_stage" if name == "lifecycle_stage" else ""
        zuweisungen.append(f"{name} = ${len(args)}{guss}")
    args.append(payload.ids)

    async with acquire_as(user.user_id) as conn:
        rows = await conn.fetch(
            f"update public.companies set {', '.join(zuweisungen)}, updated_at = now() "
            f"where id = any(${len(args)}::uuid[]) and deleted_at is null returning id",
            *args,
        )
        for r in rows:
            await audit.log_fuer(
                conn, user, action="update", entity="companies", entity_id=r["id"], diff=felder
            )
    return {"geaendert": len(rows)}


@router.post("/mehrere/loeschen")
async def mehrere_loeschen(
    payload: Stapel,
    user: CurrentUser = Depends(get_current_user),
) -> dict[str, int]:
    if not payload.ids:
        raise HTTPException(400, "Keine Firmen gewählt")
    async with acquire_as(user.user_id) as conn:
        rows = await conn.fetch(
            "update public.companies set deleted_at = now() "
            "where id = any($1::uuid[]) and deleted_at is null returning id",
            payload.ids,
        )
        for r in rows:
            await audit.log_fuer(conn, user, action="delete", entity="companies", entity_id=r["id"])
    return {"geloescht": len(rows)}


@router.get("/{company_id}", response_model=Company)
async def get_company(
    company_id: UUID,
    user: CurrentUser = Depends(get_current_user),
) -> Company:
    async with acquire_as(user.user_id) as conn:
        row = await conn.fetchrow(LIST_SQL + " and c.id = $1", company_id)
    if row is None:
        raise HTTPException(404, "Firma nicht gefunden")
    return Company(**dict(row))


@router.post("", response_model=Company, status_code=201)
async def create_company(
    payload: CompanyIn,
    user: CurrentUser = Depends(get_current_user),
) -> Company:
    async with acquire_as(user.user_id) as conn:
        new_id = await einfuegen(
            conn, user, payload, await _custom_pruefen(conn, "companies", payload.custom)
        )
        full = await conn.fetchrow(LIST_SQL + " and c.id = $1", new_id)
    # Was über die Firma öffentlich zu finden ist, wird jetzt gesucht —
    # ohne dass jemand darauf wartet.
    anreicherung.im_hintergrund(user, "companies", new_id)
    return Company(**dict(full))


@router.patch("/{company_id}", response_model=Company)
async def update_company(
    company_id: UUID,
    payload: CompanyPatch,
    user: CurrentUser = Depends(get_current_user),
) -> Company:
    if "custom" in payload.model_fields_set:
        async with acquire_as(user.user_id) as conn:
            import json

            geprueft = json.loads(await _custom_pruefen(conn, "companies", payload.custom))
        payload = payload.model_copy(update={"custom": geprueft})
    try:
        zuweisungen, args = build_update(payload)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    args.append(company_id)

    async with acquire_as(user.user_id) as conn:
        updated = await conn.fetchval(
            f"update public.companies set {zuweisungen} "
            f"where id = ${len(args)} and deleted_at is null returning id",
            *args,
        )
        if updated is None:
            raise HTTPException(404, "Firma nicht gefunden")
        await audit.log_fuer(
            conn,
            user,
            action="update",
            entity="companies",
            entity_id=company_id,
            diff=payload.model_dump(mode="json", exclude_unset=True),
        )
        row = await conn.fetchrow(LIST_SQL + " and c.id = $1", company_id)
    return Company(**dict(row))


@router.delete("/{company_id}", status_code=204)
async def delete_company(
    company_id: UUID,
    user: CurrentUser = Depends(get_current_user),
) -> None:
    # Weiches Löschen mit Frist — Kernprinzip Reversibilität. Es gibt
    # bewusst keinen Weg über die API, der die Zeile sofort entfernt.
    async with acquire_as(user.user_id) as conn:
        deleted = await conn.fetchval(
            "update public.companies set deleted_at = now() "
            "where id = $1 and deleted_at is null returning id",
            company_id,
        )
        if deleted is None:
            raise HTTPException(404, "Firma nicht gefunden")
        await audit.log_fuer(
            conn,
            user,
            action="delete",
            entity="companies",
            entity_id=company_id,
        )
