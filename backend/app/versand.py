"""Versand — Mails, die das Haus verlassen.

Zwei Wege, bewusst getrennt (Migration 0019): transaktionale Post über
das eigene SMTP-Konto, Marketing-Post später über einen Dienst oder
dasselbe Konto. Beide laufen über eine Zeile in `mails`: erst das Buch,
dann der Versand. Was scheitert, bleibt mit Grund stehen.

Drei Dinge, die man an einem Fall erkennt:

- **Eine Antwort hängt am Faden.** `In-Reply-To` und `References` tragen
  die Message-ID der Anfrage — sonst landet die Antwort beim Empfänger
  als neue Unterhaltung, und die Kennung im Betreff ist der einzige Halt.
- **Ein Platzhalter, den niemand füllt, wird leer** — nie „{{vorname}}“
  in einer Mail an einen Menschen.
- **Marketing-Post trägt einen Abmeldelink**, in der Kopfzeile
  (`List-Unsubscribe`) und im Text. Beides, weil Mailprogramme das eine
  zeigen und Menschen das andere suchen.
"""

from __future__ import annotations

import asyncio
import hashlib
import re
import smtplib
import ssl
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
from datetime import datetime
from email.message import EmailMessage
from email.utils import formataddr, make_msgid
from typing import Any
from uuid import UUID

import orjson

from app import links, tresor
from app.config import settings

# Olares adressiert einen Entrance als <appid><index>.<nutzer>.<zone>, mit
# appid = md5(<appname>)[:8]. Der öffentliche Entrance ist der zweite im
# Manifest (Index 1). Gemessen am 5.9.2026, docs/BETRIEB.md.
APP_NAME = "beacon"
OEFFENTLICHER_INDEX = 1

SICHERHEIT = ("starttls", "ssl", "keine")

# Was in einer Vorlage stehen darf. Unbekanntes wird leer, nicht stehen
# gelassen — eine Mail mit „{{vorname}}“ darin geht an niemanden.
PLATZHALTER = (
    "anrede", "vorname", "nachname", "name", "email", "firma", "position",
    "bestaetigungslink", "abmeldelink",
)

DOI_BETREFF = "Bitte bestätigen Sie Ihre Einwilligung"
DOI_TEXT = """{{anrede}},

Sie haben sich für Neuigkeiten von uns eingetragen. Damit wir Ihnen
schreiben dürfen, bestätigen Sie das bitte mit einem Klick:

{{bestaetigungslink}}

Der Link gilt sieben Tage. Wenn Sie sich nicht eingetragen haben, tun Sie
nichts — dann bleibt alles, wie es ist.
"""


class Unmoeglich(Exception):  # noqa: N818 — die Fachbegriffe hier sind deutsch
    """Etwas fehlt, ohne das nichts gehen kann: kein Konto, kein Empfänger,
    keine Adresse für die Links. Kein Fehler des Servers — eine Angabe,
    die noch aussteht."""


# ── Platzhalter ─────────────────────────────────────────────────────────

_MUSTER = re.compile(r"\{\{\s*([a-zA-Z_]+)\s*\}\}")


def rendern(vorlage: str, werte: dict[str, Any]) -> str:
    return _MUSTER.sub(lambda m: str(werte.get(m.group(1).lower()) or ""), vorlage or "")


def platzhalter_aus(kontakt: dict[str, Any] | None, **weitere: Any) -> dict[str, Any]:
    """Die Werte, die eine Vorlage aus einem Kontakt ziehen darf."""
    k = kontakt or {}
    vorname = (k.get("first_name") or "").strip()
    nachname = (k.get("last_name") or "").strip()
    name = " ".join(t for t in (vorname, nachname) if t)
    # Ohne Geschlecht keine „Frau/Herr“-Anrede — die wäre in der Hälfte der
    # Fälle falsch. „Guten Tag Anna Peters“ ist bei jedem richtig.
    anrede = f"Guten Tag {name}" if name else "Guten Tag"
    werte = {
        "anrede": anrede,
        "vorname": vorname,
        "nachname": nachname,
        "name": name,
        "email": k.get("email") or "",
        "firma": k.get("company_name") or "",
        "position": k.get("job_title") or "",
    }
    werte.update({s: (w or "") for s, w in weitere.items()})
    return werte


