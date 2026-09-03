"""Post — E-Mail hinein und hinaus, über einen Dienst auf derselben Box.

Marcs Relay ist die Outlook-Alternative; seine Schnittstelle ist beim
Schreiben dieser Datei nicht bekannt. Deshalb steht hier ein **eigener,
kleiner Vertrag**, den jeder Dienst bedienen kann — derselbe Bauplan
wie beim Insilo-Eingang: signierter POST, roher Body, Idempotenz.

Hinein (`POST /api/post/eingang/{quelle}`), Kopfzeilen:
  X-Post-Event: mail.received
  X-Post-Delivery-ID: <stabil über Wiederholungen>
  X-Post-Signature: sha256=<HMAC-SHA256 über den rohen Body>
Body:
  {"message_id", "from", "to": [...], "subject", "text", "received_at"}

Hinaus (`POST /api/post/senden`): aicrm schickt an die eingetragene
Adresse denselben Vertrag zurück — signiert mit dem Geheimnis aus den
Einstellungen: {"to", "subject", "text", "in_reply_to"}.

Zugeordnet wird über die Absenderadresse: Kennt das CRM den Kontakt,
liegt die Mail als Verlaufseintrag an ihm und seiner Firma. Sonst wartet
sie im Eingang. Nichts wird von allein beantwortet — das Modell entwirft,
ein Mensch schickt.
"""

import hashlib
import hmac
from datetime import UTC, datetime
from uuid import UUID

import httpx
import orjson
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field

from app import audit
from app.auth import CurrentUser, get_current_user
from app.db import acquire, acquire_als_quelle, acquire_as
from app.routers.eingang import _zeitpunkt, signatur_stimmt

router = APIRouter(prefix="/api/post", tags=["post"])


class SendenIn(BaseModel):
    contact_id: UUID
    subject: str = Field(min_length=1, max_length=200)
    text: str = Field(min_length=1, max_length=20000)
    deal_id: UUID | None = None
    in_reply_to: str | None = None


class PostStatus(BaseModel):
    eingerichtet: bool
    absender: str | None = None
    hinweis: str | None = None


@router.get("/status", response_model=PostStatus)
async def status(user: CurrentUser = Depends(get_current_user)) -> PostStatus:
    async with acquire_as(user.user_id) as conn:
        z = await conn.fetchrow(
            "select mail_endpoint_url, mail_absender from public.org_settings where org_id = $1", user.org_id
        )
    ok = bool(z and (z["mail_endpoint_url"] or "").strip())
    return PostStatus(
        eingerichtet=ok,
        absender=z["mail_absender"] if z else None,
        hinweis=None if ok else "Kein Postausgang hinterlegt. Adresse und Geheimnis stehen unter Einstellungen.",
    )


@router.post("/senden")
async def senden(payload: SendenIn, user: CurrentUser = Depends(get_current_user)) -> dict:
    """Übergibt eine Nachricht an den Postausgang und hält sie im Verlauf fest."""
    async with acquire_as(user.user_id) as conn:
        einst = await conn.fetchrow(
            "select mail_endpoint_url, mail_endpoint_secret, mail_absender from public.org_settings where org_id = $1",
            user.org_id,
        )
        kontakt = await conn.fetchrow(
            "select email, company_id, first_name, last_name from public.contacts where id = $1 and deleted_at is null",
            payload.contact_id,
        )
    if kontakt is None:
        raise HTTPException(404, "Kontakt nicht gefunden")
    if not kontakt["email"]:
        raise HTTPException(400, "Dieser Kontakt hat keine E-Mail-Adresse.")
    url = ((einst and einst["mail_endpoint_url"]) or "").strip()
    if not url:
        raise HTTPException(409, "Kein Postausgang hinterlegt. Adresse und Geheimnis stehen unter Einstellungen.")

    nachricht = {
        "to": kontakt["email"],
        "from": einst["mail_absender"],
        "subject": payload.subject,
        "text": payload.text,
        "in_reply_to": payload.in_reply_to,
        "sent_at": datetime.now(UTC).isoformat(),
    }
    roh = orjson.dumps(nachricht)
    kopf = {
        "Content-Type": "application/json",
        "X-Post-Event": "mail.send",
        "X-Post-Signature": "sha256=" + hmac.new((einst["mail_endpoint_secret"] or "").encode(), roh, hashlib.sha256).hexdigest(),
    }
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            antwort = await client.post(url, content=roh, headers=kopf)
            antwort.raise_for_status()
    except httpx.HTTPStatusError as exc:
        raise HTTPException(502, f"Der Postausgang hat mit {exc.response.status_code} geantwortet.") from exc
    except httpx.RequestError as exc:
        raise HTTPException(502, f"Der Postausgang {url} ist nicht erreichbar: {exc}") from exc

    async with acquire_as(user.user_id) as conn:
        aktivitaet = await conn.fetchval(
            """
            insert into public.activities (org_id, kind, subject, body, company_id, contact_id, deal_id, payload, created_by)
            values ($1, 'email', $2, $3, $4, $5, $6, $7::jsonb, $8) returning id
            """,
            user.org_id, f"An {kontakt['email']}: {payload.subject}", payload.text,
            kontakt["company_id"], payload.contact_id, payload.deal_id,
            orjson.dumps({"richtung": "ausgehend", "an": kontakt["email"]}).decode(), user.user_id,
        )
        await audit.log_fuer(conn, user, action="create", entity="activities", entity_id=aktivitaet, diff={"email": "gesendet"})
    return {"gesendet": True, "activity_id": str(aktivitaet)}


