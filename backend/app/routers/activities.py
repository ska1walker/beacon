"""Aktivitäten — die Zeitleiste an Firma, Kontakt und Deal."""

from uuid import UUID

import orjson
from fastapi import APIRouter, Depends, HTTPException, Query

from app.auth import CurrentUser, get_current_user
from app.db import acquire_as
from app.schemas import Activity, ActivityIn

router = APIRouter(prefix="/api/activities", tags=["activities"])


@router.get("", response_model=list[Activity])
async def list_activities(
    user: CurrentUser = Depends(get_current_user),
    company_id: UUID | None = Query(None),
    contact_id: UUID | None = Query(None),
    deal_id: UUID | None = Query(None),
    limit: int = Query(50, le=200),
) -> list[Activity]:
    """Verlauf zu einem Datensatz, oder — ohne Bezug — der der Organisation.

    Bei einer Firma zählt auch, was an ihren Kontakten und Deals passiert
    ist: sonst steht auf der Firmenseite eine leere Leiste, obwohl gestern
    telefoniert wurde.
    """
    sql = """
    select a.*, u.display_name as created_by_name
    from public.activities a
    left join public.users u on u.id = a.created_by
    where true
    """
    args: list[object] = []
    if company_id:
        args.append(company_id)
        n = len(args)
        sql += f"""
          and (a.company_id = ${n}
               or a.contact_id in (select id from public.contacts where company_id = ${n})
               or a.deal_id in (select id from public.deals where company_id = ${n}))
        """
    if contact_id:
        args.append(contact_id)
        sql += f" and a.contact_id = ${len(args)}"
    if deal_id:
        args.append(deal_id)
        sql += f" and a.deal_id = ${len(args)}"
    args.append(limit)
    sql += f" order by a.occurred_at desc limit ${len(args)}"

    async with acquire_as(user.user_id) as conn:
        rows = await conn.fetch(sql, *args)
    return [Activity(**{**dict(r), "payload": orjson.loads(r["payload"])}) for r in rows]


@router.post("", response_model=Activity, status_code=201)
async def create_activity(
    payload: ActivityIn,
    user: CurrentUser = Depends(get_current_user),
) -> Activity:
    if not (payload.company_id or payload.contact_id or payload.deal_id):
        raise HTTPException(400, "Eine Aktivität braucht einen Bezug: Firma, Kontakt oder Deal.")

    async with acquire_as(user.user_id) as conn:
        row = await conn.fetchrow(
            """
            insert into public.activities
              (org_id, kind, subject, body, occurred_at, company_id, contact_id, deal_id,
               payload, created_by)
            values ($1, $2::public.activity_kind, $3, $4, coalesce($5, now()), $6, $7, $8,
                    $9::jsonb, $10)
            returning *
            """,
            user.org_id,
            payload.kind,
            payload.subject,
            payload.body,
            payload.occurred_at,
            payload.company_id,
            payload.contact_id,
            payload.deal_id,
            orjson.dumps(payload.payload).decode(),
            user.user_id,
        )
    return Activity(
        **{**dict(row), "payload": orjson.loads(row["payload"]), "created_by_name": user.display_name}
    )
