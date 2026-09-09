"""CSV lesen und schreiben — die Form, in beide Richtungen.

Hier steht kein Fachwissen über Kontakte oder Firmen, nur die Frage, wie
ein Wert in einer Zelle aussieht und was aus einer Zelle wieder wird.
`einfuhr.py` und `routers/ausfuhr.py` benutzen dieselben Funktionen, damit
eine exportierte Datei wieder hereinkommt.

Fünf Entscheidungen, die man beim Lesen des Codes sonst für Willkür hält:

- **Semikolon und BOM beim Schreiben.** Der Abnehmer ist deutsches Excel
  per Doppelklick. Ohne BOM steht dort „BÃ¶hm", mit Komma steht die ganze
  Zeile in einer Spalte, weil Excel das Listentrennzeichen aus den
  Regionaleinstellungen liest. Beim *Lesen* wird `;`, `,` und Tab erkannt,
  der Rundlauf hängt also nicht am Trennzeichen.
- **Komma als Dezimalzeichen.** Bei Semikolon-Trennung erwartet deutsches
  Excel es so. `12.5` wird dort sonst zum **12. Mai**.
- **ISO-Datum.** Eindeutig, sortiert richtig, und jedes Excel-Gebietsschema
  erkennt es. Gelesen wird zusätzlich `TT.MM.JJJJ`, weil Menschen so tippen.
- **`|` zwischen Mehrfachwerten.** `;` ist das Trennzeichen der Datei und
  HubSpots bekannte Falle (siehe Migration 0015), `,` steht mitten in
  Werten („ISO 9001, 27001"), `|` in Geschäftstext praktisch nie.
- **Formelschutz.** Eine Zelle, die mit `=`, `+`, `-` oder `@` beginnt, ist
  für Excel eine Formel. Ein Firmenname aus einem Formular könnte
  `=HYPERLINK(...)` sein; ein führendes `'` macht daraus wieder Text. Die
  Einfuhr nimmt genau dieses eine Zeichen wieder weg.
"""

from __future__ import annotations

import csv
import io
import re
from collections.abc import Iterable, Iterator
from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

# 10 MB und 20.000 Datenzeilen. Zwanzigtausend Zeilen mal zwanzig Spalten
# sind zwei bis vier Megabyte; das passt doppelt (Bytes und geparste
# Zeilen) in den Speicher des Pods. Darüber ist es ein Umzug und gehört
# zu `pg_dump`, nicht in ein Formular.
MAX_BYTES = 10 * 1024 * 1024
MAX_ZEILEN = 20_000

TRENNER_AUSFUHR = ";"
MEHRFACH_TRENNER = " | "
JA, NEIN = "Ja", "Nein"

# Zeichen, mit denen eine Zelle für Excel zur Formel wird.
FORMELZEICHEN = ("=", "+", "-", "@", "\t", "\r")

# Kodierungen in der Reihenfolge, in der geraten wird. Ein BOM wird vorher
# gesondert erkannt — `utf-8-sig` liest auch BOM-lose Dateien und hieße
# dann in der Vorschau „UTF-8 mit BOM", obwohl keines da war. `cp1252` ist
# das, was Excel unter „CSV (Trennzeichen-getrennt)" schreibt; `latin-1`
# scheitert nie und ist deshalb die letzte Zeile der Verteidigung.
KODIERUNGEN = ("utf-8", "cp1252", "latin-1")

_ZAHL_ZEICHEN = re.compile(r"[^0-9,.\-]")
_DEUTSCHES_DATUM = re.compile(r"^(\d{1,2})\.(\d{1,2})\.(\d{2}|\d{4})$")

WAHR = {"ja", "j", "true", "wahr", "1", "yes", "y", "x"}
FALSCH = {"nein", "n", "false", "falsch", "0", "no", ""}


class Unlesbar(ValueError):  # noqa: N818 — die Fachbegriffe hier sind deutsch
    """Eine Zelle, aus der sich kein Wert machen lässt.

    Trägt einen festen `grund`-Schlüssel, damit die Oberfläche daraus
    einen Satz machen kann, und den Text, der nicht ging.
    """

    def __init__(self, grund: str, text: str, satz: str) -> None:
        super().__init__(satz)
        self.grund = grund
        self.text = text
        self.satz = satz


