"""Kontakte."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query

from app import audit
from app.auth import CurrentUser, get_current_user
from app.db import acquire_as
from app.patching import build_update
from app.schemas import Contact, ContactIn, ContactPatch

router = APIRouter(prefix="/api/contacts", tags=["contacts"])

LIST_SQL = """
select k.*, f.name as company_name
from public.contacts k
left join public.companies f on f.id = k.company_id
where k.deleted_at is null
"""


@router.get("", response_model=list[Contact])
async def list_contacts(
    user: CurrentUser = Depends(get_current_user),
    q: str | None = Query(None),
    company_id: UUID | None = Query(None),
    limit: int = Query(50, le=200),
    offset: int = Query(0, ge=0),
) -> list[Contact]:
    sql = LIST_SQL
    args: list[object] = []
    if q:
        args.append(f"%{q}%")
        n = len(args)
        sql += (
            f" and (coalesce(k.first_name,'') || ' ' || coalesce(k.last_name,'') ilike ${n}"
            f" or k.email ilike ${n} or f.name ilike ${n})"
        )
    if company_id:
        args.append(company_id)
        sql += f" and k.company_id = ${len(args)}"
    args.extend([limit, offset])
    sql += f" order by k.updated_at desc limit ${len(args) - 1} offset ${len(args)}"

    async with acquire_as(user.user_id) as conn:
        rows = await conn.fetch(sql, *args)
    return [Contact(**dict(r)) for r in rows]


@router.get("/{contact_id}", response_model=Contact)
async def get_contact(
    contact_id: UUID,
    user: CurrentUser = Depends(get_current_user),
) -> Contact:
    async with acquire_as(user.user_id) as conn:
        row = await conn.fetchrow(LIST_SQL + " and k.id = $1", contact_id)
    if row is None:
        raise HTTPException(404, "Kontakt nicht gefunden")
    return Contact(**dict(row))


@router.post("", response_model=Contact, status_code=201)
async def create_contact(
    payload: ContactIn,
    user: CurrentUser = Depends(get_current_user),
) -> Contact:
    async with acquire_as(user.user_id) as conn:
        new_id = await conn.fetchval(
            """
            insert into public.contacts
              (org_id, company_id, first_name, last_name, email, phone, mobile, job_title,
               buying_role, linkedin_url, lifecycle_stage, source, notes, owner_id, created_by)
            values ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11::public.lifecycle_stage,$12,$13,$14,$15)
            returning id
            """,
            user.org_id,
            payload.company_id,
            payload.first_name,
            payload.last_name,
            str(payload.email) if payload.email else None,
            payload.phone,
            payload.mobile,
            payload.job_title,
            payload.buying_role,
            payload.linkedin_url,
            payload.lifecycle_stage,
            payload.source,
            payload.notes,
            payload.owner_id or user.user_id,
            user.user_id,
        )
        await audit.log(
            conn,
            org_id=user.org_id,
            actor_id=user.user_id,
            action="create",
            entity="contacts",
            entity_id=new_id,
            diff=payload.model_dump(mode="json"),
        )
        row = await conn.fetchrow(LIST_SQL + " and k.id = $1", new_id)
    return Contact(**dict(row))


@router.patch("/{contact_id}", response_model=Contact)
async def update_contact(
    contact_id: UUID,
    payload: ContactPatch,
    user: CurrentUser = Depends(get_current_user),
) -> Contact:
    try:
        zuweisungen, args = build_update(payload)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    args.append(contact_id)

    async with acquire_as(user.user_id) as conn:
        updated = await conn.fetchval(
            f"update public.contacts set {zuweisungen} "
            f"where id = ${len(args)} and deleted_at is null returning id",
            *args,
        )
        if updated is None:
            raise HTTPException(404, "Kontakt nicht gefunden")
        await audit.log(
            conn,
            org_id=user.org_id,
            actor_id=user.user_id,
            action="update",
            entity="contacts",
            entity_id=contact_id,
            diff=payload.model_dump(mode="json", exclude_unset=True),
        )
        row = await conn.fetchrow(LIST_SQL + " and k.id = $1", contact_id)
    return Contact(**dict(row))


@router.delete("/{contact_id}", status_code=204)
async def delete_contact(
    contact_id: UUID,
    user: CurrentUser = Depends(get_current_user),
) -> None:
    async with acquire_as(user.user_id) as conn:
        deleted = await conn.fetchval(
            "update public.contacts set deleted_at = now() "
            "where id = $1 and deleted_at is null returning id",
            contact_id,
        )
        if deleted is None:
            raise HTTPException(404, "Kontakt nicht gefunden")
        await audit.log(
            conn,
            org_id=user.org_id,
            actor_id=user.user_id,
            action="delete",
            entity="contacts",
            entity_id=contact_id,
        )
