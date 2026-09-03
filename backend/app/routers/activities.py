"""Aktivitäten — die Zeitleiste an Firma, Kontakt und Deal."""

from datetime import datetime
from uuid import UUID

import orjson
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from app.auth import CurrentUser, get_current_user
from app.db import acquire_as
from app.schemas import Activity, ActivityIn

# Nur, was ein Mensch geschrieben hat, lässt sich ändern oder zurücknehmen.
# Stufenwechsel, KI-Ergebnisse und Systemeinträge sind Geschichte.
MENSCHLICH = ("note", "call", "email", "meeting", "task")


class ActivityPatch(BaseModel):
    subject: str | None = None
    body: str | None = None
    occurred_at: datetime | None = None

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
    where a.deleted_at is null
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


@router.patch("/{activity_id}", response_model=Activity)
async def aendern(activity_id: UUID, payload: ActivityPatch, user: CurrentUser = Depends(get_current_user)) -> Activity:
    felder = payload.model_dump(exclude_unset=True)
    if not felder:
        raise HTTPException(400, "Keine Änderung übergeben")
    zuw = ", ".join(f"{k} = ${i + 1}" for i, k in enumerate(felder))
    async with acquire_as(user.user_id) as conn:
        art = await conn.fetchval("select kind from public.activities where id = $1 and deleted_at is null", activity_id)
        if art is None:
            raise HTTPException(404, "Eintrag nicht gefunden")
        if art not in MENSCHLICH:
            raise HTTPException(409, "Dieser Eintrag ist Geschichte und lässt sich nicht ändern.")
        row = await conn.fetchrow(
            f"update public.activities set {zuw}, updated_at = now() where id = ${len(felder) + 1} returning *",
            *felder.values(), activity_id,
        )
    return Activity(**{**dict(row), "payload": orjson.loads(row["payload"]), "created_by_name": user.display_name})


@router.delete("/{activity_id}", status_code=204)
async def zuruecknehmen(activity_id: UUID, user: CurrentUser = Depends(get_current_user)) -> None:
    async with acquire_as(user.user_id) as conn:
        art = await conn.fetchval("select kind from public.activities where id = $1 and deleted_at is null", activity_id)
        if art is None:
            raise HTTPException(404, "Eintrag nicht gefunden")
        if art not in MENSCHLICH:
            raise HTTPException(409, "Dieser Eintrag ist Geschichte und lässt sich nicht zurücknehmen.")
        await conn.execute("update public.activities set deleted_at = now() where id = $1", activity_id)
