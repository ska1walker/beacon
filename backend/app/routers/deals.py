"""Deals, Pipelines und das Board."""

from uuid import UUID

import orjson
from fastapi import APIRouter, Depends, HTTPException, Query

from app import audit
from app.auth import CurrentUser, get_current_user
from app.db import acquire_as
from app.patching import build_update
from app.schemas import (
    Board,
    BoardColumn,
    Deal,
    DealIn,
    DealPatch,
    Pipeline,
    Stage,
    StageMove,
)

router = APIRouter(prefix="/api", tags=["deals"])

DEAL_SQL = """
select d.*, f.name as company_name, s.name as stage_name,
       s.kind as stage_kind, s.probability
from public.deals d
left join public.companies f on f.id = d.company_id
join public.pipeline_stages s on s.id = d.stage_id
where d.deleted_at is null
"""


async def _standard_pipeline(conn, org_id: UUID) -> UUID:
    pipeline_id = await conn.fetchval(
        """
        select id from public.pipelines
        where org_id = $1 and deleted_at is null
        order by is_default desc, position asc
        limit 1
        """,
        org_id,
    )
    if pipeline_id is None:
        raise HTTPException(500, "Keine Pipeline vorhanden — die Einrichtung ist unvollständig.")
    return pipeline_id


# ── Pipelines ───────────────────────────────────────────────────────────

@router.get("/pipelines", response_model=list[Pipeline])
async def list_pipelines(user: CurrentUser = Depends(get_current_user)) -> list[Pipeline]:
    async with acquire_as(user.user_id) as conn:
        pipelines = await conn.fetch(
            "select id, name, is_default from public.pipelines "
            "where deleted_at is null order by position, name"
        )
        stages = await conn.fetch(
            "select id, pipeline_id, name, kind, probability, position "
            "from public.pipeline_stages order by position"
        )
    nach_pipeline: dict[UUID, list[Stage]] = {}
    for s in stages:
        nach_pipeline.setdefault(s["pipeline_id"], []).append(
            Stage(
                id=s["id"],
                name=s["name"],
                kind=s["kind"],
                probability=float(s["probability"]),
                position=s["position"],
            )
        )
    return [
        Pipeline(
            id=p["id"],
            name=p["name"],
            is_default=p["is_default"],
            stages=nach_pipeline.get(p["id"], []),
        )
        for p in pipelines
    ]


@router.get("/board", response_model=Board)
async def get_board(
    user: CurrentUser = Depends(get_current_user),
    pipeline_id: UUID | None = Query(None),
) -> Board:
    """Das Board — eine Spalte je Stufe, mit Summe und gewichteter Summe.

    Gerechnet wird hier und nicht in der Oberfläche: die Zahl unter einer
    Spalte muss dieselbe sein, egal wer sie ansieht.
    """
    async with acquire_as(user.user_id) as conn:
        pid = pipeline_id or await _standard_pipeline(conn, user.org_id)
        pipeline = await conn.fetchrow(
            "select id, name, is_default from public.pipelines where id = $1 and deleted_at is null",
            pid,
        )
        if pipeline is None:
            raise HTTPException(404, "Pipeline nicht gefunden")
        stages = await conn.fetch(
            "select id, name, kind, probability, position from public.pipeline_stages "
            "where pipeline_id = $1 order by position",
            pid,
        )
        deals = await conn.fetch(DEAL_SQL + " and d.pipeline_id = $1 order by d.updated_at desc", pid)

    nach_stufe: dict[UUID, list[Deal]] = {}
    for row in deals:
        d = dict(row)
        d["probability"] = float(d["probability"])
        nach_stufe.setdefault(d["stage_id"], []).append(Deal(**d))

    spalten: list[BoardColumn] = []
    for s in stages:
        stufe = Stage(
            id=s["id"],
            name=s["name"],
            kind=s["kind"],
            probability=float(s["probability"]),
            position=s["position"],
        )
        eintraege = nach_stufe.get(s["id"], [])
        summe = sum(d.amount_cents for d in eintraege)
        spalten.append(
            BoardColumn(
                stage=stufe,
                deals=eintraege,
                sum_amount_cents=summe,
                weighted_amount_cents=round(summe * stufe.probability),
            )
        )

    return Board(
        pipeline=Pipeline(
            id=pipeline["id"],
            name=pipeline["name"],
            is_default=pipeline["is_default"],
            stages=[c.stage for c in spalten],
        ),
        columns=spalten,
    )


