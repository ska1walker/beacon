"""Kontakte."""

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

import orjson
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from app import anreicherung, audit, segmente, versand
from app.auth import CurrentUser, get_current_user
from app.db import acquire_as
from app.patching import build_update
from app.schemas import Contact, ContactIn, ContactPatch

router = APIRouter(prefix="/api/contacts", tags=["contacts"])

LIST_SQL = """
select k.*, f.name as company_name
from public.contacts k
left join public.companies f on f.id = k.company_id
where k.deleted_at is null
"""


async def _custom_pruefen(conn, entity: str, werte: dict | None) -> str:
    """Prüft eigene Eigenschaften gegen ihre Definition, gibt JSON zurück."""
    import json

    from app import eigenschaften

    try:
        geprueft = eigenschaften.pruefen(werte or {}, await eigenschaften.definitionen(conn, entity))
    except eigenschaften.Ungueltig as exc:
        raise HTTPException(400, str(exc)) from exc
    return json.dumps(geprueft)


def _bedingungen(sql: str, args: list[Any], q: str | None, company_id: UUID | None, filter: str | None) -> str:
    """Freitext, Firmenbezug und das Segment — in dieser Reihenfolge."""
    if q:
        args.append(f"%{q}%")
        n = len(args)
        sql += (
            f" and (coalesce(k.first_name,'') || ' ' || coalesce(k.last_name,'') ilike ${n}"
            f" or k.email ilike ${n} or f.name ilike ${n})"
        )
    if company_id:
        args.append(company_id)
        # Hauptfirma oder weitere Verknüpfung — die Firmenseite soll beide zeigen.
        sql += (
            f" and (k.company_id = ${len(args)} or exists ("
            f"select 1 from public.contact_companies v where v.contact_id = k.id and v.company_id = ${len(args)}))"
        )
    if filter:
        try:
            bedingungen = segmente.bedingungen_aus(orjson.loads(filter))
            sql += segmente.filter_zu_sql("contacts", bedingungen, args)
        except (orjson.JSONDecodeError, segmente.Ungueltig) as exc:
            raise HTTPException(400, f"Filter nicht verwendbar: {exc}") from exc
    return sql


def abfrage_sql(
    args: list[Any], q: str | None, filter: str | None,
    sort: str | None, richtung: str | None, company_id: UUID | None = None,
) -> str:
    """Die vollständige Abfrage ohne `limit` — Liste, Zählung und Ausfuhr.

    Die Ausfuhr soll exakt das liefern, was die Tabelle zeigt. Ein
    zweiter Filterbauer daneben wäre die Stelle, an der beide
    auseinanderlaufen, ohne dass es jemand merkt.
    """
    sql = _bedingungen(LIST_SQL, args, q, company_id, filter)
    try:
        return sql + segmente.sortierung_zu_sql("contacts", sort, richtung)
    except segmente.Ungueltig as exc:
        raise HTTPException(400, str(exc)) from exc


async def einfuegen(conn, user: CurrentUser, payload: ContactIn, custom_json: str) -> UUID:
    """Legt einen Kontakt an und protokolliert es. Ohne Anreicherung.

    Der Endpunkt stößt danach die Anreicherung an, die Einfuhr nicht:
    Fünftausend Hintergrundläufe gegen Suchdienst und Sprachmodell wären
    ein Selbst-DoS und eine Rechnung. `custom_json` kommt fertig geprüft
    herein, damit ein Import die Definitionen einmal lädt und nicht je
    Zeile.
    """
    new_id = await conn.fetchval(
        """
        insert into public.contacts
          (org_id, company_id, first_name, last_name, email, phone, mobile, job_title,
           buying_role, linkedin_url, lifecycle_stage, source, notes, owner_id, created_by,
           custom)
        values ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11::public.lifecycle_stage,$12,$13,$14,$15,
                $16::jsonb)
        returning id
        """,
        user.org_id,
        payload.company_id,
        payload.first_name,
        payload.last_name,
        str(payload.email) if payload.email else None,
        payload.phone,
        payload.mobile,
        payload.job_title,
        payload.buying_role,
        payload.linkedin_url,
        payload.lifecycle_stage,
        payload.source,
        payload.notes,
        payload.owner_id or user.user_id,
        user.user_id,
        custom_json,
    )
    await audit.log_fuer(
        conn, user, action="create", entity="contacts", entity_id=new_id,
        diff=payload.model_dump(mode="json"),
    )
    return new_id


