"""CSV hereinholen — Vorlage, Vorschau, Anwenden, Protokoll.

Zwei Schritte, nicht vier: sehen, was passieren würde, und es dann tun.
Die Datei kommt beide Male mit; dazwischen bewahrt Beacon nichts auf
(siehe `app/einfuhr.py`).

Nur Eigentümer und Verwalter dürfen einführen. Ein Import schreibt
tausendfach in einen Bestand, den andere pflegen — das ist keine
Handlung, die ein Mitglied nebenbei auslöst.
"""

from datetime import datetime
from typing import Any
from uuid import UUID

import orjson
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app import csvform
from app import dokumente as dateikern
from app import einfuhr as kern
from app.auth import CurrentUser, get_current_user, verwaltet
from app.db import acquire_as

router = APIRouter(prefix="/api/einfuhr", tags=["einfuhr"])

# Wie viele Zeilen die Vorschau zeigt, und wie viele Ausschlüsse mitkommen.
# Fünf Zeilen genügen, um eine verrutschte Spalte zu erkennen; 500 Gründe
# genügen, um zu verstehen, was schiefging, ohne die Antwort zu sprengen.
VORSCHAUZEILEN = 5
HOECHSTENS_GRUENDE = 500


class Spalte(BaseModel):
    nr: int
    kopf: str
    beispiele: list[str]
    ziel: str | None = None


class Zielfeld(BaseModel):
    schluessel: str
    text: str
    art: str
    eigen: bool = False
    virtuell: bool = False


class Urteilszeile(BaseModel):
    zeile: int
    werte: list[str]
    urteil: str
    grund: str | None = None
    text: str | None = None


class Ausschluss(BaseModel):
    zeile: int
    grund: str | None = None
    text: str | None = None


class Vorschau(BaseModel):
    entity: str
    kodierung: str
    trenner: str
    zeilen: int
    ziele: list[Zielfeld]
    spalten: list[Spalte]
    nicht_zugeordnet: list[str]
    vorschau: list[Urteilszeile]
    bilanz: dict[str, Any]
    uebersprungen: list[Ausschluss]
    hinweise: list[str]


class Ergebnis(BaseModel):
    id: UUID
    entity: str
    angelegt: int
    firmen_angelegt: int
    uebersprungen: int
    gruende: dict[str, int]
    details: list[Ausschluss]


class Einfuhrzeile(BaseModel):
    id: UUID
    entity: str
    dateiname: str
    zeilen: int
    angelegt: int
    firmen_angelegt: int
    uebersprungen: int
    status: str
    fehler: str | None = None
    created_at: datetime
    von: str | None = None


def _objekt(entity: str | None, kopf: list[str]) -> str:
    if entity in kern.OBJEKTE:
        return entity
    if entity:
        raise HTTPException(400, "Import gibt es für Kontakte und Firmen.")
    return kern.entity_erraten(kopf)


async def _datei_lesen(datei: UploadFile) -> tuple[str, str, list[str], list[list[str]]]:
    """Bytes → Kodierung, Trenner, Kopfzeile, Zeilen.

    Ein Byte über die Grenze lesen, wie bei den Dokumenten: So fällt eine
    zu große Datei auf, ohne sie erst ganz in den Speicher zu holen.
    """
    roh = await datei.read(csvform.MAX_BYTES + 1)
    if len(roh) > csvform.MAX_BYTES:
        raise HTTPException(
            413,
            f"Die Datei ist größer als {csvform.MAX_BYTES // (1024 * 1024)} MB. "
            "Teilen Sie sie auf.",
        )
    if not roh:
        raise HTTPException(400, "Die Datei ist leer.")
    try:
        text, kodierung = csvform.bytes_lesen(roh)
        trenner, text = csvform.trenner_erkennen(text)
        kopf, zeilen = csvform.zeilen_lesen(text, trenner)
    except csvform.Unlesbar as exc:
        raise HTTPException(413 if exc.grund == "zeilen" else 400, exc.satz) from exc
    if not kopf or not any(kopf):
        raise HTTPException(400, "Die erste Zeile muss die Spaltennamen enthalten.")
    return kodierung, trenner, kopf, zeilen