# ── Die Adresse der öffentlichen Links ──────────────────────────────────

def appid() -> str:
    return hashlib.md5(APP_NAME.encode()).hexdigest()[:8]  # noqa: S324 — Kennung, kein Schutz


def basis_url(einst: dict[str, Any] | None) -> str | None:
    """Wo Bestätigen, Abmelden und Klick erreichbar sind.

    Ein eigener Wert in den Einstellungen gewinnt. Sonst aus der Domain,
    die Olares dem Chart mitgibt (`.Values.domain.beacon`, hier als
    APP_DOMAIN): erste Stufe abschneiden, den öffentlichen Entrance davor.
    """
    eigen = ((einst or {}).get("links_basis_url") or "").strip()
    if eigen:
        return eigen.rstrip("/")
    domain = (settings.app_domain or "").strip().lower()
    if "." not in domain:
        return None
    zone = domain.split(".", 1)[1]
    return f"https://{appid()}{OEFFENTLICHER_INDEX}.{zone}"


# ── Das Konto ───────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Smtp:
    host: str
    port: int
    benutzer: str | None
    passwort: str | None
    sicherheit: str
    absender: str
    absender_name: str | None

    @property
    def von(self) -> str:
        return formataddr((self.absender_name or "", self.absender))


def smtp_aus(einst: dict[str, Any] | None) -> Smtp | None:
    """Das Konto aus der Einstellungszeile — oder None, wenn keins da ist."""
    e = einst or {}
    host = (e.get("smtp_host") or "").strip()
    absender = (e.get("smtp_absender") or "").strip()
    if not host or not absender:
        return None
    sicherheit = (e.get("smtp_sicherheit") or "starttls").lower()
    if sicherheit not in SICHERHEIT:
        sicherheit = "starttls"
    return Smtp(
        host=host, port=int(e.get("smtp_port") or 587),
        benutzer=(e.get("smtp_benutzer") or None),
        passwort=tresor.entschluesseln(e.get("smtp_passwort")) or None,
        sicherheit=sicherheit, absender=absender, absender_name=(e.get("smtp_absender_name") or None),
    )


def domain_von(adresse: str) -> str:
    return adresse.rsplit("@", 1)[-1].strip().lower() if "@" in adresse else ""


def smtp_fuer(einst: dict[str, Any] | None, nutzer: dict[str, Any] | None) -> Smtp | None:
    """Das Konto, mit dem **diese Person** schickt.

    Drei Fälle, in dieser Reihenfolge:

    1. Eigene Zugangsdaten vollständig → eigenes Postfach, eigene Anmeldung.
       Wer sich selbst anmeldet, darf auch eine fremde Domain führen.
    2. Nur eine eigene Adresse → das Konto der Organisation, aber mit
       dieser `From`. Erlaubt ist dabei nur dieselbe Domain wie der
       Absender der Organisation; sonst wäre das gemeinsame Konto ein Weg,
       als beliebige Adresse zu schreiben.
    3. Nichts hinterlegt → der Absender der Organisation, wie bisher.
    """
    haus = smtp_aus(einst)
    n = nutzer or {}
    adresse = (n.get("absender_email") or "").strip()
    name = (n.get("absender_name") or "").strip() or None

    eigener_host = (n.get("smtp_host") or "").strip()
    if eigener_host and adresse:
        sicherheit = (n.get("smtp_sicherheit") or "starttls").lower()
        if sicherheit not in SICHERHEIT:
            sicherheit = "starttls"
        return Smtp(
            host=eigener_host, port=int(n.get("smtp_port") or 587),
            benutzer=(n.get("smtp_benutzer") or None),
            passwort=tresor.entschluesseln(n.get("smtp_passwort")) or None,
            sicherheit=sicherheit, absender=adresse, absender_name=name,
        )

    if haus is None or not adresse:
        return haus
    if domain_von(adresse) != domain_von(haus.absender):
        # Nicht heimlich auf das Hauskonto zurückfallen: Wer eine fremde
        # Domain einträgt, soll den Fehler sehen, nicht eine Mail unter
        # falschem Namen. Das Speichern weist das ohnehin schon ab.
        raise Unmoeglich(
            f"„{adresse}“ gehört nicht zur Domain des Absenders der Organisation "
            f"({domain_von(haus.absender)}). Hinterlegen Sie eigene Zugangsdaten, "
            "um unter einer anderen Domain zu schreiben."
        )
    return replace(haus, absender=adresse, absender_name=name or haus.absender_name)


