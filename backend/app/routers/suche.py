"""Eine Suche über alles — Firmen, Kontakte, Geschäfte, Tickets, Listen,
Kampagnen — für das Feld „Suchen oder fragen“.

Schnell und dumm, mit Absicht: `ilike` über die Felder, die ein Mensch
tippt (Name, Domain, E-Mail, Betreff), wenige Treffer je Art, nach
Aktualität sortiert. Was wie eine Frage aussieht, geht nicht hierher,
sondern an `/api/fragen` — die Oberfläche entscheidet das am Text.
"""

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from app.auth import CurrentUser, get_current_user
from app.db import acquire_as

router = APIRouter(prefix="/api/suche", tags=["suche"])


class Treffer(BaseModel):
    art: str
    id: UUID
    titel: str
    untertitel: str | None = None
    pfad: str


class Suchergebnis(BaseModel):
    q: str
    treffer: list[Treffer]


# Je Art: SQL mit $1 = Muster, $2 = Grenze. Sortiert nach Aktualität, weil
# das, woran zuletzt jemand gearbeitet hat, meist gemeint ist.
ARTEN: list[tuple[str, str, str]] = [
    ("firma", "/firmen/{id}", """
        select id, name as titel, concat_ws(' · ', nullif(domain, ''), nullif(city, '')) as untertitel
          from public.companies where deleted_at is null
           and (name ilike $1 or domain ilike $1 or city ilike $1)
         order by updated_at desc limit $2"""),
    ("kontakt", "/kontakte/{id}", """
        select k.id, trim(concat_ws(' ', k.first_name, k.last_name)) as titel,
               concat_ws(' · ', nullif(k.email, ''), f.name) as untertitel
          from public.contacts k left join public.companies f on f.id = k.company_id
         where k.deleted_at is null
           and (concat_ws(' ', k.first_name, k.last_name) ilike $1 or k.email ilike $1 or f.name ilike $1)
         order by k.updated_at desc limit $2"""),
    ("geschaeft", "/deals/{id}", """
        select d.id, d.name as titel, f.name as untertitel
          from public.deals d left join public.companies f on f.id = d.company_id
         where d.deleted_at is null and (d.name ilike $1 or f.name ilike $1)
         order by d.updated_at desc limit $2"""),
    ("ticket", "/tickets/{id}", """
        select t.id, t.betreff as titel,
               concat_ws(' · ', 'T-' || extract(year from t.created_at)::int || '-' || lpad(t.nummer::text, 4, '0'),
                         f.name, nullif(t.absender_email, '')) as untertitel
          from public.tickets t left join public.companies f on f.id = t.company_id
         where t.deleted_at is null
           and (t.betreff ilike $1 or t.beschreibung ilike $1 or t.absender_email ilike $1 or f.name ilike $1)
         order by t.updated_at desc limit $2"""),
    ("liste", "/listen/{id}", """
        select id, name as titel, art::text as untertitel from public.listen
         where deleted_at is null and name ilike $1 order by updated_at desc limit $2"""),
    ("kampagne", "/kampagnen/{id}", """
        select id, name as titel, betreff as untertitel from public.kampagnen
         where deleted_at is null and (name ilike $1 or betreff ilike $1) order by updated_at desc limit $2"""),
]


@router.get("", response_model=Suchergebnis)
async def suchen(
    q: str = Query(min_length=1, max_length=120),
    je_art: int = Query(default=5, ge=1, le=20),
    user: CurrentUser = Depends(get_current_user),
) -> Suchergebnis:
    muster = f"%{q.strip()}%"
    treffer: list[Treffer] = []
    async with acquire_as(user.user_id) as conn:
        for art, pfad, sql in ARTEN:
            for z in await conn.fetch(sql, muster, je_art):
                zeile: dict[str, Any] = dict(z)
                treffer.append(Treffer(
                    art=art, id=zeile["id"], titel=zeile["titel"] or "(ohne Namen)",
                    untertitel=(zeile.get("untertitel") or None), pfad=pfad.format(id=zeile["id"]),
                ))
    return Suchergebnis(q=q, treffer=treffer)