@router.post("/eingang/{source_id}")
async def eingang(
    source_id: UUID,
    request: Request,
    x_post_event: str | None = Header(None, alias="X-Post-Event"),
    x_post_delivery_id: str | None = Header(None, alias="X-Post-Delivery-ID"),
    x_post_signature: str | None = Header(None, alias="X-Post-Signature"),
) -> dict:
    """Nimmt eine eingegangene Mail an — derselbe Bauplan wie der Insilo-Eingang."""
    roh = await request.body()
    async with acquire_als_quelle(source_id) as conn:
        quelle = await conn.fetchrow(
            "select id, org_id, secret, is_active from public.webhook_sources where id = $1", source_id
        )
    if quelle is None or not quelle["is_active"]:
        raise HTTPException(401, "Unbekannte oder abgeschaltete Quelle")
    if not signatur_stimmt(quelle["secret"], roh, x_post_signature):
        raise HTTPException(401, "Signatur stimmt nicht")
    try:
        daten = orjson.loads(roh)
    except orjson.JSONDecodeError as exc:
        raise HTTPException(400, f"Kein lesbares JSON: {exc}") from exc

    lieferung = x_post_delivery_id or daten.get("message_id")
    if not lieferung:
        raise HTTPException(400, "Ohne Idempotenzschlüssel wird nichts angenommen.")
    ereignis = x_post_event or "mail.received"
    absender = str(daten.get("from") or "").strip().lower()
    betreff = str(daten.get("subject") or "(ohne Betreff)")
    text = str(daten.get("text") or "")

    async with acquire() as conn:
        eigner = await conn.fetchval(
            "select user_id from public.user_org_roles where org_id = $1 and role = 'owner' limit 1", quelle["org_id"]
        )
    async with acquire_as(eigner) as conn:
        schon = await conn.fetchval(
            "select id from public.eingang where source_id = $1 and delivery_id = $2", source_id, lieferung
        )
        if schon:
            return {"status": "schon empfangen", "eingang_id": str(schon)}

        kontakt = None
        if absender:
            kontakt = await conn.fetchrow(
                "select id, company_id from public.contacts where lower(email) = $1 and deleted_at is null limit 1", absender
            )
        grund = f"Absender {absender or 'unbekannt'} " + ("bekannt" if kontakt else "nicht im CRM")

        posten = await conn.fetchval(
            """
            insert into public.eingang (org_id, source_id, delivery_id, event, external_id, titel, markdown,
                                        occurred_at, payload, company_id, zuordnung_grund)
            values ($1,$2,$3,$4,$5,$6,$7,$8,$9::jsonb,$10,$11) returning id
            """,
            quelle["org_id"], source_id, lieferung, ereignis, daten.get("message_id"), betreff, text,
            _zeitpunkt(daten.get("received_at")), roh.decode("utf-8", "replace"),
            kontakt["company_id"] if kontakt else None, grund,
        )
        await conn.execute("update public.webhook_sources set last_seen_at = now() where id = $1", source_id)

        aktivitaet = None
        if kontakt:
            aktivitaet = await conn.fetchval(
                """
                insert into public.activities (org_id, kind, subject, body, occurred_at, company_id, contact_id,
                                               payload, external_source, external_id, created_by)
                values ($1, 'email', $2, $3, coalesce($4, now()), $5, $6, $7::jsonb, 'post', $8, $9)
                on conflict do nothing returning id
                """,
                quelle["org_id"], f"Von {absender}: {betreff}", text, _zeitpunkt(daten.get("received_at")),
                kontakt["company_id"], kontakt["id"],
                orjson.dumps({"richtung": "eingehend", "von": absender, "message_id": daten.get("message_id")}).decode(),
                lieferung, eigner,
            )
            await conn.execute(
                "update public.eingang set status = 'zugeordnet', activity_id = $1 where id = $2", aktivitaet, posten
            )
    return {"status": "angenommen", "eingang_id": str(posten), "zugeordnet": bool(aktivitaet), "grund": grund}
