"""Dokumente an Firma, Kontakt, Geschäft oder Ticket."""

from datetime import datetime
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

from app import audit
from app import dokumente as kern
from app.auth import CurrentUser, get_current_user
from app.db import acquire_as

router = APIRouter(prefix="/api/dokumente", tags=["dokumente"])

BEZUEGE = ("company_id", "contact_id", "deal_id", "ticket_id")


class Dokument(BaseModel):
    id: UUID
    name: str
    groesse: int
    typ: str | None = None
    notiz: str | None = None
    created_at: datetime
    hochgeladen_von: UUID | None = None
    hochgeladen_von_name: str | None = None
    # Darf der Browser es im Fenster zeigen, oder nur herunterladen?
    im_fenster: bool = False


def _bezug(company_id, contact_id, deal_id, ticket_id) -> dict[str, UUID]:
    """Genau einer, nicht keiner und nicht zwei.

    Ein Dokument an zwei Stellen wäre zweimal dieselbe Datei mit zwei
    Wahrheiten darüber, wo sie hingehört — und niemand fände sie wieder.
    """
    gesetzt = {
        s: w for s, w in zip(
            BEZUEGE, (company_id, contact_id, deal_id, ticket_id), strict=True,
        ) if w
    }
    if len(gesetzt) != 1:
        raise HTTPException(
            400, "Ein Dokument gehört an genau eine Firma, einen Kontakt, ein Geschäft "
                 "oder ein Ticket.",
        )
    return gesetzt


@router.get("", response_model=list[Dokument])
async def liste(
    company_id: UUID | None = None,
    contact_id: UUID | None = None,
    deal_id: UUID | None = None,
    ticket_id: UUID | None = None,
    user: CurrentUser = Depends(get_current_user),
) -> list[Dokument]:
    bezug = _bezug(company_id, contact_id, deal_id, ticket_id)
    spalte, wert = next(iter(bezug.items()))
    async with acquire_as(user.user_id) as conn:
        zeilen = await conn.fetch(
            f"""
            select d.id, d.name, d.groesse, d.typ, d.notiz, d.created_at,
                   d.hochgeladen_von, u.display_name as hochgeladen_von_name
              from public.dokumente d
              left join public.users u on u.id = d.hochgeladen_von
             where d.{spalte} = $1 and d.deleted_at is null
             order by d.created_at desc
            """,  # noqa: S608 — der Spaltenname kommt aus BEZUEGE, nicht aus der Anfrage
            wert,
        )
    return [
        Dokument(**dict(z), im_fenster=kern.darf_im_fenster(z["typ"])) for z in zeilen
    ]