# ---------------------------------------------------------------------------
# Hereinkommen: Bytes → Text → Zeilen
# ---------------------------------------------------------------------------


def bytes_lesen(roh: bytes) -> tuple[str, str]:
    """Text und der Name der Kodierung, mit der es gelungen ist.

    Der Name geht in die Vorschau. Stumm zu raten wäre der schlechtere
    Weg: Ein Umlautfehler ohne Absender ist schwer zu finden, und der
    Mensch vor dem Bildschirm weiß sofort, ob „Windows-1252" plausibel
    ist.
    """
    if roh[:4] == b"PK\x03\x04":
        raise Unlesbar(
            "kodierung", "",
            "Das ist eine Excel-Datei (.xlsx). Speichern Sie sie in Excel "
            "über „Speichern unter“ als „CSV UTF-8“.",
        )
    if roh[:2] in (b"\xff\xfe", b"\xfe\xff"):
        art = "utf-16"
        return roh.decode(art), art
    if roh[:3] == b"\xef\xbb\xbf":
        art = "utf-8-sig"
        return roh.decode(art), art
    for art in KODIERUNGEN:
        try:
            text = roh.decode(art)
        except UnicodeDecodeError:
            continue
        # Ein NUL-Byte ist in einer CSV nie beabsichtigt — dann ist es
        # eine Binärdatei, die zufällig durch `latin-1` gegangen wäre.
        if "\x00" in text:
            raise Unlesbar("kodierung", "", "Das sieht nicht nach einer Textdatei aus.")
        return text, art
    raise Unlesbar("kodierung", "", "Die Datei lässt sich nicht als Text lesen.")


def trenner_erkennen(text: str) -> tuple[str, str]:
    """Trennzeichen und der Text ohne eine etwaige `sep=`-Zeile.

    Excel schreibt manchmal `sep=;` in die erste Zeile. Sie ist eine
    Anweisung an Excel, keine Kopfzeile — wer sie stehen lässt, liest die
    ganze Datei um eine Zeile verschoben.
    """
    if text[:4].lower() == "sep=":
        zeilenende = text.find("\n")
        kopf = text[:zeilenende if zeilenende >= 0 else len(text)]
        rest = text[zeilenende + 1:] if zeilenende >= 0 else ""
        trenner = kopf[4:].strip("\r\n") or TRENNER_AUSFUHR
        return trenner[:1], rest

    probe = "\n".join(text.splitlines()[:20])
    try:
        return csv.Sniffer().sniff(probe, delimiters=";,\t").delimiter, text
    except csv.Error:
        # Der Sniffer gibt auf, wenn eine Datei nur eine Spalte hat. Dann
        # zählt die Kopfzeile: Was am häufigsten vorkommt, trennt.
        erste = text.splitlines()[0] if text.splitlines() else ""
        beste = max((";", ",", "\t"), key=erste.count)
        return (beste if erste.count(beste) else TRENNER_AUSFUHR), text


def zeilen_lesen(text: str, trenner: str) -> tuple[list[str], list[list[str]]]:
    """Kopfzeile und Datenzeilen. Leerzeilen fallen weg."""
    leser = csv.reader(io.StringIO(text, newline=""), delimiter=trenner)
    try:
        kopf = [s.strip().lstrip("﻿") for s in next(leser)]
    except StopIteration:
        raise Unlesbar("kodierung", "", "Die Datei ist leer.") from None

    zeilen: list[list[str]] = []
    for zeile in leser:
        if not any(z.strip() for z in zeile):
            continue
        zeilen.append(zeile)
        if len(zeilen) > MAX_ZEILEN:
            raise Unlesbar(
                "zeilen", "",
                f"Mehr als {MAX_ZEILEN:n} Zeilen. Teilen Sie die Datei auf.",
            )
    return kopf, zeilen


# ---------------------------------------------------------------------------
# Formelschutz
# ---------------------------------------------------------------------------


def formelschutz(text: str) -> str:
    return "'" + text if text[:1] in FORMELZEICHEN else text