def _smtp_senden(konto: Smtp, nachricht: EmailMessage) -> None:
    """Blockierend — läuft in einem Thread. Ein Versand, ein Verbindungsaufbau."""
    kontext = ssl.create_default_context()
    if konto.sicherheit == "ssl":
        verbindung: smtplib.SMTP = smtplib.SMTP_SSL(konto.host, konto.port, timeout=20, context=kontext)
    else:
        verbindung = smtplib.SMTP(konto.host, konto.port, timeout=20)
    with verbindung:
        verbindung.ehlo()
        if konto.sicherheit == "starttls":
            verbindung.starttls(context=kontext)
            verbindung.ehlo()
        if konto.benutzer:
            verbindung.login(konto.benutzer, konto.passwort or "")
        verbindung.send_message(nachricht)


async def senden_smtp(konto: Smtp, nachricht: EmailMessage) -> None:
    await asyncio.to_thread(_smtp_senden, konto, nachricht)


# Was den Versand tatsächlich tut. Tests hängen hier eine Attrappe ein;
# das Postfach hat dasselbe Muster (`postfach.abholen`).
Sender = Callable[[Smtp, EmailMessage], Awaitable[None]]


def neue_message_id(absender: str) -> str:
    domain = absender.rsplit("@", 1)[-1] if "@" in absender else "beacon.local"
    return make_msgid(domain=domain)


def nachricht_bauen(
    *,
    an: str,
    betreff: str,
    text: str,
    konto: Smtp | Brevo,
    message_id: str,
    in_reply_to: str | None = None,
    referenzen: str | None = None,
    abmelde_url: str | None = None,
    antwort_an: str | None = None,
) -> EmailMessage:
    m = EmailMessage()
    m["From"] = konto.von
    m["To"] = an
    # Damit die Antwort im Bestand landet und nicht im privaten Postfach:
    # Beacon liest genau ein Postfach je Organisation. Schickt jemand unter
    # seiner eigenen Adresse, käme die Antwort dort an, wo niemand sie
    # einliest — und der Faden im CRM bliebe stumm.
    if antwort_an and antwort_an.strip().lower() != konto.absender.strip().lower():
        m["Reply-To"] = antwort_an
    m["Subject"] = betreff
    m["Message-ID"] = message_id
    m["Date"] = datetime.now().astimezone()
    m["X-Mailer"] = "beacon"
    if in_reply_to:
        m["In-Reply-To"] = in_reply_to
        m["References"] = referenzen or in_reply_to
    if abmelde_url:
        m["List-Unsubscribe"] = f"<{abmelde_url}>"
        m["List-Unsubscribe-Post"] = "List-Unsubscribe=One-Click"
    m.set_content(text)
    return m


# ── Das Buch ────────────────────────────────────────────────────────────

async def einreihen(
    conn,
    org_id: UUID,
    *,
    art: str,
    an: str,
    betreff: str,
    text: str,
    contact_id: UUID | None = None,
    ticket_id: UUID | None = None,
    in_reply_to: str | None = None,
    referenzen: str | None = None,
    created_by: UUID | None = None,
    payload: dict[str, Any] | None = None,
    kampagne_id: UUID | None = None,
) -> UUID:
    """Eine Zeile, noch kein Versand."""
    an = (an or "").strip()
    if not an or "@" not in an:
        raise Unmoeglich("Ohne E-Mail-Adresse geht keine Mail hinaus.")
    return await conn.fetchval(
        """
        insert into public.mails
          (org_id, art, contact_id, ticket_id, an, betreff, text, in_reply_to, referenzen,
           created_by, payload, kampagne_id)
        values ($1, $2::public.mail_art, $3, $4, $5, $6, $7, $8, $9, $10, $11::jsonb, $12)
        returning id
        """,
        org_id, art, contact_id, ticket_id, an, betreff.strip(), text, in_reply_to, referenzen,
        created_by, orjson.dumps(payload or {}).decode(), kampagne_id,
    )


