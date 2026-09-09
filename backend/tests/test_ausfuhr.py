"""Die aktuelle Liste als CSV.

Der wichtigste Test ist der letzte: Was Beacon exportiert, muss Beacon
wieder importieren können. Alles andere prüft, dass die Datei dieselbe
Auswahl trägt wie der Bildschirm — Filter, Spalten, Sortierung.
"""

import csv
import io

from app.db import acquire_as
from tests.conftest import klient_fuer


def gelesen(antwort) -> tuple[list[str], list[list[str]]]:
    text = antwort.text.lstrip("﻿")
    zeilen = list(csv.reader(io.StringIO(text, newline=""), delimiter=";"))
    return zeilen[0], zeilen[1:]


async def _kontakt(k, **felder):
    antwort = await k.post("/api/contacts", json=felder)
    assert antwort.status_code == 201, antwort.text
    return antwort.json()


# ---- Die Form der Datei ------------------------------------------------


async def test_die_datei_ist_fuer_deutsches_excel_gemacht(datenbank):
    """BOM gegen „BÃ¶hm", Semikolon gegen alles in einer Spalte."""
    async with klient_fuer("aus-form") as k:
        await _kontakt(k, first_name="Jörg", last_name="Müller")
        antwort = await k.get("/api/ausfuhr", params={"entity": "contacts"})
    assert antwort.status_code == 200
    assert antwort.text.startswith("﻿")
    assert ";" in antwort.text.splitlines()[0]
    assert "\r\n" in antwort.text
    assert "Müller" in antwort.text
    assert antwort.headers["content-disposition"].startswith("attachment")
    assert "beacon-kontakte-" in antwort.headers["content-disposition"]
    assert antwort.headers["x-content-type-options"] == "nosniff"


async def test_ohne_spaltenwahl_kommen_die_vorgabespalten(datenbank):
    async with klient_fuer("aus-vorgabe") as k:
        await _kontakt(k, first_name="Anna", last_name="Beispiel")
        kopf, _ = gelesen(await k.get("/api/ausfuhr", params={"entity": "contacts"}))
    assert kopf == ["Vorname", "Nachname", "Position", "Firma", "Kaufrolle", "E-Mail", "Stufe"]


async def test_die_spalten_kommen_in_der_gewaehlten_reihenfolge(datenbank):
    async with klient_fuer("aus-reihe") as k:
        await _kontakt(k, first_name="Anna", last_name="Beispiel", email="a@x.de")
        kopf, zeilen = gelesen(await k.get("/api/ausfuhr", params={
            "entity": "contacts", "spalten": "email,last_name,first_name",
        }))
    assert kopf == ["E-Mail", "Nachname", "Vorname"]
    assert zeilen == [["a@x.de", "Beispiel", "Anna"]]


async def test_alle_felder_auf_wunsch(datenbank):
    async with klient_fuer("aus-alle") as k:
        await _kontakt(k, first_name="Anna")
        kopf, _ = gelesen(await k.get("/api/ausfuhr", params={"entity": "contacts", "spalten": "alle"}))
    assert "Notizen" in kopf and "Angelegt" in kopf


async def test_eine_erfundene_spalte_wird_abgewiesen(datenbank):
    async with klient_fuer("aus-krumm") as k:
        antwort = await k.get("/api/ausfuhr", params={"entity": "contacts", "spalten": "gibtsnicht"})
    assert antwort.status_code == 400
    assert "gibtsnicht" in antwort.json()["detail"]


async def test_nur_kontakte_und_firmen(datenbank):
    async with klient_fuer("aus-objekt") as k:
        assert (await k.get("/api/ausfuhr", params={"entity": "tickets"})).status_code == 400


# ---- Dieselbe Auswahl wie auf dem Bildschirm ---------------------------


async def test_filter_und_sortierung_wirken(datenbank):
    async with klient_fuer("aus-filter") as k:
        await _kontakt(k, last_name="Zander", lifecycle_stage="customer")
        await _kontakt(k, last_name="Anders", lifecycle_stage="customer")
        await _kontakt(k, last_name="Draussen", lifecycle_stage="lead")
        _, zeilen = gelesen(await k.get("/api/ausfuhr", params={
            "entity": "contacts",
            "filter": '[{"feld":"lifecycle_stage","operator":"ist","wert":"customer"}]',
            "sort": "last_name", "richtung": "asc",
            "spalten": "last_name",
        }))
    assert zeilen == [["Anders"], ["Zander"]]


async def test_ein_kaputter_filter_kommt_als_fehler_nicht_als_halbe_datei(datenbank):
    async with klient_fuer("aus-kaputt") as k:
        antwort = await k.get("/api/ausfuhr", params={"entity": "contacts", "filter": "{kein json"})
    assert antwort.status_code == 400


