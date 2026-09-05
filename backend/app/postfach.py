"""Post abholen und daraus Tickets machen.

Die Anwendung sitzt als **zweiter** Klient auf einem Postfach, vor dem
schon ein Mensch sitzt. Daraus folgt fast alles hier:

- **Keine Markierung wird angefasst.** Kein `\\Seen`, kein Löschen, kein
  Verschieben. Wer den Posteingang eines anderen umräumt, hat verloren,
  auch wenn die Tickets stimmen.
- **Gemerkt wird eine UID**, nicht „ungelesen" — siehe 0017.
- **Automaten werden übergangen.** Eine Abwesenheitsnotiz ist keine
  Anfrage, und eine Antwort darauf wäre der Anfang einer Schleife, die
  sich selbst füttert.

Gelesen wird mit `imaplib` und `email` aus der Standardbibliothek. Beide
sind blockierend; der Aufruf läuft deshalb in einem Faden, sonst steht
die ganze Anwendung, während ein Postfach nicht antwortet.
"""

from __future__ import annotations

import asyncio
import email
import imaplib
from dataclasses import dataclass
from email.header import decode_header, make_header
from email.message import Message
from email.utils import parseaddr, parsedate_to_datetime
from typing import Any
from uuid import UUID

# Mehr als das ist keine Anfrage mehr, sondern ein Anhang mit Text daneben.
MAX_TEXT = 20000
# Wie viele Nachrichten ein Lauf höchstens mitnimmt. Ein Postfach, das
# seit Wochen nicht abgeholt wurde, soll nicht in einem Zug tausend
# Tickets erzeugen — das wäre kein Rückstand, das wäre ein Unfall.
MAX_JE_LAUF = 50


@dataclass(frozen=True)
class Postfach:
    host: str
    port: int
    benutzer: str
    passwort: str
    ordner: str
    letzte_uid: int | None
    uid_gueltigkeit: int | None

    @property
    def eingerichtet(self) -> bool:
        return bool(self.host and self.benutzer and self.passwort)


def _entschluesselt(roh: str | None) -> str:
    """Betreffzeilen kommen als =?UTF-8?B?…?= herein."""
    if not roh:
        return ""
    try:
        return str(make_header(decode_header(roh)))
    except Exception:
        return roh


def ist_automat(nachricht: Message) -> bool:
    """Abwesenheitsnotizen, Verteiler, Zustellberichte — nichts davon
    ist eine Anfrage, und auf nichts davon darf geantwortet werden."""
    if (nachricht.get("Auto-Submitted") or "").lower().strip() not in ("", "no"):
        return True
    if (nachricht.get("Precedence") or "").lower().strip() in ("bulk", "list", "junk"):
        return True
    if nachricht.get("X-Autoreply") or nachricht.get("X-Autorespond"):
        return True
    if nachricht.get("List-Id") or nachricht.get("List-Unsubscribe"):
        return True
    absender = parseaddr(nachricht.get("From") or "")[1].lower()
    return absender.startswith(("mailer-daemon@", "postmaster@", "noreply@", "no-reply@"))


def _text_aus(nachricht: Message) -> str:
    """Den lesbaren Teil herausholen — Text bevorzugt, HTML notfalls."""
    kandidaten: list[tuple[str, str]] = []
    for teil in nachricht.walk() if nachricht.is_multipart() else [nachricht]:
        art = teil.get_content_type()
        if art not in ("text/plain", "text/html"):
            continue
        if "attachment" in (teil.get("Content-Disposition") or ""):
            continue
        try:
            roh = teil.get_payload(decode=True)
        except Exception:
            continue
        if not roh:
            continue
        zeichen = teil.get_content_charset() or "utf-8"
        kandidaten.append((art, roh.decode(zeichen, "replace")))

    for art in ("text/plain", "text/html"):
        for a, text in kandidaten:
            if a == art:
                return _ohne_markup(text)[:MAX_TEXT] if art == "text/html" else text[:MAX_TEXT]
    return ""


def _ohne_markup(html: str) -> str:
    """Grob entstückt. Kein Parser: Was hier ankommt, ist Fließtext für
    ein Ticket, keine Seite, die wieder angezeigt wird."""
    import re

    ohne = re.sub(r"(?is)<(script|style).*?</\1>", " ", html)
    ohne = re.sub(r"(?i)<br\s*/?>|</p>", "\n", ohne)
    ohne = re.sub(r"(?s)<[^>]+>", " ", ohne)
    import html as htmlmod

    ohne = htmlmod.unescape(ohne)
    return re.sub(r"\n{3,}", "\n\n", re.sub(r"[ \t]{2,}", " ", ohne)).strip()


