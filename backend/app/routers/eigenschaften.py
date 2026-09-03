"""Definitionen eigener Eigenschaften — anlegen, ändern, abschalten."""

import json
from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app import audit, eigenschaften
from app.auth import CurrentUser, get_current_user
from app.db import acquire_as

router = APIRouter(prefix="/api/eigenschaften", tags=["eigenschaften"])

Entity = Literal["companies", "contacts", "deals"]
Kind = Literal["text", "number", "date", "bool", "select"]


class DefinitionIn(BaseModel):
    entity: Entity
    label: str = Field(min_length=1, max_length=80)
    kind: Kind = "text"
    options: list[str] = []
    description: str | None = None
    position: int = 0


class DefinitionPatch(BaseModel):
    label: str | None = Field(default=None, min_length=1, max_length=80)
    options: list[str] | None = None
    description: str | None = None
    position: int | None = None
    is_active: bool | None = None


class Definition(BaseModel):
    id: UUID
    entity: str
    key: str
    label: str
    kind: str
    options: list[str] = []
    description: str | None = None
    position: int
    is_active: bool
    created_at: datetime


def _aus_zeile(z: Any) -> Definition:
    d = dict(z)
    d["options"] = eigenschaften._optionen(d.get("options"))
    return Definition(**d)


@router.get("", response_model=list[Definition])
async def liste(
    user: CurrentUser = Depends(get_current_user),
    entity: Entity | None = Query(None),
    auch_inaktive: bool = Query(False),
) -> list[Definition]:
    sql = "select * from public.property_definitions where true"
    args: list[Any] = []
    if entity:
        args.append(entity)
        sql += f" and entity = ${len(args)}"
    if not auch_inaktive:
        sql += " and is_active"
    sql += " order by entity, position, label"
    async with acquire_as(user.user_id) as conn:
        zeilen = await conn.fetch(sql, *args)
    return [_aus_zeile(z) for z in zeilen]


@router.post("", response_model=Definition, status_code=201)
async def anlegen(
    payload: DefinitionIn,
    user: CurrentUser = Depends(get_current_user),
) -> Definition:
    if payload.kind == "select" and not [o for o in payload.options if o.strip()]:
        raise HTTPException(400, "Eine Auswahl braucht mindestens einen erlaubten Wert.")
    key = eigenschaften.schluessel_aus(payload.label)

    async with acquire_as(user.user_id) as conn:
        belegt = await conn.fetchval(
            "select id from public.property_definitions "
            "where org_id = $1 and entity = $2 and key = $3",
            user.org_id, payload.entity, key,
        )
        if belegt:
            raise HTTPException(
                409, f"Für dieses Objekt gibt es schon eine Eigenschaft mit dem Schlüssel „{key}“."
            )
        zeile = await conn.fetchrow(
            """
            insert into public.property_definitions
              (org_id, entity, key, label, kind, options, description, position)
            values ($1,$2,$3,$4,$5::public.property_kind,$6::jsonb,$7,$8)
            returning *
            """,
            user.org_id, payload.entity, key, payload.label.strip(), payload.kind,
            json.dumps([o.strip() for o in payload.options if o.strip()]),
            payload.description, payload.position,
        )
        await audit.log_fuer(
            conn, user, action="create", entity="property_definitions", entity_id=zeile["id"],
            diff={"entity": payload.entity, "key": key, "kind": payload.kind},
        )
    return _aus_zeile(zeile)


@router.patch("/{definition_id}", response_model=Definition)
async def aendern(
    definition_id: UUID,
    payload: DefinitionPatch,
    user: CurrentUser = Depends(get_current_user),
) -> Definition:
    """Beschriftung, Auswahl, Reihenfolge, Schalter. Nie Typ oder Schlüssel:
    Beides hinge sonst von den Werten ab, die schon in den Datensätzen
    liegen — ein Datum, das zur Zahl wird, ist keine Änderung, sondern
    ein Bruch."""
    felder = payload.model_dump(exclude_unset=True)
    if not felder:
        raise HTTPException(400, "Keine Änderung übergeben")

    zuweisungen: list[str] = []
    args: list[Any] = []
    for name, wert in felder.items():
        if name == "options":
            wert = json.dumps([o.strip() for o in (wert or []) if o.strip()])
            args.append(wert)
            zuweisungen.append(f"options = ${len(args)}::jsonb")
        else:
            args.append(wert)
            zuweisungen.append(f"{name} = ${len(args)}")
    args.append(definition_id)

    async with acquire_as(user.user_id) as conn:
        zeile = await conn.fetchrow(
            f"update public.property_definitions set {', '.join(zuweisungen)} "
            f"where id = ${len(args)} returning *",
            *args,
        )
        if zeile is None:
            raise HTTPException(404, "Eigenschaft nicht gefunden")
        await audit.log_fuer(
            conn, user, action="update", entity="property_definitions",
            entity_id=definition_id, diff=felder,
        )
    return _aus_zeile(zeile)


@router.delete("/{definition_id}", status_code=204)
async def abschalten(definition_id: UUID, user: CurrentUser = Depends(get_current_user)) -> None:
    """Schaltet ab. Die Werte bleiben in den Datensätzen — ein Löschen, das
    sie mitnähme, wäre ein Datenverlust hinter einem harmlosen Knopf."""
    async with acquire_as(user.user_id) as conn:
        weg = await conn.fetchval(
            "update public.property_definitions set is_active = false where id = $1 returning id",
            definition_id,
        )
        if weg is None:
            raise HTTPException(404, "Eigenschaft nicht gefunden")
        await audit.log_fuer(
            conn, user, action="delete", entity="property_definitions", entity_id=definition_id
        )