def formelschutz_entfernen(text: str) -> str:
    """Nur das eine Zeichen, das wir selbst gesetzt haben."""
    return text[1:] if text[:1] == "'" and text[1:2] in FORMELZEICHEN else text


# ---------------------------------------------------------------------------
# Hinausgehen: Wert → Zelle
# ---------------------------------------------------------------------------


def _zahl_text(wert: Any) -> str:
    """Ganze Zahlen ohne Komma, gebrochene mit.

    `Decimal` kommt aus jeder `sum()`-Spalte und ist kein `int` — wer nur
    auf `int` prüft, schreibt „14500.00" statt „14500".
    """
    if isinstance(wert, int) or (isinstance(wert, Decimal | float) and float(wert).is_integer()):
        return str(int(wert))
    return f"{wert}".replace(".", ",")


def zelle_text(feld: dict[str, Any], wert: Any, personen: dict[str, str]) -> str:
    """Was ein Mensch in der Zelle sehen will.

    Das Gegenstück zu `Zelle` in `frontend/components/segmentliste.tsx`:
    dieselben Entscheidungen, damit die Datei aussieht wie die Tabelle.
    """
    if wert is None or wert == "":
        return ""
    art = feld.get("art", "text")

    if art == "person":
        return personen.get(str(wert), "")
    if art == "jaNein":
        return JA if wert else NEIN
    if art == "auswahl":
        for o in feld.get("optionen") or []:
            if o["wert"] == str(wert):
                return formelschutz(o["text"])
        return formelschutz(str(wert))
    if art == "mehrfachauswahl":
        werte = wert if isinstance(wert, list) else [wert]
        texte = {o["wert"]: o["text"] for o in feld.get("optionen") or []}
        return MEHRFACH_TRENNER.join(texte.get(str(w), str(w)) for w in werte)
    if art == "datum":
        if isinstance(wert, datetime):
            return wert.date().isoformat()
        if isinstance(wert, date):
            return wert.isoformat()
        return str(wert)[:10]
    if art == "zahl":
        # Centbeträge stehen als Euro in der Datei — „14500,00" ist die
        # Zahl, die ein Mensch in Excel weiterrechnet, „1450000" nicht.
        if feld.get("schluessel", "").endswith("_cents"):
            return f"{float(wert) / 100:.2f}".replace(".", ",")
        return _zahl_text(wert)
    return formelschutz(str(wert))


class Stapel:
    """Sammelt Zeilen und gibt sie stückweise als CSV-Text heraus.

    Damit eine Ausfuhr mit zwanzigtausend Zeilen nie vollständig im
    Speicher des Pods liegt — und damit die synchrone Vorlage und die
    asynchrone Ausfuhr dieselbe Schreibweise benutzen.
    """

    STUECK = 200

    def __init__(self) -> None:
        self._puffer = io.StringIO()
        self._schreiber = csv.writer(
            self._puffer, delimiter=TRENNER_AUSFUHR, lineterminator="\r\n"
        )
        self._offen = 0

    def _abholen(self) -> str:
        text = self._puffer.getvalue()
        self._puffer.seek(0)
        self._puffer.truncate(0)
        self._offen = 0
        return text

    def kopfzeile(self, kopf: list[str]) -> str:
        """Das BOM gehört an den Anfang der Datei, nicht an jede Zeile."""
        self._schreiber.writerow(kopf)
        return "\ufeff" + self._abholen()

    def dazu(self, zeile: list[str]) -> str | None:
        """Gibt ein Stück zurück, sobald genug beisammen ist."""
        self._schreiber.writerow(zeile)
        self._offen += 1
        return self._abholen() if self._offen >= self.STUECK else None

    def rest(self) -> str:
        return self._abholen() if self._offen else ""


def csv_zeilen(kopf: list[str], zeilen: Iterable[list[str]]) -> Iterator[str]:
    """Die ganze Datei als Strom von Stücken."""
    stapel = Stapel()
    yield stapel.kopfzeile(kopf)
    for zeile in zeilen:
        stueck = stapel.dazu(zeile)
        if stueck:
            yield stueck
    letztes = stapel.rest()
    if letztes:
        yield letztes


