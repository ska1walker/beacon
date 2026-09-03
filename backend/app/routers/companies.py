"""Firmen."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query

from app import audit
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


@router.get("", response_model=list[Company])
async def list_companies(
    user: CurrentUser = Depends(get_current_user),
    q: str | None = Query(None, description="Freitext über Name, Domain, Ort"),
    stage: str | None = Query(None),
    limit: int = Query(50, le=200),
    offset: int = Query(0, ge=0),
) -> list[Company]:
    sql = LIST_SQL
    args: list[object] = []
    if q:
        args.append(f"%{q}%")
        sql += f" and (c.name ilike ${len(args)} or c.domain ilike ${len(args)} or c.city ilike ${len(args)})"
    if stage:
        args.append(stage)
        sql += f" and c.lifecycle_stage = ${len(args)}::public.lifecycle_stage"
    args.extend([limit, offset])
    sql += f" order by c.updated_at desc limit ${len(args) - 1} offset ${len(args)}"

    async with acquire_as(user.user_id) as conn:
        rows = await conn.fetch(sql, *args)
    return [Company(**dict(r)) for r in rows]


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
        row = await conn.fetchrow(
            """
            insert into public.companies
              (org_id, name, domain, industry, employee_count, city, country, phone,
               website, lifecycle_stage, source, description, owner_id, created_by)
            values ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10::public.lifecycle_stage,$11,$12,$13,$14)
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
        )
        await audit.log(
            conn,
            org_id=user.org_id,
            actor_id=user.user_id,
            action="create",
            entity="companies",
            entity_id=row["id"],
            diff=payload.model_dump(mode="json"),
        )
        full = await conn.fetchrow(LIST_SQL + " and c.id = $1", row["id"])
    return Company(**dict(full))


@router.patch("/{company_id}", response_model=Company)
async def update_company(
    company_id: UUID,
    payload: CompanyPatch,
    user: CurrentUser = Depends(get_current_user),
) -> Company:
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
        await audit.log(
            conn,
            org_id=user.org_id,
            actor_id=user.user_id,
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
        await audit.log(
            conn,
            org_id=user.org_id,
            actor_id=user.user_id,
            action="delete",
            entity="companies",
            entity_id=company_id,
        )
