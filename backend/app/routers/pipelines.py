"""Pipelines und ihre Stufen — anlegen, ändern, löschen.

Mehrere Pipelines nebeneinander: Neugeschäft und Bestandskunden laufen
anders, und ein Board, das beides in denselben Spalten zeigt, zeigt
keines richtig. Die Stufen sind Datensätze, keine Aufzählung — der
Vertrieb ändert seinen Ablauf öfter, als wir migrieren wollen.

Zwei Regeln, die das Löschen hart machen: Eine Stufe mit Geschäften
darauf verschwindet nur, wenn gesagt wird, wohin sie sollen. Und die
Standard-Pipeline ist die, in der neue Geschäfte ohne Angabe landen —
genau eine, immer.
"""

from uuid import UUID

import orjson
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app import audit
from app.auth import CurrentUser, get_current_user
from app.db import acquire_as
from app.schemas import StageKind


def _leads(anzahl: int) -> str:
    """„1 Lead" oder „3 Leads" — die Zahl bestimmt das Wort.

    An einer Fehlermeldung fällt ein falscher Plural besonders auf:
    Sie ist ohnehin schon eine schlechte Nachricht.
    """
    return f"{anzahl} Lead" if anzahl == 1 else f"{anzahl} Leads"


router = APIRouter(prefix="/api/pipelines", tags=["pipelines"])


class PipelineIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    is_default: bool = False
    # Mit Stufen anlegen — eine Pipeline ohne Stufen kann kein Geschäft
    # aufnehmen, also gibt es beim Anlegen gleich welche.
    stages: list["StageIn"] = []


class PipelinePatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    is_default: bool | None = None
    position: int | None = None


class StageIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    kind: StageKind = "open"
    probability: float = Field(default=0.1, ge=0, le=1)
    position: int | None = None


class StagePatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    kind: StageKind | None = None
    probability: float | None = Field(default=None, ge=0, le=1)
    position: int | None = None


class Reihenfolge(BaseModel):
    stage_ids: list[UUID]


class Loeschziel(BaseModel):
    # Wohin die Geschäfte sollen, die noch auf der Stufe liegen.
    ziel_stage_id: UUID | None = None


STANDARD_STUFEN = [
    ("Erstkontakt", "open", 0.05), ("Qualifiziert", "open", 0.2), ("Angebot", "open", 0.6),
    ("Gewonnen", "won", 1.0), ("Verloren", "lost", 0.0),
]


async def _standard_setzen(conn, org_id: UUID, pipeline_id: UUID) -> None:
    """Genau eine Standard-Pipeline: erst alle aus, dann diese an."""
    await conn.execute("update public.pipelines set is_default = false where org_id = $1", org_id)
    await conn.execute("update public.pipelines set is_default = true where id = $1", pipeline_id)


@router.post("", status_code=201)
async def anlegen(payload: PipelineIn, user: CurrentUser = Depends(get_current_user)) -> dict:
    async with acquire_as(user.user_id) as conn:
        anzahl = await conn.fetchval(
            "select count(*) from public.pipelines where org_id = $1 and deleted_at is null", user.org_id
        )
        pid = await conn.fetchval(
            "insert into public.pipelines (org_id, name, is_default, position) values ($1,$2,false,$3) returning id",
            user.org_id, payload.name.strip(), anzahl,
        )
        stufen = [(s.name, s.kind, s.probability) for s in payload.stages] or STANDARD_STUFEN
        for pos, (name, kind, wahrscheinlichkeit) in enumerate(stufen):
            await conn.execute(
                "insert into public.pipeline_stages (org_id, pipeline_id, name, kind, probability, position) "
                "values ($1,$2,$3,$4::public.stage_kind,$5,$6)",
                user.org_id, pid, name, kind, wahrscheinlichkeit, pos,
            )
        if payload.is_default or anzahl == 0:
            await _standard_setzen(conn, user.org_id, pid)
        await audit.log_fuer(conn, user, action="create", entity="pipelines", entity_id=pid,
                             diff={"name": payload.name, "stufen": len(stufen)})
    return {"id": str(pid)}


