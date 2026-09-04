"""Aufgaben.

Eine Aufgabenliste ist der Ort, an dem der Tag geplant wird. Dafür
braucht sie drei Fragen beantwortet: Was ist heute fällig, was ist
liegengeblieben, und was steht als Nächstes an. Genau das sind die
Reiter — und darunter dieselbe Segmentierung wie bei Firmen, Kontakten
und Tickets.
"""

from datetime import date, datetime, time, timedelta
from typing import Any
from uuid import UUID

import orjson
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from app import audit, segmente
from app.auth import CurrentUser, get_current_user
from app.db import acquire_as
from app.patching import build_update
from app.schemas import Task, TaskIn, TaskPatch

router = APIRouter(prefix="/api/tasks", tags=["tasks"])

# Die Bezüge kommen alle mit: Eine Aufgabe ohne den Namen dessen, worum
# es geht, ist in einer Liste von dreißig nicht mehr zuzuordnen.
LIST_SQL = """
select t.*, d.name as deal_name, f.name as company_name,
       ti.betreff as ticket_betreff,
       coalesce(k.first_name || ' ', '') || coalesce(k.last_name, '') as kontakt_name,
       coalesce(u.display_name, u.olares_username) as zustaendig_name
from public.tasks t
left join public.deals d on d.id = t.deal_id
left join public.companies f on f.id = t.company_id
left join public.contacts k on k.id = t.contact_id
left join public.tickets ti on ti.id = t.ticket_id
left join public.users u on u.id = t.assigned_to
where true
"""


def _tagesgrenzen(tage: int = 0) -> tuple[datetime, datetime]:
    """Anfang und Ende eines Tages in der Zeitzone dieser Box.

    In UTC zu rechnen wäre einfacher und falsch: „heute fällig" richtet
    sich nach dem Kalender dessen, der davorsitzt.
    """
    tag = date.today() + timedelta(days=tage)
    zone = datetime.now().astimezone().tzinfo
    return (
        datetime.combine(tag, time.min, tzinfo=zone),
        datetime.combine(tag, time.max, tzinfo=zone),
    )


def _bedingungen(
    sql: str,
    args: list[Any],
    *,
    status: str | None,
    q: str | None,
    faellig: str | None,
    mein: bool,
    user_id: UUID,
    deal_id: UUID | None,
    company_id: UUID | None,
    contact_id: UUID | None,
    ticket_id: UUID | None,
    filter: str | None,
) -> str:
    if status:
        args.append(status)
        sql += f" and t.status = ${len(args)}::public.task_status"
    if q:
        args.append(f"%{q}%")
        sql += f" and (t.title ilike ${len(args)} or t.body ilike ${len(args)})"
    if mein:
        args.append(user_id)
        sql += f" and t.assigned_to = ${len(args)}"

    # Die drei Fragen einer Aufgabenliste.
    if faellig == "heute":
        von, bis = _tagesgrenzen()
        args.extend([von, bis])
        sql += f" and t.due_at between ${len(args) - 1} and ${len(args)}"
    elif faellig == "ueberfaellig":
        args.append(_tagesgrenzen()[0])
        sql += f" and t.due_at < ${len(args)}"
    elif faellig == "bevorstehend":
        args.append(_tagesgrenzen()[1])
        sql += f" and t.due_at > ${len(args)}"
    elif faellig == "ohne":
        sql += " and t.due_at is null"

    for spalte, wert in (
        ("deal_id", deal_id), ("company_id", company_id),
        ("contact_id", contact_id), ("ticket_id", ticket_id),
    ):
        if wert:
            args.append(wert)
            sql += f" and t.{spalte} = ${len(args)}"

    if filter:
        try:
            sql += segmente.filter_zu_sql("tasks", segmente.bedingungen_aus(orjson.loads(filter)), args)
        except (orjson.JSONDecodeError, segmente.Ungueltig) as exc:
            raise HTTPException(400, f"Filter nicht verwendbar: {exc}") from exc
    return sql