def _zuordnung_lesen(roh: str | None, kopf: list[str], ziele: list[kern.Ziel], entity: str) -> list[str | None]:
    if not roh:
        return kern.zuordnen(kopf, ziele, entity)
    try:
        gewaehlt = orjson.loads(roh)
    except orjson.JSONDecodeError as exc:
        raise HTTPException(400, "Die Spaltenzuordnung ist unlesbar.") from exc
    if not isinstance(gewaehlt, list) or len(gewaehlt) != len(kopf):
        raise HTTPException(
            400, f"Die Zuordnung nennt {len(gewaehlt)} Spalten, die Datei hat {len(kopf)}."
        )
    bekannt = {z.schluessel for z in ziele}
    for eintrag in gewaehlt:
        if eintrag is not None and eintrag not in bekannt:
            raise HTTPException(400, f"„{eintrag}“ ist kein Feld, das sich füllen lässt.")
    return [e or None for e in gewaehlt]


@router.get("/vorlage")
async def vorlage(
    entity: str = Query("contacts"),
    user: CurrentUser = Depends(get_current_user),
) -> StreamingResponse:
    """Eine leere Datei mit den richtigen Spaltennamen.

    Nur die Kopfzeile, keine Beispielzeile: Eine Beispielzeile wird
    vergessen und mit importiert, und dann steht „Max Mustermann" im
    Bestand.
    """
    if entity not in kern.OBJEKTE:
        raise HTTPException(400, "Import gibt es für Kontakte und Firmen.")
    async with acquire_as(user.user_id) as conn:
        ziele = await kern.ziele_fuer(conn, entity)
    name = "kontakte" if entity == "contacts" else "firmen"
    return StreamingResponse(
        csvform.csv_zeilen([z.text for z in ziele], []),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="beacon-vorlage-{name}.csv"',
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.post("/vorschau", response_model=Vorschau)
async def vorschau(
    datei: UploadFile = File(...),
    entity: str | None = Form(None),
    zuordnung: str | None = Form(None),
    user: CurrentUser = Depends(verwaltet),
) -> Vorschau:
    """Was geschähe, wenn man jetzt importierte. Geschrieben wird nichts."""
    kodierung, trenner, kopf, zeilen = await _datei_lesen(datei)
    objekt = _objekt(entity, kopf)

    async with acquire_as(user.user_id) as conn:
        ziele = await kern.ziele_fuer(conn, objekt)
        gewaehlt = _zuordnung_lesen(zuordnung, kopf, ziele, objekt)
        lauf = await kern.probelauf(conn, user, objekt, kopf, zeilen, gewaehlt)

    spalten = [
        Spalte(
            nr=i,
            kopf=k,
            beispiele=[z[i] for z in zeilen[:3] if i < len(z) and z[i].strip()],
            ziel=gewaehlt[i],
        )
        for i, k in enumerate(kopf)
    ]
    return Vorschau(
        entity=objekt,
        kodierung=kodierung,
        trenner=trenner,
        zeilen=len(zeilen),
        ziele=[
            Zielfeld(schluessel=z.schluessel, text=z.text, art=z.art, eigen=z.eigen, virtuell=z.virtuell)
            for z in ziele
        ],
        spalten=spalten,
        nicht_zugeordnet=[k for i, k in enumerate(kopf) if gewaehlt[i] is None],
        vorschau=[
            Urteilszeile(
                zeile=z.nr,
                werte=zeilen[z.nr - 2][:12],
                urteil=z.urteil,
                grund=z.grund,
                text=z.satz,
            )
            for z in lauf.zeilen[:VORSCHAUZEILEN]
        ],
        bilanz=lauf.bilanz(),
        uebersprungen=[
            Ausschluss(zeile=z.nr, grund=z.grund, text=z.satz)
            for z in lauf.zeilen if z.urteil == "ueberspringen"
        ][:HOECHSTENS_GRUENDE],
        hinweise=lauf.hinweise,
    )


@router.post("", response_model=Ergebnis)
async def anwenden(
    datei: UploadFile = File(...),
    entity: str | None = Form(None),
    zuordnung: str | None = Form(None),
    user: CurrentUser = Depends(verwaltet),
) -> Ergebnis:
    """Legt an, was die Vorschau als „anlegen" gezeigt hat.

    Alles oder nichts: Geht mitten in der Datei etwas Unerwartetes
    schief, rollt die Transaktion zurück und es ist nichts geschrieben.
    Ein halber Import ist schlimmer als keiner — man sieht ihm nicht an,
    wo er aufgehört hat. Der Fehlschlag selbst wird trotzdem
    protokolliert, sonst bliebe von dem Versuch nichts übrig.
    """
    kodierung, trenner, kopf, zeilen = await _datei_lesen(datei)
    objekt = _objekt(entity, kopf)
    name = dateikern.anzeigename(datei.filename or "datei.csv")

    try:
        async with acquire_as(user.user_id) as conn:
            ziele = await kern.ziele_fuer(conn, objekt)
            gewaehlt = _zuordnung_lesen(zuordnung, kopf, ziele, objekt)
            lauf = await kern.probelauf(conn, user, objekt, kopf, zeilen, gewaehlt)
            ergebnis = await kern.anwenden(
                conn, user, objekt, lauf,
                dateiname=name, kodierung=kodierung, trenner=trenner, zuordnung=gewaehlt,
            )
    except HTTPException:
        raise
    except Exception as exc:
        async with acquire_as(user.user_id) as conn:
            await conn.execute(
                "insert into public.einfuhren "
                "(org_id, entity, dateiname, kodierung, trenner, zeilen, status, fehler, created_by) "
                "values ($1,$2,$3,$4,$5,$6,'fehlgeschlagen',$7,$8)",
                user.org_id, objekt, name, kodierung, trenner, len(zeilen),
                str(exc)[:500], user.user_id,
            )
        raise HTTPException(
            500, "Der Import ist fehlgeschlagen. Es wurde nichts angelegt — "
                 "der Versuch steht unter „Bisherige Importe“."
        ) from exc

    return Ergebnis(**ergebnis)


@router.get("", response_model=list[Einfuhrzeile])
async def liste(user: CurrentUser = Depends(get_current_user)) -> list[Einfuhrzeile]:
    async with acquire_as(user.user_id) as conn:
        zeilen = await conn.fetch(
            """
            select e.id, e.entity, e.dateiname, e.zeilen, e.angelegt, e.firmen_angelegt,
                   e.uebersprungen, e.status, e.fehler, e.created_at,
                   coalesce(u.display_name, u.olares_username) as von
              from public.einfuhren e
              left join public.users u on u.id = e.created_by
             order by e.created_at desc
             limit 20
            """
        )
    return [Einfuhrzeile(**dict(z)) for z in zeilen]


@router.get("/{einfuhr_id}", response_model=Ergebnis)
async def eine(einfuhr_id: UUID, user: CurrentUser = Depends(get_current_user)) -> Ergebnis:
    async with acquire_as(user.user_id) as conn:
        z = await conn.fetchrow(
            "select id, entity, angelegt, firmen_angelegt, uebersprungen, gruende, details "
            "from public.einfuhren where id = $1",
            einfuhr_id,
        )
    if z is None:
        raise HTTPException(404, "Diesen Import gibt es nicht.")
    return Ergebnis(
        id=z["id"], entity=z["entity"], angelegt=z["angelegt"],
        firmen_angelegt=z["firmen_angelegt"], uebersprungen=z["uebersprungen"],
        gruende=orjson.loads(z["gruende"]),
        details=[Ausschluss(**d) for d in orjson.loads(z["details"])],
    )