# ── Deals ───────────────────────────────────────────────────────────────

@router.get("/deals", response_model=list[Deal])
async def list_deals(
    user: CurrentUser = Depends(get_current_user),
    q: str | None = Query(None),
    company_id: UUID | None = Query(None),
    status: str | None = Query(None, description="open | won | lost"),
    limit: int = Query(50, le=200),
    offset: int = Query(0, ge=0),
) -> list[Deal]:
    sql = DEAL_SQL
    args: list[object] = []
    if q:
        args.append(f"%{q}%")
        sql += f" and (d.name ilike ${len(args)} or f.name ilike ${len(args)})"
    if company_id:
        args.append(company_id)
        sql += f" and d.company_id = ${len(args)}"
    if status:
        args.append(status)
        sql += f" and s.kind = ${len(args)}::public.stage_kind"
    args.extend([limit, offset])
    sql += f" order by d.updated_at desc limit ${len(args) - 1} offset ${len(args)}"

    async with acquire_as(user.user_id) as conn:
        rows = await conn.fetch(sql, *args)
    return [Deal(**{**dict(r), "probability": float(r["probability"])}) for r in rows]


@router.get("/deals/{deal_id}", response_model=Deal)
async def get_deal(deal_id: UUID, user: CurrentUser = Depends(get_current_user)) -> Deal:
    async with acquire_as(user.user_id) as conn:
        row = await conn.fetchrow(DEAL_SQL + " and d.id = $1", deal_id)
    if row is None:
        raise HTTPException(404, "Deal nicht gefunden")
    return Deal(**{**dict(row), "probability": float(row["probability"])})


@router.post("/deals", response_model=Deal, status_code=201)
async def create_deal(payload: DealIn, user: CurrentUser = Depends(get_current_user)) -> Deal:
    async with acquire_as(user.user_id) as conn:
        pid = payload.pipeline_id or await _standard_pipeline(conn, user.org_id)
        stage_id = payload.stage_id
        if stage_id is None:
            stage_id = await conn.fetchval(
                "select id from public.pipeline_stages where pipeline_id = $1 "
                "order by position limit 1",
                pid,
            )
        new_id = await conn.fetchval(
            """
            insert into public.deals
              (org_id, company_id, pipeline_id, stage_id, name, product, amount_cents,
               currency, service_days, close_date, next_step, owner_id, created_by)
            values ($1,$2,$3,$4,$5,$6::public.deal_product,$7,$8,$9,$10,$11,$12,$13)
            returning id
            """,
            user.org_id,
            payload.company_id,
            pid,
            stage_id,
            payload.name,
            payload.product,
            payload.amount_cents,
            payload.currency,
            payload.service_days,
            payload.close_date,
            payload.next_step,
            payload.owner_id or user.user_id,
            user.user_id,
        )
        await audit.log_fuer(
            conn,
            user,
            action="create",
            entity="deals",
            entity_id=new_id,
            diff=payload.model_dump(mode="json"),
        )
        row = await conn.fetchrow(DEAL_SQL + " and d.id = $1", new_id)
    return Deal(**{**dict(row), "probability": float(row["probability"])})