@router.patch("/{pipeline_id}")
async def aendern(pipeline_id: UUID, payload: PipelinePatch, user: CurrentUser = Depends(get_current_user)) -> dict:
    felder = payload.model_dump(exclude_unset=True)
    if not felder:
        raise HTTPException(400, "Keine Änderung übergeben")
    async with acquire_as(user.user_id) as conn:
        da = await conn.fetchval(
            "select id from public.pipelines where id = $1 and deleted_at is null", pipeline_id
        )
        if da is None:
            raise HTTPException(404, "Pipeline nicht gefunden")
        for name, wert in felder.items():
            if name == "is_default":
                if wert:
                    await _standard_setzen(conn, user.org_id, pipeline_id)
                else:
                    raise HTTPException(400, "Es gibt immer genau eine Standard-Pipeline — wählen Sie eine andere als Standard.")
                continue
            await conn.execute(f"update public.pipelines set {name} = $1 where id = $2", wert, pipeline_id)
        await audit.log_fuer(conn, user, action="update", entity="pipelines", entity_id=pipeline_id, diff=felder)
    return {"id": str(pipeline_id)}


@router.delete("/{pipeline_id}", status_code=204)
async def loeschen(pipeline_id: UUID, user: CurrentUser = Depends(get_current_user)) -> None:
    """Weich. Nur ohne Geschäfte — auch nicht ohne gewonnene: Die
    Geschichte eines Abschlusses hängt an seiner Stufe."""
    async with acquire_as(user.user_id) as conn:
        pl = await conn.fetchrow(
            "select is_default from public.pipelines where id = $1 and deleted_at is null", pipeline_id
        )
        if pl is None:
            raise HTTPException(404, "Pipeline nicht gefunden")
        geschaefte = await conn.fetchval(
            "select count(*) from public.deals where pipeline_id = $1 and deleted_at is null", pipeline_id
        )
        if geschaefte:
            raise HTTPException(409, f"Auf dieser Pipeline liegen noch {_leads(geschaefte)}. Verschieben Sie sie zuerst.")
        andere = await conn.fetchval(
            "select count(*) from public.pipelines where org_id = $1 and deleted_at is null and id <> $2",
            user.org_id, pipeline_id,
        )
        if not andere:
            raise HTTPException(409, "Die letzte Pipeline lässt sich nicht löschen.")
        await conn.execute("update public.pipelines set deleted_at = now(), is_default = false where id = $1", pipeline_id)
        if pl["is_default"]:
            neu = await conn.fetchval(
                "select id from public.pipelines where org_id = $1 and deleted_at is null order by position limit 1", user.org_id
            )
            await _standard_setzen(conn, user.org_id, neu)
        await audit.log_fuer(conn, user, action="delete", entity="pipelines", entity_id=pipeline_id)


# ── Stufen ──────────────────────────────────────────────────────────────

@router.post("/{pipeline_id}/stages", status_code=201)
async def stufe_anlegen(pipeline_id: UUID, payload: StageIn, user: CurrentUser = Depends(get_current_user)) -> dict:
    async with acquire_as(user.user_id) as conn:
        da = await conn.fetchval("select id from public.pipelines where id = $1 and deleted_at is null", pipeline_id)
        if da is None:
            raise HTTPException(404, "Pipeline nicht gefunden")
        position = payload.position
        if position is None:
            # Vor die erste Abschlussstufe, nicht ans Ende: Eine neue offene
            # Stufe hinter „Gewonnen" wäre ein Board, das niemand versteht.
            position = await conn.fetchval(
                "select coalesce(min(position), (select coalesce(max(position),-1)+1 from public.pipeline_stages where pipeline_id = $1)) "
                "from public.pipeline_stages where pipeline_id = $1 and kind <> 'open'",
                pipeline_id,
            ) if payload.kind == "open" else await conn.fetchval(
                "select coalesce(max(position),-1)+1 from public.pipeline_stages where pipeline_id = $1", pipeline_id
            )
            await conn.execute(
                "update public.pipeline_stages set position = position + 1 where pipeline_id = $1 and position >= $2",
                pipeline_id, position,
            )
        sid = await conn.fetchval(
            "insert into public.pipeline_stages (org_id, pipeline_id, name, kind, probability, position) "
            "values ($1,$2,$3,$4::public.stage_kind,$5,$6) returning id",
            user.org_id, pipeline_id, payload.name.strip(), payload.kind, payload.probability, position,
        )
        await audit.log_fuer(conn, user, action="create", entity="pipeline_stages", entity_id=sid,
                             diff={"name": payload.name, "pipeline": str(pipeline_id)})
    return {"id": str(sid)}


