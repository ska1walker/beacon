"""Gespräch vorbereiten — Podcasts zu Firmen und Leads, Sprachausgabe einrichten."""

from typing import Any, Literal
from uuid import UUID

import httpx
import orjson
from fastapi import APIRouter, Depends, HTTPException, Response
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from app import podcast
from app.auth import CurrentUser, get_current_user
from app.db import acquire_as
from app.llm import load_llm_config

router = APIRouter(prefix="/api/podcasts", tags=["podcasts"])

Entity = Literal["companies", "deals"]


class Podcast(BaseModel):
    id: UUID
    entity: str
    entity_id: UUID
    task_id: UUID | None = None
    anlass: str | None = None
    titel: str | None = None
    status: str
    fortschritt: dict[str, Any]
    skript: str | None = None
    segmente: list[dict[str, str]]
    dauer_s: int | None = None
    bytes: int | None = None
    modell: str | None = None
    llm_modell: str | None = None
    fehler: str | None = None
    created_at: Any
    updated_at: Any
    # Nur in „heute": wozu die Folge gehört.
    name: str | None = None
    termin_titel: str | None = None
    termin_am: Any = None


class Status(BaseModel):
    llm_ready: bool
    tts_ready: bool
    hint: str = ""


class Auftrag(BaseModel):
    entity: Entity
    entity_id: UUID
    anlass: str | None = Field(default=None, max_length=300)


class Probe(BaseModel):
    sprecher: Literal["moderatorin", "kollege"] = "kollege"


class Einrichten(BaseModel):
    modell: str = Field(min_length=3, max_length=200, pattern=r"^[A-Za-z0-9_-]+(?:[./][A-Za-z0-9_-]+)*$")


def _js(v: Any) -> Any:
    return orjson.loads(v) if isinstance(v, str | bytes) else v


def _podcast(row: Any) -> Podcast:
    r = dict(row)
    return Podcast(
        id=r["id"], entity=r["entity"], entity_id=r["entity_id"], task_id=r["task_id"], anlass=r["anlass"],
        titel=r["titel"], status=r["status"], fortschritt=_js(r["fortschritt"]) or {}, skript=r["skript"],
        segmente=_js(r["segmente"]) or [], dauer_s=r["dauer_s"], bytes=r["bytes"], modell=r["modell"],
        llm_modell=r["llm_modell"], fehler=r["fehler"], created_at=r["created_at"], updated_at=r["updated_at"],
        name=r.get("name"), termin_titel=r.get("termin_titel"), termin_am=r.get("termin_am"),
    )


def _dienstfehler(exc: Exception, adresse: str) -> HTTPException:
    if isinstance(exc, podcast.TTSNichtEingerichtet):
        return HTTPException(409, str(exc))
    if isinstance(exc, httpx.HTTPStatusError):
        return HTTPException(502, f"Die Sprachausgabe hat mit {exc.response.status_code} geantwortet: {exc.response.text[:200]}")
    if isinstance(exc, httpx.RequestError):
        return HTTPException(502, f"Die Sprachausgabe {adresse} ist nicht erreichbar: {exc}")
    return HTTPException(502, f"{type(exc).__name__}: {exc}"[:300])


@router.get("/status", response_model=Status)
async def status(user: CurrentUser = Depends(get_current_user)) -> Status:
    async with acquire_as(user.user_id) as conn:
        cfg = await load_llm_config(conn, user.org_id)
        tts = await podcast.load_tts_config(conn, user.org_id)
    hint = ""
    if not cfg.eingerichtet:
        hint = "Kein Sprachmodell hinterlegt — ohne Modell entsteht kein Skript."
    elif not tts.eingerichtet:
        hint = "Keine Sprachausgabe hinterlegt. Die Adresse steht unter Einstellungen › KI und Programme."
    return Status(llm_ready=cfg.eingerichtet, tts_ready=tts.eingerichtet, hint=hint)


@router.get("", response_model=list[Podcast])
async def liste(entity: Entity, entity_id: UUID, user: CurrentUser = Depends(get_current_user)) -> list[Podcast]:
    async with acquire_as(user.user_id) as conn:
        rows = await conn.fetch(
            "select * from public.podcasts where org_id = $1 and entity = $2 and entity_id = $3 and deleted_at is null "
            "order by created_at desc limit 5",
            user.org_id, entity, entity_id,
        )
    return [_podcast(r) for r in rows]


@router.get("/heute", response_model=list[Podcast])
async def heute(user: CurrentUser = Depends(get_current_user)) -> list[Podcast]:
    """Folgen zu Terminen der nächsten 24 Stunden — und die von Hand
    erzeugten des heutigen Tages."""
    async with acquire_as(user.user_id) as conn:
        rows = await conn.fetch(
            """
            select p.*, coalesce(f.name, d.name) as name, t.title as termin_titel, t.due_at as termin_am
              from public.podcasts p
              left join public.tasks t on t.id = p.task_id
              left join public.companies f on p.entity = 'companies' and f.id = p.entity_id
              left join public.deals d on p.entity = 'deals' and d.id = p.entity_id
             where p.org_id = $1 and p.deleted_at is null and p.status = 'fertig'
               and ((t.due_at between now() - interval '2 hours' and now() + make_interval(hours => $2))
                    or (p.task_id is null and p.created_at > now() - interval '24 hours'))
             order by t.due_at nulls last, p.created_at desc
             limit 10
            """,
            user.org_id, podcast.STUNDEN_VORAUS,
        )
    return [_podcast(r) for r in rows]


