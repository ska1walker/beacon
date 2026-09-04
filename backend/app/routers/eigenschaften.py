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
Kind = Literal["text", "number", "date", "bool", "select", "multiselect"]
# Beide führen eine Optionsliste; nur die Anzahl gleichzeitiger Werte
# unterscheidet sie.
MIT_OPTIONEN = ("select", "multiselect")


class Option(BaseModel):
    """Eine wählbare Option — mit festem Wert und freier Beschriftung.

    `wert` ist das, was in den Datensätzen steht, und ändert sich nie.
    `text` ist das, was jemand liest, und darf sich jederzeit ändern.
    Wer beides gleichsetzt, kann eine Beschriftung nie wieder korrigieren,
    ohne die vorhandenen Werte zu entwerten — genau der Fehler, den
    HubSpot mit derselben Trennung vermeidet.

    `verborgen` ist archiviert: aus der Auswahl genommen, in den
    Datensätzen unverändert gültig.
    """

    wert: str = Field(default="", max_length=200)
    text: str = Field(min_length=1, max_length=200)
    verborgen: bool = False


def _optionen_aus(roh: Any) -> list[Option]:
    """Nimmt Texte oder Objekte entgegen und macht Optionen daraus.

    Die kurze Form (`["Nord", "Süd"]`) bleibt gültig: Ein Import oder ein
    schnell getippter Aufruf soll nicht an einer Objektform scheitern.
    Ein neuer Wert ohne `wert` bekommt seine Beschriftung als Wert — so
    wie HubSpot es bei „Add option" vorbelegt.
    """
    fertig: list[Option] = []
    for o in roh or []:
        if isinstance(o, str):
            if o.strip():
                fertig.append(Option(wert=o.strip(), text=o.strip()))
            continue
        opt = o if isinstance(o, Option) else Option(**o)
        text = opt.text.strip()
        if not text:
            continue
        fertig.append(Option(wert=(opt.wert.strip() or text), text=text, verborgen=opt.verborgen))
    return fertig


class DefinitionIn(BaseModel):
    entity: Entity
    label: str = Field(min_length=1, max_length=80)
    kind: Kind = "text"
    options: list[Option | str] = []
    description: str | None = None
    position: int = 0


class DefinitionPatch(BaseModel):
    label: str | None = Field(default=None, min_length=1, max_length=80)
    options: list[Option | str] | None = None
    description: str | None = None
    position: int | None = None
    is_active: bool | None = None


class Definition(BaseModel):
    id: UUID
    entity: str
    key: str
    label: str
    kind: str
    options: list[Option] = []
    description: str | None = None
    position: int
    is_active: bool
    created_at: datetime


def _aus_zeile(z: Any) -> Definition:
    d = dict(z)
    d["options"] = [Option(**o) for o in eigenschaften.optionen(d.get("options"))]
    return Definition(**d)


def _geprueft(optionen: list[Option], kind: str) -> list[Option]:
    """Eine Optionsliste, die eine Wahl ist: nicht leer, ohne Doppelte."""
    if kind in MIT_OPTIONEN and not optionen:
        raise HTTPException(400, "Eine Auswahl braucht mindestens einen erlaubten Wert.")
    werte = [o.wert for o in optionen]
    if len(werte) != len(set(werte)):
        raise HTTPException(400, "Zwei gleiche Werte in der Auswahl sind keine Wahl.")
    if kind in MIT_OPTIONEN and all(o.verborgen for o in optionen):
        raise HTTPException(
            400, "Alle Werte archiviert — dann bliebe an dieser Eigenschaft nichts zu wählen."
        )
    return optionen


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
    optionen = _geprueft(_optionen_aus(payload.options), payload.kind)
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
            json.dumps([o.model_dump() for o in optionen]),
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
            neue = _optionen_aus(wert)
            felder[name] = [o.model_dump() for o in neue]
            args.append(json.dumps(felder[name]))
            zuweisungen.append(f"options = ${len(args)}::jsonb")
        else:
            args.append(wert)
            zuweisungen.append(f"{name} = ${len(args)}")
    args.append(definition_id)

    async with acquire_as(user.user_id) as conn:
        if "options" in felder:
            await _optionen_pruefen(conn, definition_id, [Option(**o) for o in felder["options"]])
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


async def _optionen_pruefen(conn, definition_id: UUID, neu: list[Option]) -> None:
    """Was an der Optionsliste geändert werden darf — und was nicht.

    **Umbenennen: immer.** Die Beschriftung gehört der Oberfläche, der
    Wert den Datensätzen. Genau dafür sind es zwei Felder.

    **Archivieren: immer.** Ein archivierter Wert wird nicht mehr
    angeboten, bleibt aber gültig. Das ist der vorgesehene Weg, eine
    Option aus dem Verkehr zu ziehen.

    **Entfernen: nur, solange sie niemand benutzt.** Sonst bliebe der
    Wert zwar lesbar im JSON stehen, aber der Datensatz ließe sich nicht
    mehr speichern — die Prüfung lehnte ihn ab. Das ist die unangenehmste
    Sorte Fehler: Er entsteht in den Einstellungen und schlägt Wochen
    später bei jemand anderem an ganz anderer Stelle zu. Wer wirklich
    aufräumen will, archiviert.
    """
    d = await conn.fetchrow(
        "select entity, key, kind, options from public.property_definitions where id = $1",
        definition_id,
    )
    if d is None:
        raise HTTPException(404, "Eigenschaft nicht gefunden")
    if d["kind"] not in MIT_OPTIONEN:
        raise HTTPException(
            400, "Nur eine Auswahl oder Mehrfachauswahl führt eine Werteliste."
        )
    _geprueft(neu, d["kind"])

    bleibt = {o.wert for o in neu}
    entfernt = [o for o in eigenschaften.optionen(d["options"]) if o["wert"] not in bleibt]
    if not entfernt:
        return

    tabelle = {"companies": "companies", "contacts": "contacts", "deals": "deals"}[d["entity"]]
    for option in entfernt:
        # Ein einzelner Wert steht als jsonb-Text im Feld, eine
        # Mehrfachauswahl als Liste. `@>` trifft beide Formen.
        anzahl = await conn.fetchval(
            f"select count(*) from public.{tabelle} "
            f"where deleted_at is null and (custom -> $1) @> to_jsonb($2::text)",
            d["key"], option["wert"],
        )
        if anzahl:
            raise HTTPException(
                409,
                f"„{option['text']}“ steht noch an {anzahl} "
                f"{'Datensatz' if anzahl == 1 else 'Datensätzen'}. "
                "Archivieren Sie den Wert, statt ihn zu entfernen — dann wird er "
                "nicht mehr angeboten und bleibt dort trotzdem gültig.",
            )


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
