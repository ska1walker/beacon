"""Eingehende Ereignisse von anderen Anwendungen — zuerst Insilo.

Der Vertrag steht in `insilo/docs/WEBHOOKS.md`: signierter POST,
HMAC-SHA256 über den **rohen** Body, Idempotenzschlüssel im Kopf
`X-Insilo-Delivery-ID`. Er wird hier eingehalten und nicht neu erfunden.

Der Empfangspfad hat als einziger in dieser Anwendung keine
Olares-Identität im Kopf — er kommt von einer Maschine, nicht von einem
Menschen. Statt `X-Bfl-User` trägt ihn die Signatur: Wer das Geheimnis
nicht hat, kommt nicht durch.
"""

import hashlib
import hmac
from datetime import datetime
from typing import Literal
from uuid import UUID

import orjson
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field

from app import ticketeingang
from app.auth import CurrentUser, get_current_user
from app.db import acquire, acquire_als_quelle, acquire_as

router = APIRouter(prefix="/api/eingang", tags=["eingang"])


# Die Art sagt, welcher Pfad die Quelle bedienen darf: `relay` nur den
# Postdienst (routers/post.py), alles andere nur diesen Eingang. Ein
# Geheimnis gilt damit für genau einen Vertrag.
# `relay` ist der Postdienst, `email` das eigene Postfach (app/postfach.py) —
# beide dürfen hier nicht anklopfen.
Quellenart = Literal["insilo", "api", "bot", "formular", "relay"]
EREIGNIS_ARTEN = ("insilo", "api", "bot", "formular")


def _pfad(kind: str, quelle_id) -> str:
    """Der Weg, den der Absender eintragen muss — je nach Art ein anderer."""
    return f"/api/post/eingang/{quelle_id}" if kind == "relay" else f"/api/eingang/{quelle_id}"


class QuelleIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    kind: Quellenart = "insilo"
    # Ob diese Quelle Tickets unmittelbar anlegen darf. Wer signieren
    # kann, darf es; ein öffentliches Formular kann kein Geheimnis
    # halten, und was von dort kommt, wartet im Eingang.
    tickets_direkt: bool = True


class Quelle(BaseModel):
    id: UUID
    name: str
    kind: str
    tickets_direkt: bool = True
    is_active: bool
    created_at: datetime
    last_seen_at: datetime | None = None
    # Der Weg, den der Absender eintragen muss.
    pfad: str


class QuelleNeu(Quelle):
    # Nur einmal, beim Anlegen. Danach nie wieder — wer es verliert,
    # legt eine neue Quelle an.
    secret: str


class Eingangsposten(BaseModel):
    id: UUID
    event: str
    titel: str | None = None
    external_id: str | None = None
    occurred_at: datetime | None = None
    status: str
    company_id: UUID | None = None
    company_name: str | None = None
    deal_id: UUID | None = None
    deal_name: str | None = None
    zuordnung_grund: str | None = None
    markdown_laenge: int = 0
    created_at: datetime


class Zuordnung(BaseModel):
    company_id: UUID | None = None
    deal_id: UUID | None = None


def signatur_stimmt(secret: str, roh: bytes, kopf: str | None) -> bool:
    """Prüft die HMAC-Signatur.

    Über den rohen Body, nicht über das geparste JSON: Leerzeichen,
    Schlüsselreihenfolge und Neu-Serialisierung ändern den Hash. Und der
    Vergleich läuft zeitkonstant — ein naives `==` verrät über die
    Laufzeit, wie viele Zeichen stimmten.
    """
    if not kopf:
        return False
    erwartet = "sha256=" + hmac.new(secret.encode(), roh, hashlib.sha256).hexdigest()
    return hmac.compare_digest(erwartet, kopf)


def _zeitpunkt(wert: object) -> datetime | None:
    """Ein ISO-Zeitpunkt aus fremdem JSON, oder nichts.

    Er kommt als Zeichenkette; asyncpg will ein datetime. Und er kommt
    von außen — ein unlesbarer Wert darf die Annahme nicht scheitern
    lassen, sonst wiederholt der Absender dreimal und gibt dann auf.
    """
    if not isinstance(wert, str) or not wert.strip():
        return None
    try:
        return datetime.fromisoformat(wert.replace("Z", "+00:00"))
    except ValueError:
        return None


