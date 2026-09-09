"""Zugangsdaten liegen nicht mehr im Klartext in der Datenbank.

SMTP- und IMAP-Passwörter, API-Schlüssel für Sprachmodell, Suche,
Sprachausgabe und Brevo — sie alle müssen im **Original** wieder
herauskommen, weil sich der Dienst damit anmeldet. Ein Hash wie beim
Anmeldepasswort ginge also nicht. Was bleibt, ist Verschlüsselung, und
dann entscheidet alles daran, wo der Schlüssel liegt.

**Der Schlüssel liegt nicht in der Datenbank.** Er steht als Datei unter
`/app/data`, mit Rechten 0600, und wird beim ersten Bedarf erzeugt. Damit
schützt das hier genau eine, aber sehr wirkliche Sache: einen Abzug der
Datenbank. Ein Postgres-Dump, ein kopiertes Laufwerk, eine Sicherung, die
irgendwo landet — daraus lässt sich nichts mehr benutzen.

**Wogegen es nicht schützt, und das gehört dazugesagt:** Wer im Pod ist,
liest die Schlüsseldatei genauso wie die Datenbank. Gegen einen Angreifer
mit Zugriff auf den laufenden Dienst hilft nur, dass es ihn nicht gibt.
Ein Tresor, dessen Schlüssel danebenliegt, ist trotzdem besser als eine
offene Kiste — er trennt zwei Dinge, die sonst zusammen wegkommen.

**Alt bleibt lesbar.** `entschluesseln` gibt zurück, was es nicht kennt.
Eine Datenbank voller Klartext funktioniert also weiter, und `nachziehen`
holt sie beim Start einmal nach.
"""

from __future__ import annotations

import base64
import os
import pathlib
import secrets

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.config import settings

# Die Marke sagt zweierlei: dass der Wert verschlüsselt ist, und mit
# welchem Verfahren. Ohne sie ließe sich nicht unterscheiden, ob ein Wert
# noch aus der Zeit davor stammt.
MARKE = "beacon1:"
DATEI = "tresor.key"

_schluessel: bytes | None = None


def _pfad() -> pathlib.Path:
    return pathlib.Path(settings.app_data_dir) / DATEI


def schluessel() -> bytes:
    """Der Schlüssel dieser Installation — beim ersten Bedarf erzeugt.

    Er liegt neben den Daten und **nicht** in der Datenbank, damit ein
    Abzug der Datenbank allein nichts hergibt. `/app/data` überlebt eine
    Deinstallation; ginge der Schlüssel verloren, wären die Zugangsdaten
    unlesbar und müssten neu eingetragen werden.
    """
    global _schluessel
    if _schluessel is not None:
        return _schluessel

    p = _pfad()
    if p.exists():
        _schluessel = base64.urlsafe_b64decode(p.read_text().strip())
        return _schluessel

    p.parent.mkdir(parents=True, exist_ok=True)
    neu = AESGCM.generate_key(bit_length=256)
    # Erst mit 0600 anlegen, dann schreiben: Zwischen `write_text` und
    # `chmod` läge sonst ein Moment, in dem die Datei für alle lesbar ist.
    fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as datei:
        datei.write(base64.urlsafe_b64encode(neu).decode())
    _schluessel = neu
    return neu


def verschluesseln(klartext: str | None) -> str | None:
    """Aus einem Geheimnis wird ein Wert, der ohne Schlüssel nichts sagt.

    Leeres bleibt leer: `None` heißt „nicht hinterlegt", und daraus einen
    Kryptotext zu machen würde die Bedeutung verlieren.
    """
    if not klartext:
        return klartext
    if klartext.startswith(MARKE):
        return klartext
    nonce = secrets.token_bytes(12)
    geheim = AESGCM(schluessel()).encrypt(nonce, klartext.encode(), None)
    return MARKE + base64.urlsafe_b64encode(nonce + geheim).decode()


def entschluesseln(wert: str | None) -> str | None:
    """Zurück in den Klartext — und was nicht verschlüsselt war, bleibt.

    Die Nachsicht ist Absicht: Eine Datenbank aus der Zeit vor dem Tresor
    trägt Klartext, und der muss weiter funktionieren. Ein Wert, der die
    Marke trägt, sich aber nicht öffnen lässt, gibt `None` — dann fehlt
    der Schlüssel, und ein halb entschlüsselter Rest wäre schlimmer als
    die ehrliche Antwort „nicht da".
    """
    if not wert or not wert.startswith(MARKE):
        return wert
    roh = base64.urlsafe_b64decode(wert[len(MARKE):])
    try:
        return AESGCM(schluessel()).decrypt(roh[:12], roh[12:], None).decode()
    except (InvalidTag, ValueError, OSError):
        return None


# Was verschlüsselt liegt. Die Liste ist der Vertrag: Wer eine Spalte mit
# einem Geheimnis ergänzt, trägt sie hier ein — sonst bleibt sie im
# Klartext, und niemand merkt es.
# Je Tabelle: die Spalte, die eine Zeile eindeutig macht, und die
# Geheimnisse darin. `org_settings` hat kein `id` — sie hängt an `org_id`.
SPALTEN: dict[str, tuple[str, tuple[str, ...]]] = {
    "org_settings": ("org_id", (
        "smtp_passwort", "imap_passwort", "llm_api_key", "suche_api_key",
        "tts_api_key", "brevo_api_key", "mail_endpoint_secret",
    )),
    "users": ("id", ("smtp_passwort",)),
    "webhook_sources": ("id", ("secret",)),
}


async def nachziehen(conn) -> int:
    """Holt nach, was vor dem Tresor angelegt wurde — einmal beim Start.

    Ohne diesen Lauf bliebe alles Vorhandene im Klartext liegen, bis es
    zufällig jemand neu speichert. Läuft ohne Nutzerkontext und muss das
    auch: `org_settings` steht unter Zeilensicherheit, deshalb wird die
    Sicherheit für die Dauer der Transaktion abgeschaltet — das geht nur
    als Eigentümerin der Tabellen, also aus dem Dienst heraus.
    """
    gezogen = 0
    for tabelle, (schluesselspalte, spalten) in SPALTEN.items():
        for spalte in spalten:
            async with conn.transaction():
                await conn.execute(f"alter table public.{tabelle} disable row level security")
                try:
                    zeilen = await conn.fetch(
                        f"select {schluesselspalte} as kennung, {spalte} as wert "  # noqa: S608
                        f"from public.{tabelle} "
                        f"where {spalte} is not null and {spalte} <> '' "
                        f"and {spalte} not like '{MARKE}%'"
                    )
                    for z in zeilen:
                        await conn.execute(
                            f"update public.{tabelle} set {spalte} = $2 "  # noqa: S608
                            f"where {schluesselspalte} = $1",
                            z["kennung"], verschluesseln(z["wert"]),
                        )
                        gezogen += 1
                finally:
                    await conn.execute(f"alter table public.{tabelle} enable row level security")
    return gezogen
