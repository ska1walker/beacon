"""Gespeicherte Ansichten und die Felder, aus denen sie gebaut werden."""

from typing import Any, Literal
from uuid import UUID

import orjson
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app import audit, segmente
from app.auth import CurrentUser, get_current_user
from app.db import acquire_as

router = APIRouter(prefix="/api/ansichten", tags=["ansichten"])

Entity = Literal["companies", "contacts", "tickets"]


class Bedingung(BaseModel):
    feld: str
    operator: str
    wert: Any = None


class AnsichtIn(BaseModel):
    entity: Entity
    name: str = Field(min_length=1, max_length=80)
    filter: list[Bedingung] = []
    verknuepfung: Literal["und", "oder"] = "und"
    spalten: list[str] = []
    sort_feld: str | None = None
    sort_richtung: Literal["asc", "desc"] = "desc"
    # Wahr heißt „nur für mich“ — die Ansicht bekommt einen Besitzer.
    nur_ich: bool = False


class AnsichtPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    filter: list[Bedingung] | None = None
    verknuepfung: Literal["und", "oder"] | None = None
    spalten: list[str] | None = None
    sort_feld: str | None = None
    sort_richtung: Literal["asc", "desc"] | None = None
    position: int | None = None


class Ansicht(BaseModel):
    id: UUID
    entity: str
    name: str
    filter: list[Bedingung]
    verknuepfung: str
    spalten: list[str]
    sort_feld: str | None = None
    sort_richtung: str
    owner_id: UUID | None = None
    position: int


def _aus_zeile(row: dict[str, Any]) -> Ansicht:
    def js(wert: Any) -> Any:
        return orjson.loads(wert) if isinstance(wert, str) else wert

    return Ansicht(
        id=row["id"],
        entity=row["entity"],
        name=row["name"],
        filter=[Bedingung(**b) for b in js(row["filter"])],
        verknuepfung=row["verknuepfung"],
        spalten=js(row["spalten"]),
        sort_feld=row["sort_feld"],
        sort_richtung=row["sort_richtung"],
        owner_id=row["owner_id"],
        position=row["position"],
    )


def _pruefen(entity: str, bedingungen: list[Bedingung], spalten: list[str], sort_feld: str | None) -> None:
    """Wirft, bevor etwas gespeichert wird, das später nicht abfragbar ist.

    Eine Ansicht, die beim Öffnen einen Fehler wirft, ist schlimmer als
    eine, die gar nicht erst gespeichert wurde.
    """
    try:
        args: list[Any] = []
        segmente.filter_zu_sql(
            entity, [segmente.Bedingung(b.feld, b.operator, b.wert) for b in bedingungen], args
        )
        if sort_feld:
            segmente.sortierung_zu_sql(entity, sort_feld, "asc")
    except segmente.Ungueltig as exc:
        raise HTTPException(400, str(exc)) from exc

    erlaubt = {f.schluessel for f in segmente.FELDER[entity]}
    unbekannt = [
        s for s in spalten if s not in erlaubt and not s.startswith(segmente.CUSTOM_PRAEFIX)
    ]
    if unbekannt:
        raise HTTPException(400, f"Unbekannte Spalte: {', '.join(unbekannt)}")


