"""Wenn niemand mehr hereinkommt — der Weg zurück über den Datenordner.

Das Problem, für das es das gibt: Ein vergessenes Passwort war bisher ein
Fall für SSH, `kubectl exec` und ein Python-Schnipsel. Das kann Kai, und
ein Kunde kann es nicht.

**Die Hürde ist der Zugang zur Box, und das ist die richtige.** Wer an der
Box sitzt, kommt ohnehin an Dateien, Tresor und Einstellungen heran. Der
Code steht deshalb in einer Datei unter `/app/data`, die sich in der
Dateiverwaltung von Olares öffnen lässt. Kein Terminal, keine Mail — und
vor allem kein Weg, der über das Netz führt: Ein Rücksetzlink per Mail
wäre auf einer Box ohne eingerichtetes Postfach gar nicht zustellbar und
verlagerte das Vertrauen in ein Postfach, das wir nicht kennen.

Drei Entscheidungen, die dranhängen:

- **Die Datei ist der ganze Datensatz.** Kein Eintrag in der Datenbank.
  Damit kann ein zurückgespielter Abzug keinen alten Code wiederbeleben,
  und es gibt keine Tabelle, deren Zeilensicherheit man falsch bekommen
  kann.
- **Es gibt immer nur einen offenen Code.** Ein neuer überschreibt den
  alten. Sonst sammelten sich Codes an, von denen jeder für sich gültig
  bliebe.
- **Fünfzehn Minuten.** Lang genug, um die Dateiverwaltung zu öffnen,
  kurz genug, dass eine vergessene Datei nichts mehr wert ist.
"""

from __future__ import annotations

import hmac
import os
import pathlib
import secrets
from datetime import UTC, datetime, timedelta

from app.config import settings

DATEI = "passwort-zuruecksetzen.txt"
GUELTIG_MINUTEN = 15

# Zwölf Zeichen aus dem Hex-Alphabet, in Dreiergruppen — 48 Bit. Das ist
# gegen Raten reichlich, sobald die Bremse aus `anmeldung.py` mitzählt,
# und es lässt sich vom Bildschirm abtippen, ohne sich zu vertun.
_GRUPPEN = 3
_JE_GRUPPE = 4


def _pfad() -> pathlib.Path:
    return pathlib.Path(settings.app_data_dir) / DATEI