def _namen_aus_ereignis(daten: dict) -> list[str]:
    """Woraus sich eine Zuordnung ableiten lässt: Titel und Schlagworte."""
    besprechung = daten.get("meeting") or {}
    teile = [besprechung.get("title") or ""]
    teile += [str(t) for t in (besprechung.get("tags") or [])]
    return [t for t in teile if t.strip()]


async def _zuordnen(conn, org_id: UUID, texte: list[str]) -> tuple[UUID | None, UUID | None, str]:
    """Sucht Firma und Geschäft — und sagt, warum.

    Zugeordnet wird nur, wenn es eindeutig ist. Zwei mögliche Firmen sind
    kein Grund, eine zu wählen: Ein Protokoll am falschen Kunden ist
    schlimmer als eines im Eingangskorb.
    """
    if not texte:
        return None, None, "kein Titel und keine Schlagworte"

    firmen = await conn.fetch(
        "select id, name from public.companies where deleted_at is null"
    )
    treffer = [
        f for f in firmen if any(f["name"].lower() in t.lower() for t in texte)
    ]

    if len(treffer) != 1:
        grund = (
            "keine Firma im Titel gefunden"
            if not treffer
            else f"mehrdeutig: {', '.join(f['name'] for f in treffer)}"
        )
        return None, None, grund

    firma = treffer[0]
    offene = await conn.fetch(
        """
        select d.id, d.name from public.deals d
        join public.pipeline_stages s on s.id = d.stage_id
        where d.company_id = $1 and d.deleted_at is null and s.kind = 'open'
        """,
        firma["id"],
    )
    if len(offene) == 1:
        return firma["id"], offene[0]["id"], f"{firma['name']} im Titel, ein offener Lead"
    if not offene:
        return firma["id"], None, f"{firma['name']} im Titel, kein offener Lead"
    return (
        firma["id"],
        None,
        f"{firma['name']} im Titel, aber {len(offene)} offene Leads",
    )