async def _einstellungen(conn, org_id: UUID) -> dict[str, Any]:
    z = await conn.fetchrow("select * from public.org_settings where org_id = $1", org_id)
    return dict(z) if z else {}


async def _abmelde_url(
    conn, org_id: UUID, contact_id: UUID | None, einst: dict[str, Any], kampagne_id: UUID | None = None
) -> str | None:
    if contact_id is None:
        return None
    basis = basis_url(einst)
    if not basis:
        return None
    token = await links.anlegen(conn, org_id, "abmelden", contact_id=contact_id, kampagne_id=kampagne_id)
    return links.adresse(basis, "abmelden", token)


# ── Brevo: der zweite Weg für Marketing-Post ─────────────────────────────

@dataclass(frozen=True)
class Brevo:
    api_key: str
    absender: str
    absender_name: str | None

    @property
    def von(self) -> str:
        return formataddr((self.absender_name or "", self.absender))


def brevo_aus(einst: dict[str, Any] | None) -> Brevo | None:
    e = einst or {}
    key = (tresor.entschluesseln(e.get("brevo_api_key")) or "").strip()
    absender = (e.get("marketing_absender") or e.get("smtp_absender") or "").strip()
    if not key or not absender:
        return None
    return Brevo(api_key=key, absender=absender, absender_name=(e.get("marketing_absender_name") or e.get("smtp_absender_name") or None))


async def senden_brevo(konto: Brevo, nachricht: EmailMessage) -> None:
    """Dieselbe Nachricht, über die Brevo-API statt über SMTP."""
    import httpx

    kopf = {k: nachricht[k] for k in ("In-Reply-To", "References", "List-Unsubscribe", "List-Unsubscribe-Post") if nachricht.get(k)}
    daten = {
        "sender": {"email": konto.absender, **({"name": konto.absender_name} if konto.absender_name else {})},
        "to": [{"email": nachricht["To"]}],
        "subject": nachricht["Subject"],
        "textContent": nachricht.get_content(),
        "headers": {**kopf, "Message-ID": nachricht["Message-ID"]},
    }
    async with httpx.AsyncClient(timeout=20.0) as client:
        antwort = await client.post("https://api.brevo.com/v3/smtp/email", json=daten,
                                    headers={"api-key": konto.api_key, "accept": "application/json"})
    if antwort.status_code >= 300:
        raise RuntimeError(f"Brevo {antwort.status_code}: {antwort.text[:200]}")


def marketing_konto(einst: dict[str, Any]) -> Smtp | Brevo | None:
    """Wohin Marketing-Post geht: Brevo, wenn gewählt und eingerichtet,
    sonst das SMTP-Konto — mit dem Marketing-Absender, falls einer steht."""
    if (einst.get("marketing_versand") or "smtp") == "brevo":
        b = brevo_aus(einst)
        if b is not None:
            return b
    konto = smtp_aus(einst)
    if konto is None:
        return None
    absender = (einst.get("marketing_absender") or "").strip()
    if absender:
        from dataclasses import replace
        konto = replace(konto, absender=absender, absender_name=einst.get("marketing_absender_name") or konto.absender_name)
    return konto