async def test_eine_fremde_organisation_bekommt_nur_die_kopfzeile(datenbank):
    async with klient_fuer("aus-meins") as k:
        await _kontakt(k, first_name="Geheim", email="geheim@x.de")
    async with klient_fuer("aus-fremd") as fremd:
        kopf, zeilen = gelesen(await fremd.get("/api/ausfuhr", params={"entity": "contacts"}))
    assert kopf
    assert zeilen == []


# ---- Werte -------------------------------------------------------------


async def test_werte_stehen_so_da_wie_in_der_tabelle(datenbank):
    async with klient_fuer("aus-werte") as k:
        await k.post("/api/eigenschaften", json={
            "entity": "contacts", "label": "Normen", "kind": "multiselect",
            "options": [{"wert": "iso9001", "text": "ISO 9001"}, {"wert": "tisax", "text": "TISAX"}],
        })
        await _kontakt(
            k, first_name="Anna", lifecycle_stage="customer",
            custom={"normen": ["iso9001", "tisax"]},
        )
        wer = (await k.get("/api/mitglieder/wer")).json()
        _, zeilen = gelesen(await k.get("/api/ausfuhr", params={
            "entity": "contacts", "spalten": "lifecycle_stage,owner_id,custom.normen,created_at",
        }))
    stufe, besitzer, normen, angelegt = zeilen[0]
    assert stufe == "Kunde"
    assert besitzer == wer["display_name"]
    assert normen == "ISO 9001 | TISAX"
    assert len(angelegt) == 10 and angelegt[4] == "-"  # ISO, nicht 09.09.2026


async def test_eine_formel_verlaesst_die_box_entschaerft(datenbank):
    """Ein Firmenname aus einem Formular könnte `=HYPERLINK(...)` sein."""
    async with klient_fuer("aus-formel") as k:
        await k.post("/api/companies", json={"name": "=HYPERLINK(\"http://boese\")"})
        _, zeilen = gelesen(await k.get("/api/ausfuhr", params={
            "entity": "companies", "spalten": "name",
        }))
    assert zeilen[0][0].startswith("'=")


async def test_offene_betraege_stehen_als_euro_da(datenbank):
    async with klient_fuer("aus-euro") as k:
        await k.post("/api/companies", json={"name": "Acme"})
        _, zeilen = gelesen(await k.get("/api/ausfuhr", params={
            "entity": "companies", "spalten": "open_amount_cents",
        }))
    assert zeilen[0][0] == "0,00"


# ---- Protokoll ---------------------------------------------------------


async def test_jede_ausfuhr_steht_im_protokoll(datenbank):
    """Sie verlässt die Box — das gehört festgehalten."""
    async with klient_fuer("aus-audit") as k:
        await _kontakt(k, first_name="Anna")
        await k.get("/api/ausfuhr", params={"entity": "contacts", "spalten": "first_name"})
        wer = (await k.get("/api/mitglieder/wer")).json()
    async with acquire_as(wer["user_id"]) as conn:
        eintrag = await conn.fetchrow(
            "select diff from public.audit_log where action = 'export' order by created_at desc limit 1"
        )
    assert eintrag is not None
    assert '"zeilen": 1' in eintrag["diff"] or '"zeilen":1' in eintrag["diff"]


# ---- Der Rundlauf ------------------------------------------------------


async def test_was_beacon_schreibt_kann_beacon_wieder_lesen(datenbank):
    """Der Beweis, dass Ausfuhr und Einfuhr dieselbe Sprache sprechen."""
    async with klient_fuer("aus-rund-eins") as quelle:
        await _kontakt(
            quelle, first_name="Jörg", last_name="Müller",
            email="joerg@nordwind.de", lifecycle_stage="customer", job_title="Leiter Einkauf",
        )
        datei = (await quelle.get("/api/ausfuhr", params={"entity": "contacts"})).content

    async with klient_fuer("aus-rund-zwei") as ziel:
        antwort = await ziel.post(
            "/api/einfuhr", files={"datei": ("export.csv", datei, "text/csv")}
        )
        assert antwort.status_code == 200, antwort.text
        assert antwort.json()["angelegt"] == 1
        kontakt = (await ziel.get("/api/contacts")).json()[0]

    assert kontakt["first_name"] == "Jörg"
    assert kontakt["last_name"] == "Müller"
    assert kontakt["email"] == "joerg@nordwind.de"
    assert kontakt["lifecycle_stage"] == "customer"
    assert kontakt["job_title"] == "Leiter Einkauf"


async def test_dieselbe_datei_zweimal_legt_nichts_doppelt_an(datenbank):
    async with klient_fuer("aus-zweimal") as k:
        await _kontakt(k, first_name="Anna", email="anna@x.de")
        datei = (await k.get("/api/ausfuhr", params={"entity": "contacts"})).content
        antwort = await k.post("/api/einfuhr", files={"datei": ("e.csv", datei, "text/csv")})
    assert antwort.json()["angelegt"] == 0
    assert antwort.json()["gruende"] == {"dublette_email": 1}