@router.get("", response_model=list[Contact])
async def list_contacts(
    user: CurrentUser = Depends(get_current_user),
    q: str | None = Query(None),
    company_id: UUID | None = Query(None),
    filter: str | None = Query(None, description="Bedingungen als JSON-Liste"),
    sort: str | None = Query(None),
    richtung: str | None = Query(None),
    limit: int = Query(50, le=200),
    offset: int = Query(0, ge=0),
) -> list[Contact]:
    args: list[Any] = []
    sql = abfrage_sql(args, q, filter, sort, richtung, company_id)
    args.extend([limit, offset])
    sql += f" limit ${len(args) - 1} offset ${len(args)}"

    async with acquire_as(user.user_id) as conn:
        rows = await conn.fetch(sql, *args)
    return [Contact(**dict(r)) for r in rows]


@router.get("/anzahl")
async def anzahl_contacts(
    user: CurrentUser = Depends(get_current_user),
    q: str | None = Query(None),
    company_id: UUID | None = Query(None),
    filter: str | None = Query(None),
) -> dict[str, int]:
    """Wie viele es insgesamt sind — die Liste selbst ist begrenzt.

    „50 Einträge“ wäre gelogen, wenn 312 gemeint sind; und eine
    Segmentierung ohne Gesamtzahl beantwortet die Frage nicht, für die
    man sie gebaut hat.
    """
    args: list[Any] = []
    sql = _bedingungen(
        "select count(*) from public.contacts k "
        "left join public.companies f on f.id = k.company_id "
        "where k.deleted_at is null",
        args, q, company_id, filter,
    )
    async with acquire_as(user.user_id) as conn:
        return {"anzahl": await conn.fetchval(sql, *args) or 0}


class Stapel(BaseModel):
    ids: list[UUID]


class StapelAenderung(Stapel):
    lifecycle_stage: str | None = None
    owner_id: UUID | None = None
    source: str | None = None


@router.post("/mehrere")
async def mehrere_aendern(
    payload: StapelAenderung,
    user: CurrentUser = Depends(get_current_user),
) -> dict[str, int]:
    """Setzt ein Feld an vielen Kontakten auf einmal.

    Nur drei Felder: Stufe, Besitzer, Herkunft. Ein Stapel, der alles
    ändern kann, ändert irgendwann versehentlich alles — und diese drei
    sind es, die man nach einer Messe oder einem Import wirklich in einem
    Zug setzt.
    """
    if not payload.ids:
        raise HTTPException(400, "Keine Kontakte gewählt")
    if len(payload.ids) > 500:
        raise HTTPException(400, "Höchstens 500 auf einmal")

    felder = payload.model_dump(exclude_unset=True, exclude={"ids"})
    if not felder:
        raise HTTPException(400, "Keine Änderung übergeben")

    zuweisungen: list[str] = []
    args: list[Any] = []
    for name, wert in felder.items():
        args.append(wert)
        guss = "::public.lifecycle_stage" if name == "lifecycle_stage" else ""
        zuweisungen.append(f"{name} = ${len(args)}{guss}")
    args.append(payload.ids)

    async with acquire_as(user.user_id) as conn:
        rows = await conn.fetch(
            f"update public.contacts set {', '.join(zuweisungen)}, updated_at = now() "
            f"where id = any(${len(args)}::uuid[]) and deleted_at is null returning id",
            *args,
        )
        for r in rows:
            await audit.log_fuer(
                conn, user, action="update", entity="contacts", entity_id=r["id"], diff=felder
            )
    return {"geaendert": len(rows)}


