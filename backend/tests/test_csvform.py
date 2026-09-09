"""Die Form einer CSV — hinein und hinaus.

Ohne Datenbank: Hier steht kein Fachwissen über Kontakte, nur die Frage,
was aus einer Zelle wird und was in eine Zelle kommt. Der wichtigste Test
ist der Rundlauf: Was Beacon schreibt, muss Beacon wieder lesen können.
"""

from datetime import date, datetime

import pytest

from app import csvform
from app.csvform import Unlesbar, wert_lesen, zelle_text

STUFE = {
    "schluessel": "lifecycle_stage",
    "text": "Stufe",
    "art": "auswahl",
    "optionen": [
        {"wert": "lead", "text": "Kontakt"},
        {"wert": "customer", "text": "Kunde"},
    ],
}
NORMEN = {
    "schluessel": "custom.normen",
    "text": "Normen",
    "art": "mehrfachauswahl",
    "optionen": [
        {"wert": "iso9001", "text": "ISO 9001"},
        {"wert": "tisax", "text": "TISAX"},
    ],
}
TEXT = {"schluessel": "name", "text": "Firma", "art": "text", "optionen": []}
ZAHL = {"schluessel": "employee_count", "text": "Mitarbeiter", "art": "zahl", "optionen": []}
BETRAG = {"schluessel": "open_amount_cents", "text": "Offener Wert", "art": "zahl", "optionen": []}
DATUM = {"schluessel": "created_at", "text": "Angelegt", "art": "datum", "optionen": []}
JANEIN = {"schluessel": "custom.aktiv", "text": "Aktiv", "art": "jaNein", "optionen": []}
PERSON = {"schluessel": "owner_id", "text": "Besitzer", "art": "person", "optionen": []}


# ---- Bytes und Trennzeichen -------------------------------------------


@pytest.mark.parametrize(
    "roh,erwartet",
    [
        ("Name\nBöhm".encode(), "utf-8"),
        (b"\xef\xbb\xbf" + "Name\nBöhm".encode(), "utf-8-sig"),
        ("Name\nBöhm".encode("cp1252"), "cp1252"),
        (b"\xff\xfe" + "Name\nBöhm".encode("utf-16-le"), "utf-16"),
    ],
)
def test_umlaute_ueberleben_jede_uebliche_kodierung(roh, erwartet):
    text, kodierung = csvform.bytes_lesen(roh)
    assert "Böhm" in text
    assert kodierung == erwartet


def test_eine_excel_datei_wird_beim_namen_genannt():
    """`.xlsx` ist ein Zip-Archiv — als Text gelesen wäre es Kauderwelsch."""
    with pytest.raises(Unlesbar) as fehler:
        csvform.bytes_lesen(b"PK\x03\x04irgendwas")
    assert "Excel" in fehler.value.satz
    assert "CSV UTF-8" in fehler.value.satz


def test_eine_binaerdatei_wird_abgewiesen():
    with pytest.raises(Unlesbar):
        csvform.bytes_lesen(b"\x89PNG\x00\x00\x00\x00")


@pytest.mark.parametrize("trenner", [";", ",", "\t"])
def test_das_trennzeichen_wird_erkannt(trenner):
    text = trenner.join(["Vorname", "Nachname", "E-Mail"]) + "\n" + trenner.join(["Anna", "Beispiel", "a@b.de"])
    erkannt, rest = csvform.trenner_erkennen(text)
    assert erkannt == trenner
    assert rest == text


def test_die_sep_zeile_von_excel_ist_eine_anweisung_keine_kopfzeile():
    """Wer sie stehen lässt, liest die ganze Datei um eine Zeile verschoben."""
    trenner, rest = csvform.trenner_erkennen("sep=;\nVorname;Nachname\nAnna;Beispiel\n")
    assert trenner == ";"
    assert rest.startswith("Vorname;")


def test_eine_zelle_darf_einen_zeilenumbruch_enthalten():
    text = 'Firma;Beschreibung\r\nAcme;"Zeile 1\nZeile 2"\r\n'
    kopf, zeilen = csvform.zeilen_lesen(text, ";")
    assert kopf == ["Firma", "Beschreibung"]
    assert zeilen == [["Acme", "Zeile 1\nZeile 2"]]


def test_leerzeilen_zaehlen_nicht_mit():
    kopf, zeilen = csvform.zeilen_lesen("A;B\r\n1;2\r\n\r\n;\r\n3;4\r\n", ";")
    assert kopf == ["A", "B"]
    assert zeilen == [["1", "2"], ["3", "4"]]


def test_zu_viele_zeilen_werden_abgewiesen(monkeypatch):
    monkeypatch.setattr(csvform, "MAX_ZEILEN", 3)
    with pytest.raises(Unlesbar) as fehler:
        csvform.zeilen_lesen("A\r\n" + "x\r\n" * 5, ";")
    assert fehler.value.grund == "zeilen"


# ---- Werte lesen -------------------------------------------------------


@pytest.mark.parametrize("eingabe", ["Kunde", "customer", "kunde", "CUSTOMER", " Kunde "])
def test_eine_auswahl_nimmt_text_und_wert(eingabe):
    """Die Ausfuhr schreibt den Text, ein Vorsystem liefert oft den Wert."""
    assert wert_lesen(STUFE, eingabe) == "customer"


def test_ein_unbekannter_auswahlwert_nennt_das_feld():
    with pytest.raises(Unlesbar) as fehler:
        wert_lesen(STUFE, "Superkunde")
    assert fehler.value.grund == "unbekannte_auswahl"
    assert "Stufe" in fehler.value.satz