# ---------------------------------------------------------------------------
# Hereinkommen: Zelle → Wert
# ---------------------------------------------------------------------------


def _datum_lesen(text: str) -> date:
    treffer = _DEUTSCHES_DATUM.match(text)
    if treffer:
        tag, monat, jahr = (int(t) for t in treffer.groups())
        return date(jahr + 2000 if jahr < 100 else jahr, monat, tag)
    return date.fromisoformat(text[:10])


def _zahl_lesen(text: str) -> float | int:
    """`12,5`, `12.5`, `1.250,50` und `14500 €` ergeben dasselbe.

    Die Regel für die Mehrdeutigkeit: Stehen Punkt **und** Komma da,
    trennt das letzte von beiden die Nachkommastellen. Steht nur ein
    Punkt und danach genau drei Ziffern, ist er ein Tausenderpunkt.
    """
    roh = _ZAHL_ZEICHEN.sub("", text.strip())
    if not roh:
        raise ValueError(text)
    if "," in roh and "." in roh:
        if roh.rfind(",") > roh.rfind("."):
            roh = roh.replace(".", "").replace(",", ".")
        else:
            roh = roh.replace(",", "")
    elif "," in roh:
        roh = roh.replace(",", ".")
    elif re.fullmatch(r"-?\d{1,3}(\.\d{3})+", roh):
        roh = roh.replace(".", "")
    zahl = float(roh)
    return int(zahl) if zahl.is_integer() else zahl


def wert_lesen(
    feld: dict[str, Any], text: str, personen_nach_name: dict[str, str] | None = None
) -> Any:
    """Aus einer Zelle den Wert, den die Datenbank erwartet.

    Wirft `Unlesbar` mit einem festen Grund. Auswahlfelder nehmen den
    Text **und** den gespeicherten Wert an — die Ausfuhr schreibt den
    Text, ein Vorsystem liefert oft den Wert, und beides soll gehen.
    """
    roh = formelschutz_entfernen(text.strip())
    if not roh:
        return None
    art = feld.get("art", "text")
    beschriftung = feld.get("text", feld.get("schluessel", ""))

    if art == "auswahl":
        for o in feld.get("optionen") or []:
            if roh.casefold() in (o["wert"].casefold(), o["text"].casefold()):
                return o["wert"]
        raise Unlesbar(
            "unbekannte_auswahl", roh,
            f"„{roh}“ ist kein Wert von „{beschriftung}“.",
        )

    if art == "mehrfachauswahl":
        texte = [t.strip() for t in roh.split("|") if t.strip()]
        werte: list[str] = []
        for t in texte:
            for o in feld.get("optionen") or []:
                if t.casefold() in (o["wert"].casefold(), o["text"].casefold()):
                    werte.append(o["wert"])
                    break
            else:
                raise Unlesbar(
                    "unbekannte_auswahl", t,
                    f"„{t}“ ist kein Wert von „{beschriftung}“.",
                )
        return werte

    if art == "jaNein":
        if roh.casefold() in WAHR:
            return True
        if roh.casefold() in FALSCH:
            return False
        raise Unlesbar("ungueltiger_wert", roh, f"„{roh}“ ist weder Ja noch Nein.")

    if art == "datum":
        try:
            return _datum_lesen(roh)
        except ValueError:
            raise Unlesbar(
                "ungueltiger_wert", roh,
                f"„{roh}“ ist kein Datum. Erwartet wird 2026-09-09 oder 09.09.2026.",
            ) from None

    if art == "zahl":
        try:
            zahl = _zahl_lesen(roh)
        except ValueError:
            raise Unlesbar("ungueltiger_wert", roh, f"„{roh}“ ist keine Zahl.") from None
        if feld.get("schluessel", "").endswith("_cents"):
            return round(zahl * 100)
        return zahl

    if art == "person":
        gefunden = (personen_nach_name or {}).get(roh.casefold())
        if gefunden is None:
            raise Unlesbar(
                "unbekannte_person", roh,
                f"„{roh}“ ist niemand in dieser Organisation.",
            )
        return UUID(gefunden)

    return roh[:2000]