@router.post("", response_model=Dokument, status_code=201)
async def hochladen(
    datei: UploadFile = File(...),
    company_id: UUID | None = Form(None),
    contact_id: UUID | None = Form(None),
    deal_id: UUID | None = Form(None),
    ticket_id: UUID | None = Form(None),
    notiz: str | None = Form(None),
    user: CurrentUser = Depends(get_current_user),
) -> Dokument:
    """Legt eine Datei am Datensatz ab.

    Gelesen wird ein Byte über die Grenze hinaus — nur so lässt sich eine
    zu große Datei erkennen, ohne sie erst ganz in den Speicher zu holen.
    """
    bezug = _bezug(company_id, contact_id, deal_id, ticket_id)
    roh = await datei.read(kern.MAX_BYTES + 1)
    if len(roh) > kern.MAX_BYTES:
        raise HTTPException(
            413, f"Die Datei ist größer als {kern.MAX_BYTES // (1024 * 1024)} MB. "
                 "Große Dateien gehören in Drive auf der Box, nicht ins CRM.",
        )
    if not roh:
        raise HTTPException(400, "Die Datei ist leer.")

    name = kern.anzeigename(datei.filename or "datei")
    dokument_id = uuid4()
    spalte, wert = next(iter(bezug.items()))

    # Erst schreiben, dann eintragen: Eine Zeile ohne Datei zeigt ins
    # Leere, eine Datei ohne Zeile kostet nur Platz.
    pfad, pruefsumme = kern.schreiben(user.org_id, dokument_id, name, roh)
    try:
        async with acquire_as(user.user_id) as conn:
            zeile = await conn.fetchrow(
                f"""
                insert into public.dokumente
                  (id, org_id, {spalte}, name, pfad, groesse, typ, pruefsumme,
                   notiz, hochgeladen_von)
                values ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)
                returning id, name, groesse, typ, notiz, created_at, hochgeladen_von
                """,  # noqa: S608 — der Spaltenname kommt aus BEZUEGE
                dokument_id, user.org_id, wert, name, pfad, len(roh),
                datei.content_type, pruefsumme, (notiz or "").strip() or None,
                user.user_id,
            )
            await audit.log_fuer(
                conn, user, action="create", entity="dokumente", entity_id=dokument_id,
                diff={"name": name, "groesse": len(roh), spalte: str(wert)},
            )
    except Exception:
        kern.loeschen(pfad)
        raise

    return Dokument(
        **dict(zeile), hochgeladen_von_name=user.display_name,
        im_fenster=kern.darf_im_fenster(datei.content_type),
    )


@router.get("/{dokument_id}/datei")
async def datei_holen(
    dokument_id: UUID, user: CurrentUser = Depends(get_current_user)
) -> FileResponse:
    """Liefert die Datei aus — als Anhang, außer bei Bild und PDF.

    Warum das zählt: Eine hochgeladene HTML-Datei, die der Browser im
    Ursprung von Beacon anzeigt, wäre eingeschleustes Skript mit allen
    Rechten des Angemeldeten. Sie wird deshalb heruntergeladen und nicht
    dargestellt — und SVG ebenso, das kann Skript enthalten.
    """
    async with acquire_as(user.user_id) as conn:
        z = await conn.fetchrow(
            "select name, pfad, typ from public.dokumente "
            "where id = $1 and deleted_at is null",
            dokument_id,
        )
    if z is None:
        raise HTTPException(404, "Dieses Dokument gibt es nicht.")
    pfad = kern.pfad(z["pfad"])
    if pfad is None or not pfad.exists():
        raise HTTPException(
            410, "Die Datei liegt nicht mehr auf der Box. Der Eintrag ist noch da, "
                 "der Inhalt nicht — das passiert, wenn der Datenordner ersetzt wurde.",
        )
    im_fenster = kern.darf_im_fenster(z["typ"])
    return FileResponse(
        pfad,
        media_type=z["typ"] or "application/octet-stream",
        filename=z["name"],
        content_disposition_type="inline" if im_fenster else "attachment",
        headers={
            # Auch bei einem Bild: kein Raten am Inhalt. Sonst könnte eine
            # als PNG deklarierte HTML-Datei doch als Seite laufen.
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": "default-src 'none'; sandbox",
        },
    )


@router.delete("/{dokument_id}", status_code=204)
async def loeschen(dokument_id: UUID, user: CurrentUser = Depends(get_current_user)) -> None:
    """Entfernt Eintrag und Datei.

    Anders als bei Kontakten gibt es hier keine dreißig Tage: Eine Datei
    liegt auf der Platte, und „gelöscht, aber noch da" ist bei einem
    Dokument die Zusage, die man am wenigsten brechen will.
    """
    async with acquire_as(user.user_id) as conn:
        z = await conn.fetchrow(
            "delete from public.dokumente where id = $1 returning pfad, name", dokument_id
        )
        if z is None:
            raise HTTPException(404, "Dieses Dokument gibt es nicht.")
        await audit.log_fuer(
            conn, user, action="delete", entity="dokumente", entity_id=dokument_id,
            diff={"name": z["name"]},
        )
    kern.loeschen(z["pfad"])