def test_mehrfachauswahl_wird_am_strich_getrennt():
    assert wert_lesen(NORMEN, "ISO 9001 | TISAX") == ["iso9001", "tisax"]
    assert wert_lesen(NORMEN, "tisax") == ["tisax"]


@pytest.mark.parametrize(
    "eingabe,erwartet",
    [("12,5", 12.5), ("12.5", 12.5), ("1.250,50", 1250.5), ("14500 €", 14500), ("1.250", 1250), ("-3", -3)],
)
def test_zahlen_kommen_in_beiden_schreibweisen_an(eingabe, erwartet):
    assert wert_lesen(ZAHL, eingabe) == erwartet


def test_ein_centbetrag_wird_aus_euro_gerechnet():
    assert wert_lesen(BETRAG, "14500,00") == 1_450_000


@pytest.mark.parametrize("eingabe", ["2026-09-09", "09.09.2026", "9.9.2026", "09.09.26"])
def test_datum_iso_und_deutsch(eingabe):
    assert wert_lesen(DATUM, eingabe) == date(2026, 9, 9)


def test_ein_kaputtes_datum_sagt_was_erwartet_wird():
    with pytest.raises(Unlesbar) as fehler:
        wert_lesen(DATUM, "irgendwann")
    assert "2026-09-09" in fehler.value.satz


@pytest.mark.parametrize("eingabe", ["Ja", "ja", "true", "1", "x", "yes", "wahr"])
def test_ja_in_allen_schreibweisen(eingabe):
    assert wert_lesen(JANEIN, eingabe) is True


@pytest.mark.parametrize("eingabe", ["Nein", "false", "0", "no"])
def test_nein_in_allen_schreibweisen(eingabe):
    assert wert_lesen(JANEIN, eingabe) is False


def test_eine_person_wird_ueber_den_namen_gefunden():
    kennung = "11111111-1111-1111-1111-111111111111"
    assert str(wert_lesen(PERSON, "Kai Böhm", {"kai böhm": kennung})) == kennung


def test_eine_unbekannte_person_faellt_auf():
    with pytest.raises(Unlesbar) as fehler:
        wert_lesen(PERSON, "Niemand", {})
    assert fehler.value.grund == "unbekannte_person"


def test_eine_leere_zelle_ist_kein_wert():
    assert wert_lesen(STUFE, "   ") is None
    assert wert_lesen(ZAHL, "") is None


# ---- Werte schreiben ---------------------------------------------------


def test_geschrieben_wird_was_ein_mensch_lesen_will():
    assert zelle_text(STUFE, "customer", {}) == "Kunde"
    assert zelle_text(NORMEN, ["iso9001", "tisax"], {}) == "ISO 9001 | TISAX"
    assert zelle_text(JANEIN, True, {}) == "Ja"
    assert zelle_text(DATUM, datetime(2026, 9, 9, 14, 30), {}) == "2026-09-09"
    assert zelle_text(BETRAG, 1_450_000, {}) == "14500,00"
    assert zelle_text(ZAHL, 12.5, {}) == "12,5"
    assert zelle_text(PERSON, "abc", {"abc": "Kai Böhm"}) == "Kai Böhm"
    assert zelle_text(TEXT, None, {}) == ""


@pytest.mark.parametrize(
    "feld,wert",
    [(STUFE, "customer"), (NORMEN, ["iso9001", "tisax"]), (JANEIN, True), (ZAHL, 42), (BETRAG, 1_450_000)],
)
def test_rundlauf_geschrieben_und_wieder_gelesen(feld, wert):
    """Was Beacon exportiert, muss Beacon importieren können."""
    assert wert_lesen(feld, zelle_text(feld, wert, {})) == wert


def test_das_datum_ueberlebt_den_rundlauf():
    assert wert_lesen(DATUM, zelle_text(DATUM, date(2026, 9, 9), {})) == date(2026, 9, 9)


# ---- Formelschutz ------------------------------------------------------


def test_eine_formel_wird_beim_schreiben_entschaerft():
    """Ein Firmenname aus einem Formular könnte `=HYPERLINK(...)` sein."""
    assert zelle_text(TEXT, "=HYPERLINK(\"http://boese\")", {}).startswith("'=")


def test_und_beim_lesen_wieder_hergestellt():
    geschrieben = zelle_text(TEXT, "=SUMME(A1)", {})
    assert wert_lesen(TEXT, geschrieben) == "=SUMME(A1)"


def test_eine_telefonnummer_bleibt_lesbar():
    """`+49 …` beginnt mit einem Formelzeichen und darf trotzdem stimmen."""
    geschrieben = zelle_text(TEXT, "+49 170 1234567", {})
    assert geschrieben == "'+49 170 1234567"
    assert wert_lesen(TEXT, geschrieben) == "+49 170 1234567"


def test_ein_apostroph_im_text_bleibt_stehen():
    """Nur das Zeichen, das wir selbst gesetzt haben, kommt wieder weg."""
    assert wert_lesen(TEXT, "'Zitat' Meier") == "'Zitat' Meier"


# ---- Die Datei als Ganzes ---------------------------------------------


def test_die_datei_traegt_bom_semikolon_und_crlf():
    stuecke = list(csvform.csv_zeilen(["Vorname", "Nachname"], [["Anna", "Beispiel"]]))
    ganz = "".join(stuecke)
    assert ganz.startswith("﻿")
    assert "Vorname;Nachname\r\n" in ganz
    assert ganz.endswith("Anna;Beispiel\r\n")


def test_die_ausfuhr_kommt_stueckweise():
    """Zwanzigtausend Zeilen dürfen nie ganz im Speicher liegen."""
    stuecke = list(csvform.csv_zeilen(["A"], [[str(i)] for i in range(450)]))
    assert len(stuecke) == 4  # Kopf + 200 + 200 + 50