@router.post("/mehrere/loeschen")
async def mehrere_loeschen(
    payload: Stapel,
    user: CurrentUser = Depends(get_current_user),
) -> dict[str, int]:
    if not payload.ids:
        raise HTTPException(400, "Keine Kontakte gewählt")
    async with acquire_as(user.user_id) as conn:
        rows = await conn.fetch(
            "update public.contacts set deleted_at = now() "
            "where id = any($1::uuid[]) and deleted_at is null returning id",
            payload.ids,
        )
        for r in rows:
            await audit.log_fuer(conn, user, action="delete", entity="contacts", entity_id=r["id"])
    return {"geloescht": len(rows)}


@router.get("/{contact_id}", response_model=Contact)
async def get_contact(
    contact_id: UUID,
    user: CurrentUser = Depends(get_current_user),
) -> Contact:
    async with acquire_as(user.user_id) as conn:
        row = await conn.fetchrow(LIST_SQL + " and k.id = $1", contact_id)
    if row is None:
        raise HTTPException(404, "Kontakt nicht gefunden")
    return Contact(**dict(row))


@router.post("", response_model=Contact, status_code=201)
async def create_contact(
    payload: ContactIn,
    user: CurrentUser = Depends(get_current_user),
) -> Contact:
    async with acquire_as(user.user_id) as conn:
        new_id = await einfuegen(
            conn, user, payload, await _custom_pruefen(conn, "contacts", payload.custom)
        )
        row = await conn.fetchrow(LIST_SQL + " and k.id = $1", new_id)
    anreicherung.im_hintergrund(user, "contacts", new_id)
    return Contact(**dict(row))


@router.patch("/{contact_id}", response_model=Contact)
async def update_contact(
    contact_id: UUID,
    payload: ContactPatch,
    user: CurrentUser = Depends(get_current_user),
) -> Contact:
    if "custom" in payload.model_fields_set:
        async with acquire_as(user.user_id) as conn:
            import json

            geprueft = json.loads(await _custom_pruefen(conn, "contacts", payload.custom))
        payload = payload.model_copy(update={"custom": geprueft})
    try:
        zuweisungen, args = build_update(payload)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    args.append(contact_id)

    async with acquire_as(user.user_id) as conn:
        updated = await conn.fetchval(
            f"update public.contacts set {zuweisungen} "
            f"where id = ${len(args)} and deleted_at is null returning id",
            *args,
        )
        if updated is None:
            raise HTTPException(404, "Kontakt nicht gefunden")
        await audit.log_fuer(
            conn,
            user,
            action="update",
            entity="contacts",
            entity_id=contact_id,
            diff=payload.model_dump(mode="json", exclude_unset=True),
        )
        row = await conn.fetchrow(LIST_SQL + " and k.id = $1", contact_id)
    return Contact(**dict(row))


@router.delete("/{contact_id}", status_code=204)
async def delete_contact(
    contact_id: UUID,
    user: CurrentUser = Depends(get_current_user),
) -> None:
    async with acquire_as(user.user_id) as conn:
        deleted = await conn.fetchval(
            "update public.contacts set deleted_at = now() "
            "where id = $1 and deleted_at is null returning id",
            contact_id,
        )
        if deleted is None:
            raise HTTPException(404, "Kontakt nicht gefunden")
        await audit.log_fuer(
            conn,
            user,
            action="delete",
            entity="contacts",
            entity_id=contact_id,
        )


# ── Weitere Firmen ──────────────────────────────────────────────────────
# `company_id` bleibt die Hauptfirma. Was hier hängt, ist zusätzlich —
# der IT-Leiter, der die Holding und zwei Töchter betreut.

from pydantic import BaseModel  # noqa: E402


class FirmenverknuepfungIn(BaseModel):
    company_id: UUID
    role: str | None = None


class Firmenverknuepfung(BaseModel):
    company_id: UUID
    company_name: str
    role: str | None = None
    # Wahr für die Hauptfirma aus `contacts.company_id`.
    ist_haupt: bool = False


