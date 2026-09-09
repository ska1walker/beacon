"""Die aktuelle Liste als CSV — Filter, Spalten und Sortierung wie auf dem Bildschirm.

Die Abfrage kommt aus demselben `abfrage_sql` wie die Liste selbst. Ein
zweiter Filterbauer daneben wäre die Stelle, an der Tabelle und Datei
auseinanderlaufen, ohne dass es jemand merkt — und dann exportiert
jemand „alle Kunden in Hamburg" und bekommt etwas anderes.

Geschrieben wird zeilenweise über einen Cursor, nicht in eine Liste im
Speicher: Zwanzigtausend Kontakte sollen den Pod nicht umbringen.

Jede Ausfuhr steht im Protokoll. Sie verlässt die Box — das ist
dieselbe Art von Ereignis wie ein Anreicherungslauf und gehört
festgehalten, mit Zeilenzahl, Filter und Spalten.
"""

from datetime import date
from typing import Any

import orjson
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse

from app import audit, csvform, segmente
from app.auth import CurrentUser, get_current_user
from app.db import acquire_as
from app.routers import companies as firmen_router
from app.routers import contacts as kontakt_router

router = APIRouter(prefix="/api/ausfuhr", tags=["ausfuhr"])

# Woher die Zeilen kommen und wie die Datei heißt. Tickets und Aufgaben
# haben dieselben Feldlisten und wären je ein Eintrag mehr — sie fehlen
# hier, weil sie nicht geprüft sind, nicht weil es nicht ginge.
QUELLEN = {
    "contacts": (kontakt_router.abfrage_sql, "kontakte"),
    "companies": (firmen_router.abfrage_sql, "firmen"),
}


def _spalten_waehlen(entity: str, roh: str | None, felder: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Welche Spalten in die Datei kommen — in der Reihenfolge der Tabelle."""
    nach_schluessel = {f["schluessel"]: f for f in felder}
    if not roh:
        gewaehlt = segmente.VORGABE_SPALTEN[entity]
    elif roh == "alle":
        return felder
    else:
        gewaehlt = [s.strip() for s in roh.split(",") if s.strip()]

    ausgabe = []
    for schluessel in gewaehlt:
        feld = nach_schluessel.get(schluessel)
        if feld is None:
            raise HTTPException(400, f"„{schluessel}“ ist keine Spalte von {entity}.")
        ausgabe.append(feld)
    return ausgabe


@router.get("")
async def ausfuhr(
    entity: str = Query("contacts"),
    q: str | None = Query(None),
    filter: str | None = Query(None),
    sort: str | None = Query(None),
    richtung: str | None = Query(None),
    spalten: str | None = Query(None, description="Feldschlüssel, kommagetrennt, oder „alle“"),
    user: CurrentUser = Depends(get_current_user),
) -> StreamingResponse:
    if entity not in QUELLEN:
        raise HTTPException(400, "Export gibt es für Kontakte und Firmen.")
    bauen, dateiname = QUELLEN[entity]

    # Die Abfrage wird **vor** dem Generator gebaut: Ein Filterfehler soll
    # als 400 ankommen, nicht mitten in einer schon laufenden Datei.
    args: list[Any] = []
    sql = bauen(args, q, filter, sort, richtung)

    async with acquire_as(user.user_id) as conn:
        felder = await segmente.felder_fuer(conn, entity)
    gewaehlt = _spalten_waehlen(entity, spalten, felder)

    async def zeilen():
        async with acquire_as(user.user_id) as conn:
            personen = {
                str(p["id"]): p["name"]
                for p in await conn.fetch(
                    "select u.id, coalesce(u.display_name, u.olares_username) as name "
                    "from public.users u join public.user_org_roles r on r.user_id = u.id "
                    "where u.deleted_at is null"
                )
            }
            gezaehlt = 0
            async for satz in conn.cursor(sql, *args):
                eigen = orjson.loads(satz["custom"]) if satz.get("custom") else {}
                gezaehlt += 1
                yield [
                    csvform.zelle_text(
                        f,
                        eigen.get(f["schluessel"].removeprefix(segmente.CUSTOM_PRAEFIX))
                        if f["eigen"] else satz.get(f["schluessel"]),
                        personen,
                    )
                    for f in gewaehlt
                ]
            await audit.log_fuer(
                conn, user, action="export", entity=entity, entity_id=None,
                diff={
                    "zeilen": gezaehlt,
                    "spalten": [f["schluessel"] for f in gewaehlt],
                    "filter": filter,
                },
            )

    async def stuecke():
        stapel = csvform.Stapel()
        yield stapel.kopfzeile([f["text"] for f in gewaehlt])
        async for zeile in zeilen():
            stueck = stapel.dazu(zeile)
            if stueck:
                yield stueck
        letztes = stapel.rest()
        if letztes:
            yield letztes

    return StreamingResponse(
        stuecke(),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition":
                f'attachment; filename="beacon-{dateiname}-{date.today().isoformat()}.csv"',
            "X-Content-Type-Options": "nosniff",
        },
    )

