"""Kontakte."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query

from app import anreicherung, audit
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


@router.get("", response_model=list[Contact])
async def list_contacts(
    user: CurrentUser = Depends(get_current_user),
    q: str | None = Query(None),
    company_id: UUID | None = Query(None),
    limit: int = Query(50, le=200),
    offset: int = Query(0, ge=0),
) -> list[Contact]:
    sql = LIST_SQL
    args: list[object] = []
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
    args.extend([limit, offset])
    sql += f" order by k.updated_at desc limit ${len(args) - 1} offset ${len(args)}"

    async with acquire_as(user.user_id) as conn:
        rows = await conn.fetch(sql, *args)
    return [Contact(**dict(r)) for r in rows]


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
            await _custom_pruefen(conn, 'contacts', payload.custom),
        )
        await audit.log_fuer(
            conn,
            user,
            action="create",
            entity="contacts",
            entity_id=new_id,
            diff=payload.model_dump(mode="json"),
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
            # sonst stünde der Kontakt in jeder Liste weiter „ohne Firma".
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