def als_ereignis(nachricht: Message) -> dict[str, Any] | None:
    """Aus einer Nachricht wird das Ereignis, das der Ticketeingang kennt.

    Gibt `None` zurück, wenn daraus kein Ticket werden soll — damit ist
    die Entscheidung an einer Stelle und nicht über die Schleife verteilt.
    """
    if ist_automat(nachricht):
        return None

    betreff = _entschluesselt(nachricht.get("Subject")).strip() or "(ohne Betreff)"
    name, adresse = parseaddr(nachricht.get("From") or "")
    if not adresse:
        return None

    try:
        gesendet = parsedate_to_datetime(nachricht.get("Date"))
    except (TypeError, ValueError):
        gesendet = None

    return {
        "event": "ticket.erstellt",
        "id": (nachricht.get("Message-ID") or "").strip() or None,
        "occurred_at": gesendet.isoformat() if gesendet else None,
        "ticket": {
            "betreff": betreff,
            "beschreibung": _text_aus(nachricht),
            "absender": {"email": adresse, "name": _entschluesselt(name) or None},
        },
    }


def _holen(pf: Postfach) -> tuple[int | None, list[tuple[int, bytes]]]:
    """Der blockierende Teil: verbinden, suchen, laden.

    Gibt die UIDVALIDITY des Ordners zurück und die neuen Nachrichten als
    (UID, Rohbytes). Öffnet den Ordner **schreibgeschützt** — das ist
    keine Vorsicht, sondern die Zusage, nichts anzufassen.
    """
    verbindung = imaplib.IMAP4_SSL(pf.host, pf.port, timeout=30)
    try:
        verbindung.login(pf.benutzer, pf.passwort)
        art, daten = verbindung.select(f'"{pf.ordner}"', readonly=True)
        if art != "OK":
            raise RuntimeError(f"Ordner „{pf.ordner}“ nicht gefunden.")

        art, roh = verbindung.status(f'"{pf.ordner}"', "(UIDVALIDITY)")
        gueltigkeit = None
        if art == "OK" and roh and roh[0]:
            teil = roh[0].decode("ascii", "replace")
            if "UIDVALIDITY" in teil:
                gueltigkeit = int("".join(c for c in teil.split("UIDVALIDITY")[1] if c.isdigit()))

        # Ein Wechsel der Gültigkeit macht jede gemerkte UID wertlos.
        ab = pf.letzte_uid
        if pf.uid_gueltigkeit is not None and gueltigkeit != pf.uid_gueltigkeit:
            ab = None

        # Beim ersten Lauf nicht das ganze Postfach aufrollen: Was vor der
        # Einrichtung liegt, ist Bestand und keine offene Anfrage.
        bereich = f"{ab + 1}:*" if ab else "1:*"
        art, gefunden = verbindung.uid("SEARCH", None, "UID", bereich)
        if art != "OK":
            return gueltigkeit, []

        uids = [int(u) for u in (gefunden[0] or b"").split()]
        if ab:
            uids = [u for u in uids if u > ab]
        else:
            # Erstlauf: nur die jüngsten, damit ein altes Postfach nicht
            # als Lawine hereinkommt.
            uids = uids[-5:]
        uids = sorted(uids)[:MAX_JE_LAUF]

        nachrichten: list[tuple[int, bytes]] = []
        for uid in uids:
            art, teil = verbindung.uid("FETCH", str(uid), "(BODY.PEEK[])")
            if art != "OK" or not teil or not isinstance(teil[0], tuple):
                continue
            nachrichten.append((uid, teil[0][1]))
        return gueltigkeit, nachrichten
    finally:
        try:
            verbindung.logout()
        except Exception:
            pass


async def abholen(pf: Postfach) -> tuple[int | None, list[tuple[int, Message]]]:
    """Holt neue Post. Läuft im Faden, weil imaplib blockiert."""
    gueltigkeit, roh = await asyncio.to_thread(_holen, pf)
    return gueltigkeit, [(uid, email.message_from_bytes(b)) for uid, b in roh]