@router.get("", response_model=list[Task])
async def list_tasks(
    user: CurrentUser = Depends(get_current_user),
    status: str | None = Query("open", description="offen/erledigt/verworfen; leer = alle"),
    q: str | None = Query(None),
    faellig: str | None = Query(None, description="heute | ueberfaellig | bevorstehend | ohne"),
    mein: bool = Query(False),
    deal_id: UUID | None = Query(None),
    company_id: UUID | None = Query(None),
    contact_id: UUID | None = Query(None),
    ticket_id: UUID | None = Query(None),
    filter: str | None = Query(None),
    sort: str | None = Query(None),
    richtung: str | None = Query(None),
    limit: int = Query(100, le=300),
    offset: int = Query(0, ge=0),
) -> list[Task]:
    args: list[Any] = []
    sql = _bedingungen(
        LIST_SQL, args, status=status, q=q, faellig=faellig, mein=mein, user_id=user.user_id,
        deal_id=deal_id, company_id=company_id, contact_id=contact_id, ticket_id=ticket_id,
        filter=filter,
    )
    if sort:
        try:
            sql += segmente.sortierung_zu_sql("tasks", sort, richtung)
        except segmente.Ungueltig as exc:
            raise HTTPException(400, str(exc)) from exc
    else:
        # Ohne ausdrückliche Sortierung: nach Frist, Undatiertes zuletzt.
        # NULLS FIRST setzte das Unverbindliche über das, was heute ansteht.
        sql += " order by t.due_at asc nulls last, t.created_at desc"
    args.extend([limit, offset])
    sql += f" limit ${len(args) - 1} offset ${len(args)}"

    async with acquire_as(user.user_id) as conn:
        rows = await conn.fetch(sql, *args)
    return [Task(**dict(r)) for r in rows]


@router.get("/anzahl")
async def anzahl(
    user: CurrentUser = Depends(get_current_user),
    status: str | None = Query("open"),
    q: str | None = Query(None),
    faellig: str | None = Query(None),
    mein: bool = Query(False),
    deal_id: UUID | None = Query(None),
    company_id: UUID | None = Query(None),
    contact_id: UUID | None = Query(None),
    ticket_id: UUID | None = Query(None),
    filter: str | None = Query(None),
) -> dict[str, int]:
    args: list[Any] = []
    sql = _bedingungen(
        "select count(*) from public.tasks t "
        "left join public.deals d on d.id = t.deal_id "
        "left join public.companies f on f.id = t.company_id "
        "left join public.contacts k on k.id = t.contact_id "
        "left join public.tickets ti on ti.id = t.ticket_id "
        "where true",
        args, status=status, q=q, faellig=faellig, mein=mein, user_id=user.user_id,
        deal_id=deal_id, company_id=company_id, contact_id=contact_id, ticket_id=ticket_id,
        filter=filter,
    )
    async with acquire_as(user.user_id) as conn:
        return {"anzahl": await conn.fetchval(sql, *args) or 0}


@router.get("/uebersicht")
async def uebersicht(user: CurrentUser = Depends(get_current_user)) -> dict[str, int]:
    """Die Zahlen für die Reiter — in einer Abfrage statt in vier.

    Vier Abfragen wären vier Roundtrips für eine Leiste, die bei jedem
    Seitenwechsel neu gezeichnet wird.
    """
    von, bis = _tagesgrenzen()
    async with acquire_as(user.user_id) as conn:
        z = await conn.fetchrow(
            """
            select
              count(*) filter (where status = 'open') as offen,
              count(*) filter (where status = 'open' and due_at between $1 and $2) as heute,
              count(*) filter (where status = 'open' and due_at < $1) as ueberfaellig,
              count(*) filter (where status = 'open' and due_at > $2) as bevorstehend,
              count(*) filter (where status = 'open' and assigned_to = $3) as meine
            from public.tasks
            """,
            von, bis, user.user_id,
        )
    return {k: int(v or 0) for k, v in dict(z).items()}