@router.post("/{source_id}", include_in_schema=True)
async def empfangen(
    source_id: UUID,
    request: Request,
    x_beacon_event: str | None = Header(None, alias="X-Beacon-Event"),
    x_beacon_delivery_id: str | None = Header(None, alias="X-Beacon-Delivery-Id"),
    x_beacon_signature: str | None = Header(None, alias="X-Beacon-Signature"),
    x_insilo_event: str | None = Header(None, alias="X-Insilo-Event"),
    x_insilo_delivery_id: str | None = Header(None, alias="X-Insilo-Delivery-ID"),
    x_insilo_signature: str | None = Header(None, alias="X-Insilo-Signature"),
    # Bis 0.1.12 hieß das Produkt aicrm; wer damals angeschlossen hat,
    # schickt weiter diese Kopfzeilen — und soll nicht merken, dass sich
    # ein Name geändert hat.
    x_aicrm_event: str | None = Header(None, alias="X-Aicrm-Event"),
    x_aicrm_delivery_id: str | None = Header(None, alias="X-Aicrm-Delivery-Id"),
    x_aicrm_signature: str | None = Header(None, alias="X-Aicrm-Signature"),
) -> dict:
    """Nimmt ein Ereignis einer eingetragenen Quelle entgegen.

    Die Kopfzeilen heißen `X-Beacon-*`; die `X-Insilo-*` bleiben als Alias
    gültig, weil Insilo seinen Vertrag nicht unsertwegen ändert. Wer neu
    anschließt, nimmt die neutralen — eine Schnittstelle, die von jedem
    Absender verlangt, sich für Insilo auszugeben, ist eine schlechte
    Schnittstelle.

    Antwortet auf eine unbekannte Quelle oder eine falsche Signatur mit
    401. Das ist kein Geiz: Insilo wiederholt bei 4xx nicht, und eine
    Auslieferung, die nie ankommen kann, soll nicht dreimal versucht
    werden.
    """
    ereignis_kopf = x_beacon_event or x_insilo_event or x_aicrm_event
    lieferung_kopf = x_beacon_delivery_id or x_insilo_delivery_id or x_aicrm_delivery_id
    signatur_kopf = x_beacon_signature or x_insilo_signature or x_aicrm_signature

    roh = await request.body()

    # Ohne Nutzerkontext: Der Absender ist eine Maschine und hat keine
    # Olares-Identität. Lesbar ist deshalb genau eine Zeile — die der
    # angesprochenen Quelle (siehe acquire_als_quelle). Erst wenn die
    # Signatur stimmt, läuft alles Weitere im Kontext ihrer Organisation.
    async with acquire_als_quelle(source_id) as conn:
        quelle = await conn.fetchrow(
            "select id, org_id, secret, is_active, kind, tickets_direkt "
            "from public.webhook_sources where id = $1",
            source_id,
        )

    if quelle is None or not quelle["is_active"]:
        raise HTTPException(401, "Unbekannte oder abgeschaltete Quelle")
    if quelle["kind"] not in EREIGNIS_ARTEN:
        # Dieselbe Antwort wie bei falscher Signatur: Wer hier mit einem
        # Post-Geheimnis anklopft, erfährt nicht mehr als „nein“.
        raise HTTPException(401, "Diese Quelle ist nicht für Ereignisse gedacht.")
    if not signatur_stimmt(quelle["secret"], roh, signatur_kopf):
        raise HTTPException(401, "Signatur stimmt nicht")

    try:
        daten = orjson.loads(roh)
    except orjson.JSONDecodeError as exc:
        raise HTTPException(400, f"Kein lesbares JSON: {exc}") from exc

    ereignis = ereignis_kopf or daten.get("event") or "unbekannt"
    lieferung = lieferung_kopf or daten.get("id")
    if not lieferung:
        raise HTTPException(400, "Ohne Idempotenzschlüssel wird nichts angenommen.")

    besprechung = daten.get("meeting") or {}
    org_id = quelle["org_id"]

    # Der Nutzerkontext für die Zeilensicherheit: der Eigentümer der
    # Organisation, zu der die Quelle gehört.
    async with acquire() as conn:
        eigner = await conn.fetchval(
            "select user_id from public.user_org_roles where org_id = $1 and role = 'owner' limit 1",
            org_id,
        )
    if eigner is None:
        raise HTTPException(500, "Die Organisation dieser Quelle hat keinen Eigentümer.")

    async with acquire_as(eigner) as conn:
        vorhanden = await conn.fetchval(
            "select id from public.eingang where source_id = $1 and delivery_id = $2",
            source_id,
            lieferung,
        )
        if vorhanden:
            # Eine Wiederholung ist kein Fehler. 200 mit dem Hinweis, dass
            # nichts Neues passiert ist — sonst wiederholt der Absender
            # weiter.
            return {"status": "schon empfangen", "eingang_id": str(vorhanden)}

        company_id, deal_id, grund = await _zuordnen(conn, org_id, _namen_aus_ereignis(daten))

        posten = await conn.fetchval(
            """
            insert into public.eingang
              (org_id, source_id, delivery_id, event, external_id, titel, markdown,
               occurred_at, payload, company_id, deal_id, zuordnung_grund)
            values ($1,$2,$3,$4,$5,$6,$7,$8,$9::jsonb,$10,$11,$12)
            returning id
            """,
            org_id,
            source_id,
            lieferung,
            ereignis,
            besprechung.get("id"),
            besprechung.get("title"),
            daten.get("markdown"),
            _zeitpunkt(daten.get("occurred_at")),
            roh.decode("utf-8", "replace"),
            company_id,
            deal_id,
            grund,
        )

        await conn.execute(
            "update public.webhook_sources set last_seen_at = now() where id = $1", source_id
        )

        # ── Ein Ticket? ──────────────────────────────────────────────
        # Nur eine Quelle mit Geheimnis darf durchregieren. Was von einem
        # öffentlichen Formular kommt, wartet im Eingang, bis ein Mensch
        # es ansieht — deshalb hängt die Entscheidung an der Quelle und
        # nicht an einer Verzweigung im Code.
        ticket_id = None
        if ereignis in ticketeingang.EREIGNISSE:
            if not quelle["tickets_direkt"]:
                return {
                    "status": "angenommen",
                    "eingang_id": str(posten),
                    "hinweis": "Diese Quelle legt keine Tickets an — der Posten wartet im Eingang.",
                }
            try:
                ticket_id, ticketgrund = await ticketeingang.anlegen(
                    conn, org_id, eigner, quelle["kind"], daten,
                    _zeitpunkt(daten.get("occurred_at") or daten.get("eingegangen_am")),
                )
            except ticketeingang.Unbrauchbar as exc:
                # Der Posten steht schon; das Ereignis war nur zu dünn.
                # 400 ist richtig: Ein Wiederholen ändert daran nichts.
                await conn.execute(
                    "update public.eingang set zuordnung_grund = $1 where id = $2",
                    str(exc), posten,
                )
                raise HTTPException(400, str(exc)) from exc

            await conn.execute(
                "update public.eingang set ticket_id = $1, status = 'zugeordnet', "
                "zuordnung_grund = coalesce($2, zuordnung_grund) where id = $3",
                ticket_id, ticketgrund, posten,
            )
            return {
                "status": "angenommen",
                "eingang_id": str(posten),
                "ticket_id": str(ticket_id),
                "grund": ticketgrund,
            }

        # Nur ein fertiges Protokoll wird von allein zur Aktivität. Ein
        # „angelegt" oder „fehlgeschlagen" hat am Deal nichts verloren.
        aktivitaet = None
        if ereignis == "meeting.ready" and (deal_id or company_id):
            aktivitaet = await _als_aktivitaet(conn, org_id, eigner, posten)

    return {
        "status": "angenommen",
        "eingang_id": str(posten),
        "zugeordnet": bool(aktivitaet),
        "grund": grund,
    }