async def versenden(
    conn,
    org_id: UUID,
    mail_id: UUID,
    *,
    sender: Sender | None = None,
) -> dict[str, Any]:
    """Schickt genau diese Zeile. Gibt sie danach zurück — mit Status.

    Ein abgelehnter Versand wirft nicht: `acquire_as` spannt eine
    Transaktion auf, und eine Exception darin nähme die Zeile samt
    Fehlergrund mit zurück. Der Aufrufer liest `status` und `fehler`.
    """
    # Der Sender wird erst unten aufgelöst, wenn das Konto feststeht: So
    # greift eine Attrappe am Modul auch für die Router, die keinen mitgeben.
    zeile = await conn.fetchrow("select * from public.mails where id = $1 and org_id = $2", mail_id, org_id)
    if zeile is None:
        raise Unmoeglich("Diese Mail gibt es nicht.")
    if zeile["status"] == "gesendet":
        return dict(zeile)

    einst = await _einstellungen(conn, org_id)
    # Wer diese Zeile eingereiht hat, schickt sie auch — unter seiner
    # Adresse. Marketing bleibt beim Absender der Organisation: Eine
    # Kampagne kommt von der Firma, nicht von einem Menschen, und der
    # Abmeldelink hängt an derselben Adresse.
    nutzer = None
    if zeile["art"] != "marketing" and zeile["created_by"]:
        nutzer = await conn.fetchrow(
            "select absender_email, absender_name, smtp_host, smtp_port, smtp_benutzer, "
            "       smtp_passwort, smtp_sicherheit "
            "from public.users where id = $1",
            zeile["created_by"],
        )
    konto: Smtp | Brevo | None = (
        marketing_konto(einst) if zeile["art"] == "marketing"
        else smtp_fuer(einst, dict(nutzer) if nutzer else None)
    )
    if konto is None:
        raise Unmoeglich("Kein SMTP-Konto hinterlegt. Server und Absenderadresse stehen unter Einstellungen → E-Mail.")
    if sender is None:
        sender = senden_brevo if isinstance(konto, Brevo) else senden_smtp

    message_id = zeile["message_id"] or neue_message_id(konto.absender)
    text = zeile["text"]
    abmelde_url = None
    if zeile["art"] == "marketing":
        abmelde_url = await _abmelde_url(conn, org_id, zeile["contact_id"], einst, zeile["kampagne_id"])
        if abmelde_url and "{{abmeldelink}}" not in text and abmelde_url not in text:
            text = f"{text.rstrip()}\n\n—\nKeine weiteren Mails? Hier abmelden: {abmelde_url}\n"
        text = rendern(text, {"abmeldelink": abmelde_url or ""})

    # Beacon liest genau ein Postfach je Organisation. Schickt jemand unter
    # eigener Adresse, käme die Antwort dort an, wo niemand sie einliest —
    # also zeigt `Reply-To` zurück auf das Postfach der Organisation.
    antwort_an = None
    if (einst.get("imap_host") or "").strip():
        antwort_an = (einst.get("smtp_absender") or "").strip() or None

    nachricht = nachricht_bauen(
        an=zeile["an"], betreff=zeile["betreff"], text=text, konto=konto, message_id=message_id,
        in_reply_to=zeile["in_reply_to"], referenzen=zeile["referenzen"], abmelde_url=abmelde_url,
        antwort_an=antwort_an,
    )
    try:
        await sender(konto, nachricht)
    except Exception as exc:
        grund = f"{type(exc).__name__}: {exc}"[:500]
        versuche = zeile["versuche"] + 1
        # Dreimal, dann liegen lassen — mit Grund. Ein Konto, das nicht
        # antwortet, braucht einen Menschen, keine vierte Wiederholung.
        status = "fehlgeschlagen" if versuche >= 3 else "wartend"
        await conn.execute(
            """
            update public.mails
               set status = $2::public.mail_status, versuche = $3, fehler = $4,
                   naechster_versuch = now() + make_interval(mins => 5 * $3)
             where id = $1
            """,
            mail_id, status, versuche, grund,
        )
        await conn.execute(
            "update public.org_settings set smtp_letzter_fehler = $1, smtp_zuletzt = now() where org_id = $2",
            grund, org_id,
        )
        z = await conn.fetchrow("select * from public.mails where id = $1", mail_id)
        return dict(z)
    await conn.execute(
        """
        update public.mails
           set status = 'gesendet', message_id = $2, text = $3, gesendet_am = now(),
               versuche = versuche + 1, fehler = null, naechster_versuch = null
         where id = $1
        """,
        mail_id, message_id, text,
    )
    await conn.execute(
        "update public.org_settings set smtp_letzter_fehler = null, smtp_zuletzt = now() where org_id = $1",
        org_id,
    )
    z = await conn.fetchrow("select * from public.mails where id = $1", mail_id)
    return dict(z)


