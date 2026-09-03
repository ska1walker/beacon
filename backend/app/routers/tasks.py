"""Aufgaben."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query

from app.auth import CurrentUser, get_current_user
from app.db import acquire_as
from app.patching import build_update
from app.schemas import Task, TaskIn, TaskPatch

router = APIRouter(prefix="/api/tasks", tags=["tasks"])


@router.get("", response_model=list[Task])
async def list_tasks(
    user: CurrentUser = Depends(get_current_user),
    status: str = Query("open"),
    deal_id: UUID | None = Query(None),
    company_id: UUID | None = Query(None),
    contact_id: UUID | None = Query(None),
    limit: int = Query(100, le=300),
) -> list[Task]:
    sql = ("select t.*, d.name as deal_name, f.name as company_name from public.tasks t "
           "left join public.deals d on d.id = t.deal_id "
           "left join public.companies f on f.id = t.company_id "
           "where t.status = $1::public.task_status")
    args: list[object] = [status]
    for spalte, wert in (("deal_id", deal_id), ("company_id", company_id), ("contact_id", contact_id)):
        if wert:
            args.append(wert)
            sql += f" and t.{spalte} = ${len(args)}"
    args.append(limit)
    # Aufgaben ohne Frist zuletzt: NULLS FIRST würde die undatierten oben
    # einsortieren, und dort steht, was heute fällig ist.
    sql += f" order by t.due_at asc nulls last limit ${len(args)}"

    async with acquire_as(user.user_id) as conn:
        rows = await conn.fetch(sql, *args)
    return [Task(**dict(r)) for r in rows]


@router.post("", response_model=Task, status_code=201)
async def create_task(payload: TaskIn, user: CurrentUser = Depends(get_current_user)) -> Task:
    async with acquire_as(user.user_id) as conn:
        row = await conn.fetchrow(
            """
            insert into public.tasks
              (org_id, title, body, due_at, company_id, contact_id, deal_id, assigned_to, created_by)
            values ($1,$2,$3,$4,$5,$6,$7,$8,$9)
            returning *
            """,
            user.org_id,
            payload.title,
            payload.body,
            payload.due_at,
            payload.company_id,
            payload.contact_id,
            payload.deal_id,
            payload.assigned_to or user.user_id,
            user.user_id,
        )
    return Task(**dict(row))


@router.patch("/{task_id}", response_model=Task)
async def update_task(
    task_id: UUID,
    payload: TaskPatch,
    user: CurrentUser = Depends(get_current_user),
) -> Task:
    try:
        zuweisungen, args = build_update(payload)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    # completed_at gehört zum Zustand und wird nicht der Oberfläche
    # überlassen — sonst steht irgendwann „erledigt" ohne Zeitpunkt da.
    if payload.status == "done":
        zuweisungen += ", completed_at = now()"
    elif payload.status in ("open", "cancelled"):
        zuweisungen += ", completed_at = null"
    args.append(task_id)

    async with acquire_as(user.user_id) as conn:
        row = await conn.fetchrow(
            f"update public.tasks set {zuweisungen} where id = ${len(args)} returning *", *args
        )
    if row is None:
        raise HTTPException(404, "Aufgabe nicht gefunden")
    return Task(**dict(row))