async def konfiguration(conn, org_id: UUID) -> Postfach:
    z = await conn.fetchrow(
        "select imap_host, imap_port, imap_benutzer, imap_passwort, imap_ordner, "
        "imap_letzte_uid, imap_uid_gueltigkeit from public.org_settings where org_id = $1",
        org_id,
    )
    if z is None:
        return Postfach("", 993, "", "", "INBOX", None, None)
    return Postfach(
        host=z["imap_host"] or "",
        port=z["imap_port"] or 993,
        benutzer=z["imap_benutzer"] or "",
        passwort=z["imap_passwort"] or "",
        ordner=z["imap_ordner"] or "INBOX",
        letzte_uid=z["imap_letzte_uid"],
        uid_gueltigkeit=z["imap_uid_gueltigkeit"],
    )


# ── Der Lauf ────────────────────────────────────────────────────────────

async def _quelle_fuer(conn, org_id: UUID) -> UUID:
    """Das Postfach ist eine Quelle wie jede andere.

    Damit gilt für Post dieselbe Dublettensperre wie für Schnittstelle
    und Bot — der eindeutige Index über (Quelle, Lieferkennung) —, und
    im Eingang steht später, woher ein Ticket kam.
    """
    vorhanden = await conn.fetchval(
        "select id from public.webhook_sources where org_id = $1 and kind = 'email' limit 1",
        org_id,
    )
    if vorhanden:
        return vorhanden
    import secrets

    return await conn.fetchval(
        "insert into public.webhook_sources (org_id, name, kind, secret, tickets_direkt) "
        "values ($1, 'Postfach', 'email', $2, true) returning id",
        org_id,
        secrets.token_urlsafe(32),
    )


async def einlesen(conn, org_id: UUID, actor: UUID) -> dict[str, int]:
    """Holt neue Post und legt Tickets an. Gibt die Bilanz zurück."""
    import orjson

    from app import ticketeingang

    pf = await konfiguration(conn, org_id)
    if not pf.eingerichtet:
        raise RuntimeError("Für dieses Postfach fehlen Adresse, Benutzer oder Passwort.")

    gueltigkeit, nachrichten = await abholen(pf)
    quelle = await _quelle_fuer(conn, org_id)

    bilanz = {"gelesen": len(nachrichten), "tickets": 0, "uebergangen": 0, "doppelt": 0}
    hoechste = pf.letzte_uid or 0

    for uid, nachricht in nachrichten:
        hoechste = max(hoechste, uid)
        ereignis = als_ereignis(nachricht)
        if ereignis is None:
            bilanz["uebergangen"] += 1
            continue

        lieferung = ereignis["id"] or f"uid:{uid}"
        posten = await conn.fetchval(
            """
            insert into public.eingang
              (org_id, source_id, delivery_id, event, external_id, titel, markdown,
               occurred_at, payload)
            values ($1,$2,$3,'ticket.erstellt',$4,$5,$6,$7,$8::jsonb)
            on conflict (source_id, delivery_id) do nothing
            returning id
            """,
            org_id, quelle, lieferung, lieferung,
            ereignis["ticket"]["betreff"], ereignis["ticket"]["beschreibung"],
            _zeit(ereignis["occurred_at"]),
            orjson.dumps(ereignis).decode(),
        )
        if posten is None:
            # Dieselbe Nachricht war schon da. Kein Fehler — der Abholer
            # darf sich überschneiden, ohne Schaden anzurichten.
            bilanz["doppelt"] += 1
            continue

        try:
            ticket_id, grund = await ticketeingang.anlegen(
                conn, org_id, actor, "email", ereignis, _zeit(ereignis["occurred_at"])
            )
        except ticketeingang.Unbrauchbar as exc:
            await conn.execute(
                "update public.eingang set zuordnung_grund = $1 where id = $2", str(exc), posten
            )
            bilanz["uebergangen"] += 1
            continue

        await conn.execute(
            "update public.eingang set ticket_id = $1, status = 'zugeordnet', "
            "zuordnung_grund = $2 where id = $3",
            ticket_id, grund, posten,
        )
        bilanz["tickets"] += 1

    await conn.execute(
        "update public.org_settings set imap_letzte_uid = $1, imap_uid_gueltigkeit = $2, "
        "imap_zuletzt = now(), imap_letzter_fehler = null where org_id = $3",
        hoechste or None, gueltigkeit, org_id,
    )
    return bilanz


def _zeit(roh: str | None):
    from datetime import datetime

    if not roh:
        return None
    try:
        return datetime.fromisoformat(roh)
    except ValueError:
        return None