async def verarbeiten(conn, org_id: UUID, *, hoechstens: int = 50, sender: Sender | None = None) -> dict[str, int]:
    """Ein Lauf über das Wartende. Fehler bleiben in der Zeile, nicht im Lauf."""
    faellig = await conn.fetch(
        """
        select id from public.mails
         where org_id = $1 and status = 'wartend'
           and (naechster_versuch is null or naechster_versuch <= now())
         order by created_at
         limit $2
        """,
        org_id, hoechstens,
    )
    bilanz = {"gesendet": 0, "gescheitert": 0}
    for z in faellig:
        try:
            zeile = await versenden(conn, org_id, z["id"], sender=sender)
        except Unmoeglich:
            # Ohne Konto geht in diesem Lauf nichts — die Zeilen warten.
            break
        bilanz["gesendet" if zeile["status"] == "gesendet" else "gescheitert"] += 1
    return bilanz


# ── Double-Opt-In ───────────────────────────────────────────────────────

async def einwilligung_anfragen(
    conn,
    org_id: UUID,
    contact_id: UUID,
    *,
    actor: UUID,
    sender: Sender | None = None,
) -> dict[str, Any]:
    """Schickt die Bestätigungsmail und merkt am Kontakt, dass sie draußen ist.
    Gibt die Zeile aus dem Buch zurück — mit Status.

    Das ist der einzige Weg zu `bestaetigt`, den die Anwendung von selbst
    geht. `bestandskunde` setzt ein Mensch, mit Absicht.
    """
    kontakt = await conn.fetchrow(
        """
        select k.id, k.email, k.first_name, k.last_name, k.job_title, f.name as company_name,
               k.marketing_einwilligung::text as einwilligung
          from public.contacts k
          left join public.companies f on f.id = k.company_id
         where k.id = $1 and k.deleted_at is null
        """,
        contact_id,
    )
    if kontakt is None:
        raise Unmoeglich("Kontakt nicht gefunden.")
    if not kontakt["email"]:
        raise Unmoeglich("Dieser Kontakt hat keine E-Mail-Adresse.")
    if kontakt["einwilligung"] == "bestaetigt":
        raise Unmoeglich("Die Einwilligung liegt schon vor.")

    einst = await _einstellungen(conn, org_id)
    basis = basis_url(einst)
    if not basis:
        raise Unmoeglich(
            "Die Adresse der öffentlichen Links ist nicht bekannt. Unter Einstellungen → E-Mail eintragen."
        )
    if smtp_aus(einst) is None:
        raise Unmoeglich("Kein SMTP-Konto hinterlegt. Server und Absenderadresse stehen unter Einstellungen → E-Mail.")

    token = await links.anlegen(conn, org_id, "bestaetigen", contact_id=contact_id, payload={"durch": str(actor)})
    werte = platzhalter_aus(dict(kontakt), bestaetigungslink=links.adresse(basis, "bestaetigen", token))
    betreff = rendern((einst.get("doi_betreff") or "").strip() or DOI_BETREFF, werte)
    text = rendern((einst.get("doi_text") or "").strip() or DOI_TEXT, werte)

    mail_id = await einreihen(
        conn, org_id, art="transaktional", an=kontakt["email"], betreff=betreff, text=text,
        contact_id=contact_id, created_by=actor, payload={"zweck": "double-opt-in"},
    )
    await conn.execute(
        """
        update public.contacts
           set marketing_einwilligung = 'angefragt',
               einwilligung_quelle = 'double-opt-in',
               einwilligung_am = null,
               einwilligung_nachweis = $2::jsonb,
               updated_at = now()
         where id = $1
        """,
        contact_id,
        orjson.dumps({"angefragt_am": datetime.now().astimezone().isoformat(), "durch": str(actor)}).decode(),
    )
    return await versenden(conn, org_id, mail_id, sender=sender)