async def _als_aktivitaet(conn, org_id: UUID, actor: UUID, eingang_id: UUID) -> UUID | None:
    """Macht aus einem Eingangsposten eine Aktivität am Deal."""
    posten = await conn.fetchrow("select * from public.eingang where id = $1", eingang_id)
    if posten is None:
        return None

    # Dieselbe Besprechung kann über zwei Auslieferungen hereinkommen —
    # etwa nach einem `meeting.updated`. Der eindeutige Index verhindert
    # die zweite Aktivität; `do nothing` gibt dann aber nichts zurück,
    # und der Eingangsposten stünde auf „zugeordnet" ohne Ziel. Deshalb
    # wird der vorhandene Eintrag hinterher gesucht.
    aktivitaet = await conn.fetchval(
        """
        insert into public.activities
          (org_id, kind, subject, body, occurred_at, company_id, deal_id,
           payload, external_source, external_id, created_by)
        values ($1, 'meeting', $2, $3, coalesce($4, now()), $5, $6, $7::jsonb, 'insilo', $8, $9)
        on conflict do nothing
        returning id
        """,
        org_id,
        posten["titel"] or "Besprechung",
        posten["markdown"],
        posten["occurred_at"],
        posten["company_id"],
        posten["deal_id"],
        orjson.dumps({"quelle": "insilo", "besprechung": posten["external_id"]}).decode(),
        posten["external_id"],
        actor,
    )

    if aktivitaet is None and posten["external_id"]:
        aktivitaet = await conn.fetchval(
            "select id from public.activities where org_id = $1 "
            "and external_source = 'insilo' and external_id = $2",
            org_id,
            posten["external_id"],
        )

    await conn.execute(
        "update public.eingang set status = 'zugeordnet', activity_id = $1 where id = $2",
        aktivitaet,
        eingang_id,
    )
    return aktivitaet


# ── Verwaltung ──────────────────────────────────────────────────────────

@router.get("", response_model=list[Eingangsposten])
async def liste(
    user: CurrentUser = Depends(get_current_user),
    status: str = "offen",
) -> list[Eingangsposten]:
    async with acquire_as(user.user_id) as conn:
        zeilen = await conn.fetch(
            """
            select e.id, e.event, e.titel, e.external_id, e.occurred_at, e.status,
                   e.company_id, e.deal_id, e.zuordnung_grund, e.created_at,
                   coalesce(length(e.markdown), 0) as markdown_laenge,
                   f.name as company_name, d.name as deal_name
            from public.eingang e
            left join public.companies f on f.id = e.company_id
            left join public.deals d on d.id = e.deal_id
            where e.status = $1::public.eingang_status
            order by e.created_at desc
            limit 200
            """,
            status,
        )
    return [Eingangsposten(**dict(z)) for z in zeilen]