@router.post("", response_model=Task, status_code=201)
async def create_task(payload: TaskIn, user: CurrentUser = Depends(get_current_user)) -> Task:
    async with acquire_as(user.user_id) as conn:
        neu = await conn.fetchval(
            """
            insert into public.tasks
              (org_id, title, body, due_at, art, prioritaet, phase,
               company_id, contact_id, deal_id, ticket_id, assigned_to, created_by)
            values ($1,$2,$3,$4,$5::public.aufgaben_art,$6::public.ticket_prioritaet,
                    $7::public.aufgaben_phase,$8,$9,$10,$11,$12,$13)
            returning id
            """,
            user.org_id,
            payload.title,
            payload.body,
            payload.due_at,
            payload.art,
            payload.prioritaet,
            payload.phase,
            payload.company_id,
            payload.contact_id,
            payload.deal_id,
            payload.ticket_id,
            payload.assigned_to or user.user_id,
            user.user_id,
        )
        row = await conn.fetchrow(LIST_SQL + " and t.id = $1", neu)
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
    args.append(user.user_id)
    zuweisungen += f", updated_by = ${len(args)}, updated_at = now()"
    args.append(task_id)

    async with acquire_as(user.user_id) as conn:
        neu = await conn.fetchval(
            f"update public.tasks set {zuweisungen} where id = ${len(args)} returning id", *args
        )
        if neu is None:
            raise HTTPException(404, "Aufgabe nicht gefunden")
        row = await conn.fetchrow(LIST_SQL + " and t.id = $1", task_id)
    return Task(**dict(row))


@router.delete("/{task_id}", status_code=204)
async def delete_task(task_id: UUID, user: CurrentUser = Depends(get_current_user)) -> None:
    """Eine Aufgabe ist kein Datensatz mit Geschichte — sie geht ganz weg.

    Verworfen (`cancelled`) ist der Weg, sie zu behalten. Wer löscht,
    meint löschen.
    """
    async with acquire_as(user.user_id) as conn:
        weg = await conn.fetchval(
            "delete from public.tasks where id = $1 returning id", task_id
        )
        if weg is None:
            raise HTTPException(404, "Aufgabe nicht gefunden")
        await audit.log_fuer(conn, user, action="delete", entity="tasks", entity_id=task_id)


# ── Stapel ──────────────────────────────────────────────────────────────

class Stapel(BaseModel):
    ids: list[UUID]


class StapelAenderung(Stapel):
    status: str | None = None
    phase: str | None = None
    art: str | None = None
    prioritaet: str | None = None
    assigned_to: UUID | None = None


@router.post("/mehrere")
async def mehrere_aendern(
    payload: StapelAenderung, user: CurrentUser = Depends(get_current_user)
) -> dict[str, int]:
    if not payload.ids:
        raise HTTPException(400, "Keine Aufgaben gewählt")
    felder = payload.model_dump(exclude_unset=True, exclude={"ids"})
    if not felder:
        raise HTTPException(400, "Keine Änderung übergeben")

    gussformen = {
        "status": "::public.task_status",
        "phase": "::public.aufgaben_phase",
        "art": "::public.aufgaben_art",
        "prioritaet": "::public.ticket_prioritaet",
    }
    zuweisungen: list[str] = []
    args: list[Any] = []
    for name, wert in felder.items():
        args.append(wert)
        zuweisungen.append(f"{name} = ${len(args)}{gussformen.get(name, '')}")
    if payload.status == "done":
        zuweisungen.append("completed_at = now()")
    elif payload.status in ("open", "cancelled"):
        zuweisungen.append("completed_at = null")
    args.append(payload.ids)

    async with acquire_as(user.user_id) as conn:
        rows = await conn.fetch(
            f"update public.tasks set {', '.join(zuweisungen)}, updated_at = now() "
            f"where id = any(${len(args)}::uuid[]) returning id",
            *args,
        )
        for r in rows:
            await audit.log_fuer(
                conn, user, action="update", entity="tasks", entity_id=r["id"], diff=felder
            )
    return {"geaendert": len(rows)}


@router.post("/mehrere/loeschen")
async def mehrere_loeschen(
    payload: Stapel, user: CurrentUser = Depends(get_current_user)
) -> dict[str, int]:
    if not payload.ids:
        raise HTTPException(400, "Keine Aufgaben gewählt")
    async with acquire_as(user.user_id) as conn:
        rows = await conn.fetch(
            "delete from public.tasks where id = any($1::uuid[]) returning id", payload.ids
        )
        for r in rows:
            await audit.log_fuer(conn, user, action="delete", entity="tasks", entity_id=r["id"])
    return {"geloescht": len(rows)}