@router.post("", response_model=Podcast, status_code=202)
async def erzeugen(payload: Auftrag, user: CurrentUser = Depends(get_current_user)) -> Podcast:
    async with acquire_as(user.user_id) as conn:
        cfg = await load_llm_config(conn, user.org_id)
        if not cfg.eingerichtet:
            raise HTTPException(409, "Es ist kein Sprachmodell hinterlegt. Ohne Modell entsteht kein Skript.")
        tts = await podcast.load_tts_config(conn, user.org_id)
        if not tts.eingerichtet:
            raise HTTPException(409, "Es ist keine Sprachausgabe hinterlegt. Die Adresse steht unter Einstellungen › KI und Programme.")
        da = await conn.fetchval(
            f"select exists (select 1 from public.{payload.entity} where id = $1 and deleted_at is null)",
            payload.entity_id,
        )
        if not da:
            raise HTTPException(404, "Firma oder Lead nicht gefunden")
        laeuft = await conn.fetchrow(
            "select id from public.podcasts where org_id = $1 and entity = $2 and entity_id = $3 and status = 'laeuft' "
            "and updated_at > now() - interval '15 minutes' and deleted_at is null limit 1",
            user.org_id, payload.entity, payload.entity_id,
        )
        if laeuft:
            raise HTTPException(409, "Eine Folge entsteht gerade.")
        row = await conn.fetchrow(
            "insert into public.podcasts (org_id, entity, entity_id, anlass, created_by, llm_modell, modell) "
            "values ($1, $2, $3, $4, $5, $6, $7) returning *",
            user.org_id, payload.entity, payload.entity_id, payload.anlass, user.user_id, cfg.model, tts.modell,
        )
    podcast.im_hintergrund(user, row["id"])
    return _podcast(row)


async def _zeile(conn: Any, user: CurrentUser, podcast_id: UUID) -> Any:
    row = await conn.fetchrow(
        "select * from public.podcasts where id = $1 and org_id = $2 and deleted_at is null", podcast_id, user.org_id
    )
    if row is None:
        raise HTTPException(404, "Podcast nicht gefunden")
    return row


@router.get("/stimmen")
async def stimmen(user: CurrentUser = Depends(get_current_user)) -> dict[str, Any]:
    async with acquire_as(user.user_id) as conn:
        tts = await podcast.load_tts_config(conn, user.org_id)
    if not tts.eingerichtet:
        raise HTTPException(409, "Keine Sprachausgabe hinterlegt.")
    try:
        return await podcast.modelle(tts)
    except Exception as exc:  # noqa: BLE001
        raise _dienstfehler(exc, tts.endpoint_url) from exc


@router.post("/stimmen/einrichten", status_code=202)
async def stimme_einrichten(payload: Einrichten, user: CurrentUser = Depends(get_current_user)) -> dict[str, str]:
    async with acquire_as(user.user_id) as conn:
        tts = await podcast.load_tts_config(conn, user.org_id)
    if not tts.eingerichtet:
        raise HTTPException(409, "Keine Sprachausgabe hinterlegt.")
    podcast.installieren(tts, payload.modell)
    return {"modell": payload.modell, "stand": podcast.INSTALLATIONEN.get(payload.modell, "laeuft")}


@router.post("/probe")
async def probe(payload: Probe, user: CurrentUser = Depends(get_current_user)) -> Response:
    async with acquire_as(user.user_id) as conn:
        tts = await podcast.load_tts_config(conn, user.org_id)
    if not tts.eingerichtet:
        raise HTTPException(409, "Keine Sprachausgabe hinterlegt.")
    try:
        daten = await podcast.probe(tts, payload.sprecher)
    except Exception as exc:  # noqa: BLE001
        raise _dienstfehler(exc, tts.endpoint_url) from exc
    return Response(content=daten, media_type="audio/mpeg")


@router.get("/{podcast_id}", response_model=Podcast)
async def einzeln(podcast_id: UUID, user: CurrentUser = Depends(get_current_user)) -> Podcast:
    async with acquire_as(user.user_id) as conn:
        return _podcast(await _zeile(conn, user, podcast_id))


@router.get("/{podcast_id}/audio")
async def audio(podcast_id: UUID, user: CurrentUser = Depends(get_current_user)) -> FileResponse:
    async with acquire_as(user.user_id) as conn:
        row = await _zeile(conn, user, podcast_id)
    pfad = podcast.datei_pfad(row["datei"])
    if row["status"] != "fertig" or pfad is None or not pfad.is_file():
        raise HTTPException(404, "Die Datei dieser Folge liegt nicht (mehr) auf der Box.")
    name = (row["titel"] or "podcast").replace('"', "")[:80] + ".mp3"
    return FileResponse(pfad, media_type="audio/mpeg", filename=name, content_disposition_type="inline")


@router.delete("/{podcast_id}", status_code=204)
async def loeschen(podcast_id: UUID, user: CurrentUser = Depends(get_current_user)) -> Response:
    async with acquire_as(user.user_id) as conn:
        row = await _zeile(conn, user, podcast_id)
        await conn.execute("update public.podcasts set deleted_at = now(), updated_at = now() where id = $1", podcast_id)
    podcast.datei_loeschen(row["datei"])
    return Response(status_code=204)