@router.get("/{eingang_id}/markdown")
async def markdown(eingang_id: UUID, user: CurrentUser = Depends(get_current_user)) -> dict:
    async with acquire_as(user.user_id) as conn:
        zeile = await conn.fetchrow(
            "select titel, markdown from public.eingang where id = $1", eingang_id
        )
    if zeile is None:
        raise HTTPException(404, "Nicht gefunden")
    return {"titel": zeile["titel"], "markdown": zeile["markdown"] or ""}


@router.post("/{eingang_id}/zuordnen", response_model=dict)
async def zuordnen(
    eingang_id: UUID,
    payload: Zuordnung,
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    """Ordnet einen Posten von Hand zu und legt die Aktivität an."""
    if not (payload.company_id or payload.deal_id):
        raise HTTPException(400, "Firma oder Lead angeben.")

    async with acquire_as(user.user_id) as conn:
        vorhanden = await conn.fetchval(
            "select id from public.eingang where id = $1 and status <> 'zugeordnet'", eingang_id
        )
        if vorhanden is None:
            raise HTTPException(404, "Nicht gefunden oder bereits zugeordnet")

        company_id = payload.company_id
        if payload.deal_id and not company_id:
            company_id = await conn.fetchval(
                "select company_id from public.deals where id = $1", payload.deal_id
            )

        await conn.execute(
            "update public.eingang set company_id = $1, deal_id = $2, "
            "zuordnung_grund = 'von Hand zugeordnet' where id = $3",
            company_id,
            payload.deal_id,
            eingang_id,
        )
        aktivitaet = await _als_aktivitaet(conn, user.org_id, user.user_id, eingang_id)

    return {"zugeordnet": True, "activity_id": str(aktivitaet) if aktivitaet else None}


@router.post("/{eingang_id}/verwerfen", status_code=204)
async def verwerfen(eingang_id: UUID, user: CurrentUser = Depends(get_current_user)) -> None:
    async with acquire_as(user.user_id) as conn:
        weg = await conn.fetchval(
            "update public.eingang set status = 'verworfen' where id = $1 and status = 'offen' "
            "returning id",
            eingang_id,
        )
    if weg is None:
        raise HTTPException(404, "Nicht gefunden oder nicht mehr offen")


# ── Quellen ─────────────────────────────────────────────────────────────

quellen_router = APIRouter(prefix="/api/quellen", tags=["eingang"])


@quellen_router.get("", response_model=list[Quelle])
async def quellen(user: CurrentUser = Depends(get_current_user)) -> list[Quelle]:
    async with acquire_as(user.user_id) as conn:
        zeilen = await conn.fetch(
            "select id, name, kind, tickets_direkt, is_active, created_at, last_seen_at "
            "from public.webhook_sources order by created_at"
        )
    return [Quelle(**dict(z), pfad=_pfad(z["kind"], z["id"])) for z in zeilen]


@quellen_router.post("", response_model=QuelleNeu, status_code=201)
async def quelle_anlegen(
    payload: QuelleIn,
    user: CurrentUser = Depends(get_current_user),
) -> QuelleNeu:
    """Legt eine Quelle an und zeigt das Geheimnis genau einmal."""
    import secrets

    geheim = secrets.token_urlsafe(32)
    async with acquire_as(user.user_id) as conn:
        zeile = await conn.fetchrow(
            "insert into public.webhook_sources (org_id, name, kind, secret, tickets_direkt) "
            "values ($1,$2,$3,$4,$5) returning id, name, kind, tickets_direkt, is_active, "
            "created_at, last_seen_at",
            user.org_id,
            payload.name,
            payload.kind,
            geheim,
            payload.tickets_direkt,
        )
    return QuelleNeu(**dict(zeile), pfad=_pfad(zeile["kind"], zeile["id"]), secret=geheim)


@quellen_router.delete("/{quelle_id}", status_code=204)
async def quelle_loeschen(quelle_id: UUID, user: CurrentUser = Depends(get_current_user)) -> None:
    async with acquire_as(user.user_id) as conn:
        weg = await conn.fetchval(
            "update public.webhook_sources set is_active = false where id = $1 returning id",
            quelle_id,
        )
    if weg is None:
        raise HTTPException(404, "Quelle nicht gefunden")
