"""Aus einem eingehenden Ereignis wird ein Ticket.

Der Weg dorthin ist für jeden Kanal derselbe — API, Bot, Formular. Was
sie unterscheidet, ist die Quelle im Ticket und die Frage, ob die Quelle
durchregieren darf; alles andere wäre dreimal dasselbe Problem.

Drei Entscheidungen stecken hier drin, und alle drei sind an einem Fall
zu erkennen, den man sonst erst im Betrieb bemerkt:

- **Die SLA-Uhr startet, als der Absender geschrieben hat**, nicht als
  wir es gelesen haben. Wer sie beim Sichten startet, misst die eigene
  Reaktionszeit gegen die eigene Bequemlichkeit. Ein Ereignis, das drei
  Stunden in einer Warteschlange hing, ist drei Stunden alt.
- **Die Absenderadresse bleibt am Ticket**, auch wenn sie keinen Kontakt
  trifft. Sonst kommt eine Anfrage herein, auf die niemand antworten
  kann, weil die Adresse nur im Ereignis-JSON steht.
- **Nichts wird geraten.** Trifft die E-Mail keinen Kontakt, bleibt
  `contact_id` leer. Ein Ticket am falschen Kunden ist schlimmer als
  eines ohne Kunden — es sieht richtig aus.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from app.routers.tickets import _erste_stufe, _frist, _standard_pipeline

# Worauf dieser Weg anspringt. Beide Schreibweisen, weil ein fremder
# Absender die deutsche nicht kennen muss.
EREIGNISSE = {"ticket.erstellt", "ticket.created"}

# Was eine Quelle für ein Ticket bedeutet. Unbekanntes wird `api` — es
# kam über die Schnittstelle herein, und das stimmt immer.
QUELLE_AUS_ART = {
    "api": "api",
    "bot": "bot",
    "formular": "formular",
    "form": "formular",
    "email": "email",
    "insilo": "insilo",
}

PRIORITAETEN = ("dringend", "hoch", "mittel", "niedrig")


class Unbrauchbar(ValueError):  # noqa: N818 — die Fachbegriffe hier sind deutsch
    """Das Ereignis trägt nicht genug für ein Ticket."""


def _text(wert: Any, grenze: int) -> str | None:
    if wert is None:
        return None
    s = str(wert).strip()
    return s[:grenze] if s else None


def felder_aus(daten: dict[str, Any]) -> dict[str, Any]:
    """Liest die Ticketfelder aus dem Ereignis.

    Der Block darf unter `ticket` liegen oder flach danebenstehen. Wer
    eine Schnittstelle bedient, soll nicht an einer Verschachtelung
    scheitern, die ihm niemand gesagt hat.
    """
    t = daten.get("ticket") if isinstance(daten.get("ticket"), dict) else daten

    betreff = _text(t.get("betreff") or t.get("subject") or t.get("title"), 300)
    if not betreff:
        raise Unbrauchbar("Ohne Betreff wird kein Ticket angelegt.")

    absender = t.get("absender") if isinstance(t.get("absender"), dict) else {}
    if not absender and isinstance(t.get("from"), dict):
        absender = t["from"]

    email = _text(absender.get("email") or t.get("absender_email") or t.get("email"), 200)
    if email and "@" not in email:
        email = None

    prioritaet = _text(t.get("prioritaet") or t.get("priority"), 20)
    if prioritaet not in PRIORITAETEN:
        prioritaet = "mittel"

    return {
        "betreff": betreff,
        "beschreibung": _text(t.get("beschreibung") or t.get("body") or t.get("description"), 20000),
        "prioritaet": prioritaet,
        "kategorie": _text(t.get("kategorie") or t.get("category"), 120),
        "absender_email": email,
        "absender_name": _text(absender.get("name") or t.get("absender_name"), 200),
    }


async def _kontakt_zu(conn, email: str | None) -> tuple[UUID | None, UUID | None]:
    """Sucht den Kontakt zur Absenderadresse — und dessen Firma."""
    if not email:
        return None, None
    z = await conn.fetchrow(
        "select id, company_id from public.contacts "
        "where lower(email) = lower($1) and deleted_at is null limit 1",
        email,
    )
    return (z["id"], z["company_id"]) if z else (None, None)


async def anlegen(
    conn,
    org_id: UUID,
    actor: UUID,
    quelle_art: str,
    daten: dict[str, Any],
    eingegangen_am: datetime | None,
) -> tuple[UUID, str | None]:
    """Legt das Ticket an. Gibt seine Kennung und den Zuordnungsgrund zurück."""
    felder = felder_aus(daten)

    contact_id, company_id = await _kontakt_zu(conn, felder["absender_email"])
    grund = (
        f"Absender {felder['absender_email']} trifft einen Kontakt"
        if contact_id
        else ("Absender ist kein bekannter Kontakt" if felder["absender_email"] else None)
    )

    pipeline_id = await _standard_pipeline(conn, org_id)
    stage_id = await _erste_stufe(conn, pipeline_id)
    faellig = await _frist(conn, org_id, felder["prioritaet"], eingegangen_am)
    quelle = QUELLE_AUS_ART.get((quelle_art or "").lower(), "api")

    async with conn.transaction():
        nummer = await conn.fetchval(
            "select coalesce(max(nummer), 0) + 1 from public.tickets where org_id = $1", org_id
        )
        ticket_id = await conn.fetchval(
            """
            insert into public.tickets
              (org_id, nummer, betreff, beschreibung, pipeline_id, stage_id, prioritaet,
               kategorie, quelle, contact_id, company_id, faellig_am,
               absender_email, absender_name, created_by, created_at)
            values ($1,$2,$3,$4,$5,$6,$7::public.ticket_prioritaet,$8,
                    $9::public.ticket_quelle,$10,$11,$12,$13,$14,$15, coalesce($16, now()))
            returning id
            """,
            org_id, nummer, felder["betreff"], felder["beschreibung"], pipeline_id, stage_id,
            felder["prioritaet"], felder["kategorie"], quelle, contact_id, company_id, faellig,
            felder["absender_email"], felder["absender_name"], actor, eingegangen_am,
        )
    return ticket_id, grund