@router.patch("/stages/{stage_id}")
async def stufe_aendern(stage_id: UUID, payload: StagePatch, user: CurrentUser = Depends(get_current_user)) -> dict:
    felder = payload.model_dump(exclude_unset=True)
    if not felder:
        raise HTTPException(400, "Keine Änderung übergeben")
    async with acquire_as(user.user_id) as conn:
        alt = await conn.fetchrow("select kind, pipeline_id from public.pipeline_stages where id = $1", stage_id)
        if alt is None:
            raise HTTPException(404, "Stufe nicht gefunden")
        if "kind" in felder and felder["kind"] != alt["kind"]:
            # Die Art einer Stufe entscheidet, ob ein Geschäft darauf als
            # offen oder abgeschlossen zählt. Mit Geschäften darauf ändert
            # sich damit rückwirkend die Prognose — das bleibt verboten.
            liegen = await conn.fetchval(
                "select count(*) from public.deals where stage_id = $1 and deleted_at is null", stage_id
            )
            if liegen:
                raise HTTPException(409, f"Auf dieser Stufe liegen {_leads(liegen)} — ihre Art lässt sich nicht mehr ändern.")
        for name, wert in felder.items():
            cast = "::public.stage_kind" if name == "kind" else ""
            await conn.execute(f"update public.pipeline_stages set {name} = $1{cast} where id = $2", wert, stage_id)
        await audit.log_fuer(conn, user, action="update", entity="pipeline_stages", entity_id=stage_id, diff=felder)
    return {"id": str(stage_id)}


@router.put("/{pipeline_id}/stages/reihenfolge")
async def reihenfolge(pipeline_id: UUID, payload: Reihenfolge, user: CurrentUser = Depends(get_current_user)) -> dict:
    async with acquire_as(user.user_id) as conn:
        vorhanden = {z["id"] for z in await conn.fetch(
            "select id from public.pipeline_stages where pipeline_id = $1", pipeline_id)}
        if set(payload.stage_ids) != vorhanden:
            raise HTTPException(400, "Die Reihenfolge muss genau alle Stufen dieser Pipeline nennen.")
        for pos, sid in enumerate(payload.stage_ids):
            await conn.execute("update public.pipeline_stages set position = $1 where id = $2", pos, sid)
    return {"ok": True}


@router.post("/stages/{stage_id}/loeschen", status_code=204)
async def stufe_loeschen(stage_id: UUID, payload: Loeschziel, user: CurrentUser = Depends(get_current_user)) -> None:
    """POST statt DELETE, weil ein Ziel mitkommt: Geschäfte, die noch auf
    der Stufe liegen, wandern dorthin — und das steht bei jedem im Verlauf."""
    async with acquire_as(user.user_id) as conn:
        stufe = await conn.fetchrow("select name, pipeline_id from public.pipeline_stages where id = $1", stage_id)
        if stufe is None:
            raise HTTPException(404, "Stufe nicht gefunden")
        uebrige = await conn.fetchval(
            "select count(*) from public.pipeline_stages where pipeline_id = $1 and id <> $2", stufe["pipeline_id"], stage_id
        )
        if not uebrige:
            raise HTTPException(409, "Die letzte Stufe einer Pipeline lässt sich nicht löschen.")

        geschaefte = await conn.fetch(
            "select id from public.deals where stage_id = $1 and deleted_at is null", stage_id
        )
        if geschaefte:
            if payload.ziel_stage_id is None:
                raise HTTPException(409, f"Auf „{stufe['name']}“ liegen {_leads(len(geschaefte))}. Geben Sie an, wohin sie sollen.")
            ziel = await conn.fetchrow(
                "select name, kind from public.pipeline_stages where id = $1 and pipeline_id = $2",
                payload.ziel_stage_id, stufe["pipeline_id"],
            )
            if ziel is None:
                raise HTTPException(400, "Die Zielstufe gehört nicht zu dieser Pipeline.")
            geschlossen = ziel["kind"] in ("won", "lost")
            for g in geschaefte:
                await conn.execute(
                    "update public.deals set stage_id = $1, closed_at = case when $2 then coalesce(closed_at, now()) else null end where id = $3",
                    payload.ziel_stage_id, geschlossen, g["id"],
                )
                await conn.execute(
                    "insert into public.activities (org_id, kind, subject, deal_id, payload, created_by) "
                    "values ($1, 'stage_change', $2, $3, $4::jsonb, $5)",
                    user.org_id, f"{stufe['name']} → {ziel['name']} (Stufe gelöscht)", g["id"],
                    orjson.dumps({"von": stufe["name"], "nach": ziel["name"], "grund": "Stufe gelöscht"}).decode(),
                    user.user_id,
                )
        await conn.execute("delete from public.pipeline_stages where id = $1", stage_id)
        await audit.log_fuer(conn, user, action="delete", entity="pipeline_stages", entity_id=stage_id,
                             diff={"name": stufe["name"], "verschoben": len(geschaefte)})