@router.get("/{contact_id}/firmen", response_model=list[Firmenverknuepfung])
async def firmen(contact_id: UUID, user: CurrentUser = Depends(get_current_user)) -> list[Firmenverknuepfung]:
    async with acquire_as(user.user_id) as conn:
        haupt = await conn.fetchrow(
            "select k.company_id, f.name from public.contacts k "
            "left join public.companies f on f.id = k.company_id "
            "where k.id = $1 and k.deleted_at is null",
            contact_id,
        )
        if haupt is None:
            raise HTTPException(404, "Kontakt nicht gefunden")
        weitere = await conn.fetch(
            "select v.company_id, f.name, v.role from public.contact_companies v "
            "join public.companies f on f.id = v.company_id "
            "where v.contact_id = $1 and f.deleted_at is null order by f.name",
            contact_id,
        )
    ergebnis = []
    if haupt["company_id"]:
        ergebnis.append(Firmenverknuepfung(company_id=haupt["company_id"], company_name=haupt["name"], ist_haupt=True))
    ergebnis += [
        Firmenverknuepfung(company_id=z["company_id"], company_name=z["name"], role=z["role"])
        for z in weitere if z["company_id"] != haupt["company_id"]
    ]
    return ergebnis


@router.post("/{contact_id}/firmen", response_model=list[Firmenverknuepfung], status_code=201)
async def firma_verknuepfen(
    contact_id: UUID, payload: FirmenverknuepfungIn, user: CurrentUser = Depends(get_current_user)
) -> list[Firmenverknuepfung]:
    async with acquire_as(user.user_id) as conn:
        kontakt = await conn.fetchrow(
            "select company_id from public.contacts where id = $1 and deleted_at is null", contact_id
        )
        if kontakt is None:
            raise HTTPException(404, "Kontakt nicht gefunden")
        firma = await conn.fetchval(
            "select id from public.companies where id = $1 and deleted_at is null", payload.company_id
        )
        if firma is None:
            raise HTTPException(404, "Firma nicht gefunden")
        if kontakt["company_id"] is None:
            # Ohne Hauptfirma wird die erste Verknüpfung zur Hauptfirma —
            # sonst stünde der Kontakt in jeder Liste weiter „ohne Firma“.
            await conn.execute("update public.contacts set company_id = $1 where id = $2", payload.company_id, contact_id)
        else:
            await conn.execute(
                "insert into public.contact_companies (contact_id, company_id, org_id, role) values ($1,$2,$3,$4) "
                "on conflict (contact_id, company_id) do update set role = excluded.role",
                contact_id, payload.company_id, user.org_id, payload.role,
            )
        await audit.log_fuer(conn, user, action="update", entity="contacts", entity_id=contact_id,
                             diff={"firma_verknuepft": str(payload.company_id)})
    return await firmen(contact_id, user)


@router.delete("/{contact_id}/firmen/{company_id}", response_model=list[Firmenverknuepfung])
async def firma_loesen(
    contact_id: UUID, company_id: UUID, user: CurrentUser = Depends(get_current_user)
) -> list[Firmenverknuepfung]:
    async with acquire_as(user.user_id) as conn:
        kontakt = await conn.fetchrow(
            "select company_id from public.contacts where id = $1 and deleted_at is null", contact_id
        )
        if kontakt is None:
            raise HTTPException(404, "Kontakt nicht gefunden")
        if kontakt["company_id"] == company_id:
            # Die Hauptfirma lösen: Die nächste Verknüpfung rückt nach, sonst null.
            naechste = await conn.fetchval(
                "select company_id from public.contact_companies where contact_id = $1 and company_id <> $2 "
                "order by created_at limit 1", contact_id, company_id,
            )
            await conn.execute("update public.contacts set company_id = $1 where id = $2", naechste, contact_id)
            if naechste:
                await conn.execute(
                    "delete from public.contact_companies where contact_id = $1 and company_id = $2", contact_id, naechste
                )
        else:
            await conn.execute(
                "delete from public.contact_companies where contact_id = $1 and company_id = $2", contact_id, company_id
            )
        await audit.log_fuer(conn, user, action="update", entity="contacts", entity_id=contact_id,
                             diff={"firma_geloest": str(company_id)})
    return await firmen(contact_id, user)