def code_neu() -> str:
    roh = secrets.token_hex(_GRUPPEN * _JE_GRUPPE // 2).upper()
    return "-".join(roh[i:i + _JE_GRUPPE] for i in range(0, len(roh), _JE_GRUPPE))


def anfordern(name: str, zugaenge: list[str], *, bekannt: bool) -> str | None:
    """Schreibt die Datei neben die Daten. Gibt den Code, wenn es einen gibt.

    **Die Datei entsteht auch, wenn der Name nicht stimmt.** Das ist kein
    Versehen: Auf einer fremden Box weiß der Mensch oft gar nicht, wie
    sein Zugang heißt — auf Kais Box heißt Marc `marc-bayer`, auf seiner
    eigenen anders. Die Seite darf ihm das nicht sagen, sie ist öffentlich.
    Die Datei darf es: Sie liegt hinter derselben Hürde wie der Code, und
    wer sie öffnen kann, hat ohnehin Zugriff auf alles.

    Zurückgegeben wird der Code nur an den Aufrufer, damit Tests ihn
    prüfen können — an den Browser geht er nie.
    """
    code = code_neu() if bekannt else None
    laeuft_ab = datetime.now(UTC) + timedelta(minutes=GUELTIG_MINUTEN)

    kopf = "Beacon — Passwort zurücksetzen\n==============================\n\n"
    if code is not None:
        teil = (
            f"Zugang:     {name}\n"
            f"Code:       {code}\n"
            f"Gültig bis: {laeuft_ab.astimezone().strftime('%d.%m.%Y %H:%M:%S %Z')}\n\n"
            "Diesen Code auf der Anmeldeseite von Beacon eingeben, zusammen\n"
            "mit dem Zugang oben und dem neuen Passwort.\n"
        )
    elif zugaenge:
        teil = (
            f"Für „{name}\" gibt es hier keinen Zugang mit Passwort.\n\n"
            "Auf dieser Box heißen die Zugänge:\n"
            + "".join(f"  - {z}\n" for z in zugaenge)
            + "\nEinen davon auf der Seite eintragen und noch einmal auf\n"
              "„Code erzeugen\" drücken.\n"
        )
    else:
        teil = (
            "Auf dieser Box hat noch niemand ein Passwort gesetzt.\n\n"
            "Solange das so ist, brauchen Sie keines: Öffnen Sie Beacon von\n"
            "der Olares-Oberfläche dieser Box aus, dann sind Sie drin. Setzen\n"
            "Sie dort unter Einstellungen ein Passwort — erst das schließt\n"
            "die Tür.\n"
        )

    fuss = (
        "\nWer diese Datei nicht angefordert hat, kann sie löschen. Nur wer\n"
        "an diese Box kommt, kann sie lesen.\n"
    )
    ziel = _pfad()
    ziel.parent.mkdir(parents=True, exist_ok=True)
    # Über `os.open` mit 0600, nicht über `write_text`: Sonst entstünde die
    # Datei kurz mit den Vorgaberechten, und in genau diesem Moment stünde
    # der Code für jeden lesbar da.
    kennung = os.open(ziel, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(kennung, "w", encoding="utf-8") as datei:
        datei.write(kopf + teil + fuss)
    return code


def _lesen() -> tuple[str, str, datetime] | None:
    """Zugang, Code und Ablauf aus der Datei — oder nichts."""
    ziel = _pfad()
    try:
        zeilen = ziel.read_text(encoding="utf-8").splitlines()
    except OSError:
        return None

    felder: dict[str, str] = {}
    for zeile in zeilen:
        if ":" in zeile:
            schluessel, _, wert = zeile.partition(":")
            felder.setdefault(schluessel.strip(), wert.strip())

    name, code = felder.get("Zugang", ""), felder.get("Code", "")
    if not name or not code:
        return None
    # Der Ablauf steht als lesbarer Zeitstempel in der Datei; maßgeblich
    # ist aber, wann sie geschrieben wurde. Ein Mensch, der die Zeile
    # ändert, verlängert damit nichts.
    try:
        geschrieben = datetime.fromtimestamp(ziel.stat().st_mtime, UTC)
    except OSError:
        return None
    return name, code, geschrieben + timedelta(minutes=GUELTIG_MINUTEN)


def _blank(code: str) -> str:
    """Nur die Zeichen, die den Code ausmachen.

    Er wird vom Bildschirm abgetippt. Bindestriche, Leerzeichen und
    Kleinschreibung sind Tippgewohnheiten, keine Aussage — und an einer
    davon soll ein Rettungsweg nicht scheitern.
    """
    return "".join(z for z in code if z.isalnum()).upper()


def stimmt(name: str, code: str) -> bool:
    """Passt dieser Code, für diesen Zugang, jetzt?

    Verglichen wird zeitkonstant. Ein Vergleich mit `==` verriete über
    die Dauer, wie viele Zeichen am Anfang schon stimmen.
    """
    gelesen = _lesen()
    if gelesen is None:
        return False
    erwartet_name, erwartet_code, laeuft_ab = gelesen
    if datetime.now(UTC) > laeuft_ab:
        return False
    passt_name = hmac.compare_digest(erwartet_name.strip().lower(), name.strip().lower())
    passt_code = hmac.compare_digest(_blank(erwartet_code), _blank(code))
    return passt_name and passt_code


def verbrauchen() -> None:
    """Nach dem Einlösen ist die Datei wertlos — und weg."""
    _pfad().unlink(missing_ok=True)


# Wo die Datei in der Dateien-App von Olares auftaucht. `/app/data` ist
# der Pfad **im Container** — in der Dateien-App gibt es ihn nicht, dort
# liegt derselbe Ordner unter „Data" mit dem Namen der App. Wer einem
# Menschen `/app/data` nennt, schickt ihn an eine Stelle, die er nicht
# finden kann; genau daran ist der erste Versuch gescheitert.
#
# Der Ordnername ist der Olares-App-Name, und der ist gleich dem
# Chart-Namen — `scripts/check-chart.sh` erzwingt das.
ORDNER_IN_DATEIEN = ("Data", "beacon")


def wo_liegt_die_datei() -> str:
    """Der Weg, den ein Mensch in der Dateien-App klickt."""
    return " › ".join((*ORDNER_IN_DATEIEN, DATEI))


def wo_liegt_die_datei_im_container() -> str:
    """Derselbe Ort, für die Kommandozeile — Log und Rettungsweg per SSH."""
    return f"{settings.app_data_dir.rstrip('/')}/{DATEI}"