@router.get("/felder")
async def felder(
    entity: Entity,
    user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    """Woraus sich Filter und Spalten bauen lassen — samt Vorgaben.

    Die Personen kommen mit: Ein Filter auf „Besitzer“ braucht Namen zur
    Auswahl, keine Kennungen.
    """
    async with acquire_as(user.user_id) as conn:
        liste = await segmente.felder_fuer(conn, entity)
        personen = await conn.fetch(
            """
            select u.id, coalesce(u.display_name, u.olares_username) as name
            from public.users u
            join public.user_org_roles r on r.user_id = u.id
            where r.org_id = $1 and u.deleted_at is null
            order by name
            """,
            user.org_id,
        )
    return {
        "felder": liste,
        "personen": [{"id": str(p["id"]), "name": p["name"]} for p in personen],
        "vorgabe_spalten": segmente.VORGABE_SPALTEN[entity],
        "vorgabe_sortierung": segmente.VORGABE_SORTIERUNG,
    }


@router.get("", response_model=list[Ansicht])
async def liste(
    entity: Entity,
    user: CurrentUser = Depends(get_current_user),
) -> list[Ansicht]:
    """Alle Ansichten, die für diese Person gelten.

    Geteilte (ohne Besitzer) und die eigenen — fremde private nicht. Sie
    stehen in derselben Organisation und wären lesbar, aber in der Leiste
    hätten sie nichts verloren.
    """
    async with acquire_as(user.user_id) as conn:
        rows = await conn.fetch(
            """
            select * from public.ansichten
            where entity = $1 and deleted_at is null
              and (owner_id is null or owner_id = $2)
            order by position, created_at
            """,
            entity,
            user.user_id,
        )
    return [_aus_zeile(dict(r)) for r in rows]


@router.post("", response_model=Ansicht, status_code=201)
async def anlegen(payload: AnsichtIn, user: CurrentUser = Depends(get_current_user)) -> Ansicht:
    _pruefen(payload.entity, payload.filter, payload.spalten, payload.sort_feld)

    async with acquire_as(user.user_id) as conn:
        naechste = await conn.fetchval(
            "select coalesce(max(position), -1) + 1 from public.ansichten "
            "where org_id = $1 and entity = $2 and deleted_at is null",
            user.org_id,
            payload.entity,
        )
        row = await conn.fetchrow(
            """
            insert into public.ansichten
              (org_id, entity, name, filter, verknuepfung, spalten, sort_feld, sort_richtung,
               owner_id, position, created_by)
            values ($1,$2,$3,$4::jsonb,$5,$6::jsonb,$7,$8,$9,$10,$11)
            returning *
            """,
            user.org_id,
            payload.entity,
            payload.name.strip(),
            orjson.dumps([b.model_dump() for b in payload.filter]).decode(),
            payload.verknuepfung,
            orjson.dumps(payload.spalten).decode(),
            payload.sort_feld,
            payload.sort_richtung,
            user.user_id if payload.nur_ich else None,
            naechste,
            user.user_id,
        )
        await audit.log_fuer(
            conn, user, action="create", entity="ansichten", entity_id=row["id"],
            diff={"name": payload.name, "entity": payload.entity},
        )
    return _aus_zeile(dict(row))


@router.patch("/{ansicht_id}", response_model=Ansicht)
async def aendern(
    ansicht_id: UUID,
    payload: AnsichtPatch,
    user: CurrentUser = Depends(get_current_user),
) -> Ansicht:
    felder = payload.model_dump(exclude_unset=True)
    if not felder:
        raise HTTPException(400, "Keine Änderung übergeben")

    async with acquire_as(user.user_id) as conn:
        vorhanden = await conn.fetchrow(
            "select * from public.ansichten where id = $1 and deleted_at is null", ansicht_id
        )
        if vorhanden is None:
            raise HTTPException(404, "Ansicht nicht gefunden")

        entity = vorhanden["entity"]
        bedingungen = payload.filter if payload.filter is not None else [
            Bedingung(**b) for b in (orjson.loads(vorhanden["filter"]) if isinstance(vorhanden["filter"], str) else vorhanden["filter"])
        ]
        spalten = payload.spalten if payload.spalten is not None else []
        _pruefen(entity, bedingungen, spalten, payload.sort_feld or vorhanden["sort_feld"])

        zuweisungen: list[str] = []
        args: list[Any] = []
        for name, wert in felder.items():
            if name == "filter":
                args.append(orjson.dumps([b.model_dump() for b in payload.filter or []]).decode())
                zuweisungen.append(f"filter = ${len(args)}::jsonb")
            elif name == "spalten":
                args.append(orjson.dumps(payload.spalten or []).decode())
                zuweisungen.append(f"spalten = ${len(args)}::jsonb")
            elif name == "name":
                args.append(str(wert).strip())
                zuweisungen.append(f"name = ${len(args)}")
            else:
                args.append(wert)
                zuweisungen.append(f"{name} = ${len(args)}")
        args.append(ansicht_id)

        row = await conn.fetchrow(
            f"update public.ansichten set {', '.join(zuweisungen)}, updated_at = now() "
            f"where id = ${len(args)} and deleted_at is null returning *",
            *args,
        )
        await audit.log_fuer(
            conn, user, action="update", entity="ansichten", entity_id=ansicht_id, diff=felder
        )
    return _aus_zeile(dict(row))


@router.delete("/{ansicht_id}", status_code=204)
async def loeschen(ansicht_id: UUID, user: CurrentUser = Depends(get_current_user)) -> None:
    async with acquire_as(user.user_id) as conn:
        weg = await conn.fetchval(
            "update public.ansichten set deleted_at = now() "
            "where id = $1 and deleted_at is null returning id",
            ansicht_id,
        )
        if weg is None:
            raise HTTPException(404, "Ansicht nicht gefunden")
        await audit.log_fuer(
            conn, user, action="delete", entity="ansichten", entity_id=ansicht_id
        )