@router.post("/{contact_id}/firmen/{company_id}/haupt", response_model=list[Firmenverknuepfung])
async def hauptfirma_setzen(
    contact_id: UUID, company_id: UUID, user: CurrentUser = Depends(get_current_user)
) -> list[Firmenverknuepfung]:
    """Tauscht Hauptfirma und Verknüpfung — die bisherige Hauptfirma bleibt verknüpft."""
    async with acquire_as(user.user_id) as conn:
        kontakt = await conn.fetchrow(
            "select company_id from public.contacts where id = $1 and deleted_at is null", contact_id
        )
        if kontakt is None:
            raise HTTPException(404, "Kontakt nicht gefunden")
        verknuepft = await conn.fetchval(
            "select 1 from public.contact_companies where contact_id = $1 and company_id = $2", contact_id, company_id
        )
        if not verknuepft:
            raise HTTPException(400, "Diese Firma ist mit dem Kontakt nicht verknüpft.")
        await conn.execute("delete from public.contact_companies where contact_id = $1 and company_id = $2", contact_id, company_id)
        if kontakt["company_id"]:
            await conn.execute(
                "insert into public.contact_companies (contact_id, company_id, org_id) values ($1,$2,$3) on conflict do nothing",
                contact_id, kontakt["company_id"], user.org_id,
            )
        await conn.execute("update public.contacts set company_id = $1 where id = $2", company_id, contact_id)
    return await firmen(contact_id, user)


# ── Einwilligung ────────────────────────────────────────────────────────

class EinwilligungIn(BaseModel):
    """Drei Handgriffe, die ein Mensch am Kontakt tun darf.

    `anfragen` schickt die Bestätigungsmail (Double-Opt-In); `bestaetigt`
    entsteht nur über ihren Link. `bestandskunde` ist die Ausnahme aus §7
    Abs. 3 UWG und wird bewusst gesetzt — mit dem Namen dessen, der es
    getan hat. `keine` nimmt alles zurück.
    """

    aktion: Literal["anfragen", "bestandskunde", "keine"]


@router.post("/{contact_id}/einwilligung", response_model=Contact)
async def einwilligung(
    contact_id: UUID,
    payload: EinwilligungIn,
    user: CurrentUser = Depends(get_current_user),
) -> Contact:
    fehler = None
    async with acquire_as(user.user_id) as conn:
        vorher = await conn.fetchval(
            "select marketing_einwilligung::text from public.contacts where id = $1 and deleted_at is null",
            contact_id,
        )
        if vorher is None:
            raise HTTPException(404, "Kontakt nicht gefunden")

        if payload.aktion == "anfragen":
            try:
                zeile = await versand.einwilligung_anfragen(conn, user.org_id, contact_id, actor=user.user_id)
            except versand.Unmoeglich as exc:
                raise HTTPException(409, str(exc)) from exc
            # Ein abgelehnter Versand bleibt im Buch und wird wiederholt;
            # der Fehler geht erst nach der Transaktion hinaus — sonst
            # nähme er die Zeile mit.
            if zeile["status"] != "gesendet":
                fehler = zeile["fehler"]
        else:
            neu = "bestandskunde" if payload.aktion == "bestandskunde" else "keine"
            nachweis = {
                "zeitpunkt": datetime.now().astimezone().isoformat(),
                "durch": str(user.user_id),
                "grund": "Bestandskunde nach §7 Abs. 3 UWG" if neu == "bestandskunde" else "zurückgesetzt",
            }
            await conn.execute(
                """
                update public.contacts
                   set marketing_einwilligung = $2::public.einwilligung,
                       einwilligung_am = case when $2 = 'bestandskunde' then now() else null end,
                       einwilligung_quelle = case when $2 = 'bestandskunde' then 'bestandskunde' else null end,
                       einwilligung_nachweis = $3::jsonb,
                       abgemeldet_am = null,
                       updated_at = now()
                 where id = $1
                """,
                contact_id, neu, orjson.dumps(nachweis).decode(),
            )
        await audit.log_fuer(
            conn, user, action="update", entity="contacts", entity_id=contact_id,
            diff={"marketing_einwilligung": payload.aktion, "vorher": vorher},
        )
        row = await conn.fetchrow(LIST_SQL + " and k.id = $1", contact_id)
    if fehler:
        raise HTTPException(502, f"Die Bestätigungsmail ging noch nicht hinaus, sie wird wiederholt: {fehler}")
    return Contact(**dict(row))