@router.patch("/deals/{deal_id}", response_model=Deal)
async def update_deal(
    deal_id: UUID,
    payload: DealPatch,
    user: CurrentUser = Depends(get_current_user),
) -> Deal:
    if "stage_id" in payload.model_fields_set:
        raise HTTPException(
            400,
            "Die Stufe wird über /deals/{id}/stage verschoben — dort wird der Wechsel protokolliert.",
        )
    try:
        zuweisungen, args = build_update(payload)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    args.append(deal_id)

    async with acquire_as(user.user_id) as conn:
        updated = await conn.fetchval(
            f"update public.deals set {zuweisungen} "
            f"where id = ${len(args)} and deleted_at is null returning id",
            *args,
        )
        if updated is None:
            raise HTTPException(404, "Deal nicht gefunden")
        await audit.log_fuer(
            conn,
            user,
            action="update",
            entity="deals",
            entity_id=deal_id,
            diff=payload.model_dump(mode="json", exclude_unset=True),
        )
        row = await conn.fetchrow(DEAL_SQL + " and d.id = $1", deal_id)
    return Deal(**{**dict(row), "probability": float(row["probability"])})


@router.post("/deals/{deal_id}/stage", response_model=Deal)
async def move_stage(
    deal_id: UUID,
    move: StageMove,
    user: CurrentUser = Depends(get_current_user),
) -> Deal:
    """Stufenwechsel — der einzige Weg, `stage_id` zu ändern.

    Er hinterlässt eine Aktivität. Ohne die wäre in der Zeitleiste eines
    Deals nicht mehr zu sehen, wann er wohin gewandert ist, und genau das
    ist die Frage, die im Vertrieb ständig gestellt wird.
    """
    async with acquire_as(user.user_id) as conn:
        alt = await conn.fetchrow(
            "select d.stage_id, s.name as stage_name, d.pipeline_id "
            "from public.deals d join public.pipeline_stages s on s.id = d.stage_id "
            "where d.id = $1 and d.deleted_at is null",
            deal_id,
        )
        if alt is None:
            raise HTTPException(404, "Deal nicht gefunden")

        neu = await conn.fetchrow(
            "select id, name, kind from public.pipeline_stages where id = $1 and pipeline_id = $2",
            move.stage_id,
            alt["pipeline_id"],
        )
        if neu is None:
            raise HTTPException(400, "Die Stufe gehört nicht zu dieser Pipeline")

        # closed_at setzt die Datenbank nicht selbst: „geschlossen" ist eine
        # fachliche Aussage über die Art der Stufe, kein Zeitstempel-Trigger.
        geschlossen = neu["kind"] in ("won", "lost")
        await conn.execute(
            """
            update public.deals
               set stage_id = $1,
                   closed_at = case when $2 then now() else null end,
                   lost_reason = case when $3 then $4 else null end
             where id = $5
            """,
            move.stage_id,
            geschlossen,
            neu["kind"] == "lost",
            move.lost_reason,
            deal_id,
        )
        await conn.execute(
            """
            insert into public.activities (org_id, kind, subject, deal_id, payload, created_by)
            values ($1, 'stage_change', $2, $3, $4::jsonb, $5)
            """,
            user.org_id,
            f"{alt['stage_name']} → {neu['name']}",
            deal_id,
            # Als Parameter, nicht als zusammengebauter Text: ein Stufenname
            # mit Anführungszeichen würde das JSON sonst zerreißen.
            orjson.dumps({"von": alt["stage_name"], "nach": neu["name"]}).decode(),
            user.user_id,
        )
        await audit.log_fuer(
            conn,
            user,
            action="update",
            entity="deals",
            entity_id=deal_id,
            diff={"stage": [str(alt["stage_id"]), str(move.stage_id)]},
        )
        row = await conn.fetchrow(DEAL_SQL + " and d.id = $1", deal_id)
    return Deal(**{**dict(row), "probability": float(row["probability"])})


@router.delete("/deals/{deal_id}", status_code=204)
async def delete_deal(deal_id: UUID, user: CurrentUser = Depends(get_current_user)) -> None:
    async with acquire_as(user.user_id) as conn:
        deleted = await conn.fetchval(
            "update public.deals set deleted_at = now() "
            "where id = $1 and deleted_at is null returning id",
            deal_id,
        )
        if deleted is None:
            raise HTTPException(404, "Deal nicht gefunden")
        await audit.log_fuer(
            conn,
            user,
            action="delete",
            entity="deals",
            entity_id=deal_id,
        )
