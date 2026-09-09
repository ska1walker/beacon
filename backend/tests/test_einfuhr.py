"""Kontakte und Firmen aus einer CSV.

Geprüft wird vor allem, was **nicht** passiert: Nichts wird überschrieben,
eine Vorschau schreibt nichts, ein Fehler in der Mitte hinterlässt keinen
halben Import, und fünftausend Zeilen lösen keine fünftausend
Anreicherungsläufe aus.
"""

from uuid import UUID

import pytest

from app import einfuhr, sicherung
from app.db import acquire, acquire_as
from tests.conftest import klient_fuer

KOPF_HUBSPOT_DE = "Vorname;Nachname;E-Mail-Adresse;Zugehöriges Unternehmen;Lifecycle-Phase"
KOPF_HUBSPOT_EN = "First Name;Last Name;Email;Associated Company;Lifecycle Stage"


def datei(text: str, name: str = "kontakte.csv", kodierung: str = "utf-8") -> dict:
    return {"datei": (name, text.encode(kodierung), "text/csv")}


async def _vorschau(k, text: str, **form):
    return await k.post("/api/einfuhr/vorschau", data=form, files=datei(text))


async def _einfuehren(k, text: str, **form):
    return await k.post("/api/einfuhr", data=form, files=datei(text))


# ---- Vorlage -----------------------------------------------------------


async def test_die_vorlage_traegt_die_beschriftungen_der_felder(datenbank):
    async with klient_fuer("ein-vorlage") as k:
        antwort = await k.get("/api/einfuhr/vorlage", params={"entity": "contacts"})
    assert antwort.status_code == 200
    assert antwort.headers["content-disposition"].startswith("attachment")
    kopf = antwort.text.lstrip("﻿").splitlines()[0]
    assert "Vorname" in kopf and "E-Mail" in kopf and "Firma" in kopf
    # Was nicht importierbar ist, steht auch nicht in der Vorlage.
    assert "Marketing-Einwilligung" not in kopf
    assert "Angelegt" not in kopf


# ---- Vorschau ----------------------------------------------------------


async def test_die_vorschau_schreibt_nichts(datenbank):
    async with klient_fuer("ein-trocken") as k:
        vorher = len((await k.get("/api/contacts")).json())
        antwort = await _vorschau(k, f"{KOPF_HUBSPOT_DE}\nAnna;Beispiel;anna@x.de;Acme GmbH;Kunde\n")
        assert antwort.status_code == 200, antwort.text
        assert antwort.json()["bilanz"]["anlegen"] == 1
        assert len((await k.get("/api/contacts")).json()) == vorher


@pytest.mark.parametrize("kopf", [KOPF_HUBSPOT_DE, KOPF_HUBSPOT_EN])
async def test_hubspot_kopfzeilen_werden_erkannt(datenbank, kopf):
    async with klient_fuer("ein-alias") as k:
        v = (await _vorschau(k, f"{kopf}\nAnna;Beispiel;anna@x.de;Acme GmbH;Kunde\n")).json()
    assert v["entity"] == "contacts"
    assert [s["ziel"] for s in v["spalten"]] == [
        "first_name", "last_name", "email", "firma_name", "lifecycle_stage",
    ]
    assert v["nicht_zugeordnet"] == []


async def test_die_vorschau_nennt_die_kodierung(datenbank):
    """Ein Umlautfehler ohne Absender ist schwer zu finden."""
    async with klient_fuer("ein-kodierung") as k:
        antwort = await k.post(
            "/api/einfuhr/vorschau",
            files={"datei": ("k.csv", "Vorname;Nachname\nJörg;Müller\n".encode("cp1252"), "text/csv")},
        )
    assert antwort.json()["kodierung"] == "cp1252"
    assert antwort.json()["trenner"] == ";"


async def test_eine_firmendatei_wird_als_solche_erkannt(datenbank):
    async with klient_fuer("ein-erraten") as k:
        v = (await _vorschau(k, "Name des Unternehmens;Branche;Ort\nAcme GmbH;Bau;Hamburg\n")).json()
    assert v["entity"] == "companies"


# ---- Anwenden ----------------------------------------------------------


async def test_umlaute_kommen_unversehrt_an(datenbank):
    async with klient_fuer("ein-umlaut") as k:
        antwort = await k.post(
            "/api/einfuhr",
            files={"datei": ("k.csv", "Vorname;Nachname\nJörg;Müller\n".encode("cp1252"), "text/csv")},
        )
        assert antwort.status_code == 200, antwort.text
        namen = [(c["first_name"], c["last_name"]) for c in (await k.get("/api/contacts")).json()]
    assert ("Jörg", "Müller") in namen


async def test_zwei_kontakte_derselben_neuen_firma_ergeben_eine_firma(datenbank):
    """Sonst stünde die Firma nach dem Import doppelt im Bestand."""
    async with klient_fuer("ein-firma") as k:
        antwort = await _einfuehren(k, (
            f"{KOPF_HUBSPOT_DE}\n"
            "Anna;Beispiel;anna@nordwind.de;Nordwind Logistik GmbH;Kunde\n"
            "Bert;Beispiel;bert@nordwind.de;Nordwind Logistik;Kunde\n"
        ))
        assert antwort.status_code == 200, antwort.text
        assert antwort.json()["angelegt"] == 2
        assert antwort.json()["firmen_angelegt"] == 1
        firmen = (await k.get("/api/companies")).json()
        kontakte = (await k.get("/api/contacts")).json()
    assert [f["name"] for f in firmen] == ["Nordwind Logistik GmbH"]
    assert {c["company_id"] for c in kontakte} == {firmen[0]["id"]}


async def test_eine_vorhandene_firma_wird_gefunden_nicht_verdoppelt(datenbank):
    async with klient_fuer("ein-treffer") as k:
        vorhanden = (await k.post("/api/companies", json={"name": "Nordwind Logistik"})).json()
        antwort = await _einfuehren(
            k, f"{KOPF_HUBSPOT_DE}\nAnna;Beispiel;a@n.de;Nordwind Logistik GmbH;Kunde\n"
        )
        assert antwort.json()["firmen_angelegt"] == 0
        kontakte = (await k.get("/api/contacts")).json()
    assert kontakte[0]["company_id"] == vorhanden["id"]


async def test_die_domain_geht_dem_namen_vor(datenbank):
    """Zwei Firmen können gleich heißen; eine Domain gehört nur einer."""
    async with klient_fuer("ein-domain") as k:
        richtig = (await k.post("/api/companies", json={"name": "Nord AG", "domain": "nordwind.de"})).json()
        await k.post("/api/companies", json={"name": "Nordwind Logistik"})
        antwort = await k.post(
            "/api/einfuhr",
            files=datei(
                "Vorname;E-Mail;Firma;Firmen-Domain\n"
                "Anna;a@n.de;Nordwind Logistik;https://www.nordwind.de/kontakt\n"
            ),
        )
        assert antwort.status_code == 200, antwort.text
        kontakte = (await k.get("/api/contacts")).json()
    assert kontakte[0]["company_id"] == richtig["id"]


async def test_eine_vorhandene_mailadresse_wird_uebersprungen(datenbank):
    async with klient_fuer("ein-dublette") as k:
        await k.post("/api/contacts", json={"first_name": "Alt", "email": "doppelt@x.de"})
        antwort = await _einfuehren(k, (
            "Vorname;E-Mail\nNeu;doppelt@x.de\nAndere;frisch@x.de\n"
        ))
    ergebnis = antwort.json()
    assert ergebnis["angelegt"] == 1
    assert ergebnis["gruende"] == {"dublette_email": 1}
    assert ergebnis["details"][0]["zeile"] == 2


async def test_eine_dublette_in_der_datei_selbst_faellt_auf(datenbank):
    async with klient_fuer("ein-selbst") as k:
        antwort = await _einfuehren(k, "Vorname;E-Mail\nA;gleich@x.de\nB;gleich@x.de\n")
    assert antwort.json()["angelegt"] == 1
    assert antwort.json()["gruende"] == {"dublette_datei": 1}


async def test_eine_unbekannte_stufe_kippt_nur_ihre_zeile(datenbank):
    """Und die Optionsliste wird dabei nicht erweitert."""
    async with klient_fuer("ein-stufe") as k:
        antwort = await _einfuehren(k, (
            "Vorname;E-Mail;Stufe\nGut;gut@x.de;Kunde\nBoese;boese@x.de;Superkunde\n"
        ))
        felder = (await k.get("/api/ansichten/felder", params={"entity": "contacts"})).json()
    assert antwort.json()["angelegt"] == 1
    assert antwort.json()["gruende"] == {"unbekannte_auswahl": 1}
    stufe = next(f for f in felder["felder"] if f["schluessel"] == "lifecycle_stage")
    assert "Superkunde" not in [o["text"] for o in stufe["optionen"]]


async def test_eigene_eigenschaften_kommen_ueber_ihre_beschriftung(datenbank):
    async with klient_fuer("ein-eigen") as k:
        await k.post("/api/eigenschaften", json={
            "entity": "contacts", "label": "Normen", "kind": "multiselect",
            "options": [{"wert": "iso9001", "text": "ISO 9001"}, {"wert": "tisax", "text": "TISAX"}],
        })
        await k.post("/api/eigenschaften", json={
            "entity": "contacts", "label": "Prüftermin", "kind": "date",
        })
        antwort = await _einfuehren(k, (
            "Vorname;E-Mail;Normen;Prüftermin\nAnna;a@x.de;ISO 9001 | TISAX;09.09.2026\n"
        ))
        assert antwort.status_code == 200, antwort.text
        kontakt = (await k.get("/api/contacts")).json()[0]
    assert kontakt["custom"]["normen"] == ["iso9001", "tisax"]
    assert kontakt["custom"]["prueftermin"] == "2026-09-09"


async def test_ein_unbekannter_besitzer_kippt_die_zeile_nicht(datenbank):
    """Eine fremde Datei nennt Menschen, die es hier nicht gibt."""
    async with klient_fuer("ein-besitzer") as k:
        v = (await _vorschau(k, "Vorname;E-Mail;Besitzer\nAnna;a@x.de;Niemand Fremdes\n")).json()
        assert v["bilanz"]["anlegen"] == 1
        assert any("Besitzer" in h for h in v["hinweise"])
        antwort = await _einfuehren(k, "Vorname;E-Mail;Besitzer\nAnna;a@x.de;Niemand Fremdes\n")
        kontakt = (await k.get("/api/contacts")).json()[0]
        wer = (await k.get("/api/mitglieder/wer")).json()
    assert antwort.json()["angelegt"] == 1
    assert kontakt["owner_id"] == wer["user_id"]


async def test_ohne_quellspalte_traegt_der_datensatz_import(datenbank):
    async with klient_fuer("ein-quelle") as k:
        await _einfuehren(k, "Vorname;E-Mail\nAnna;a@x.de\n")
        kontakt = (await k.get("/api/contacts")).json()[0]
    assert kontakt["source"] == einfuhr.HERKUNFT


async def test_eine_einfuhr_reichert_nicht_an(datenbank):
    """Fünftausend Hintergrundläufe wären ein Selbst-DoS und eine Rechnung."""
    async with klient_fuer("ein-ruhe") as k:
        await _einfuehren(k, "Vorname;E-Mail\nAnna;a@x.de\nBert;b@x.de\n")
        kontakt = (await k.get("/api/contacts")).json()[0]
        laeufe = (await k.get(
            "/api/anreicherungen", params={"entity": "contacts", "entity_id": kontakt["id"]}
        )).json()
    assert laeufe == []


async def test_der_import_steht_im_protokoll(datenbank):
    async with klient_fuer("ein-protokoll") as k:
        ergebnis = (await _einfuehren(k, "Vorname;E-Mail\nAnna;a@x.de\n")).json()
        liste = (await k.get("/api/einfuhr")).json()
        eine = (await k.get(f"/api/einfuhr/{ergebnis['id']}")).json()
    assert liste[0]["dateiname"] == "kontakte.csv"
    assert liste[0]["angelegt"] == 1
    assert liste[0]["status"] == "fertig"
    assert eine["angelegt"] == 1


async def test_jeder_datensatz_traegt_die_einfuhr_im_audit(datenbank):
    """Sonst ließe sich später nicht sagen, woher ein Datensatz kam."""
    async with klient_fuer("ein-audit") as k:
        await _einfuehren(k, "Vorname;E-Mail\nAnna;a@x.de\n", entity="contacts")
        wer = (await k.get("/api/mitglieder/wer")).json()
    async with acquire_as(wer["user_id"]) as conn:
        diffs = await conn.fetch(
            "select diff from public.audit_log where entity = 'contacts' and action = 'create'"
        )
    assert any("kontakte.csv" in str(d["diff"]) for d in diffs)


# ---- Wenn es schiefgeht ------------------------------------------------


async def test_ein_fehler_in_der_mitte_hinterlaesst_nichts(datenbank, monkeypatch):
    """Ein halber Import ist schlimmer als keiner — man sieht ihm nichts an."""
    from app.routers import contacts as kontakt_router

    echt = kontakt_router.einfuegen
    zaehler = {"n": 0}

    async def stolpern(conn, user, payload, custom_json):
        zaehler["n"] += 1
        if zaehler["n"] == 3:
            raise RuntimeError("Absicht")
        return await echt(conn, user, payload, custom_json)

    monkeypatch.setattr(kontakt_router, "einfuegen", stolpern)
    async with klient_fuer("ein-rollback") as k:
        antwort = await _einfuehren(k, "Vorname;E-Mail\nA;a@x.de\nB;b@x.de\nC;c@x.de\n")
        assert antwort.status_code == 500
        assert (await k.get("/api/contacts")).json() == []
        liste = (await k.get("/api/einfuhr")).json()
    assert liste[0]["status"] == "fehlgeschlagen"
    assert liste[0]["angelegt"] == 0


async def test_eine_zu_grosse_datei_wird_abgewiesen(datenbank, monkeypatch):
    monkeypatch.setattr("app.csvform.MAX_BYTES", 200)
    async with klient_fuer("ein-gross") as k:
        antwort = await _einfuehren(k, "Vorname;E-Mail\n" + "A;a@x.de\n" * 100)
    assert antwort.status_code == 413


async def test_zu_viele_zeilen_werden_abgewiesen(datenbank, monkeypatch):
    monkeypatch.setattr("app.csvform.MAX_ZEILEN", 3)
    async with klient_fuer("ein-viele") as k:
        antwort = await _einfuehren(k, "Vorname;E-Mail\n" + "".join(f"A;a{i}@x.de\n" for i in range(9)))
    assert antwort.status_code == 413


async def test_eine_excel_datei_wird_erklaert(datenbank):
    async with klient_fuer("ein-xlsx") as k:
        antwort = await k.post(
            "/api/einfuhr/vorschau",
            files={"datei": ("mappe.xlsx", b"PK\x03\x04irgendwas", "application/vnd.ms-excel")},
        )
    assert antwort.status_code == 400
    assert "CSV UTF-8" in antwort.json()["detail"]


async def test_eine_zuordnung_muss_zur_spaltenzahl_passen(datenbank):
    async with klient_fuer("ein-krumm") as k:
        antwort = await _vorschau(k, "Vorname;E-Mail\nA;a@x.de\n", zuordnung='["first_name"]')
    assert antwort.status_code == 400
    assert "2" in antwort.json()["detail"]


async def test_ein_erfundenes_zielfeld_wird_abgelehnt(datenbank):
    async with klient_fuer("ein-erfunden") as k:
        antwort = await _vorschau(k, "A;B\n1;2\n", zuordnung='["gibtsnicht", null]')
    assert antwort.status_code == 400


async def test_eine_firma_ohne_namen_geht_nicht(datenbank):
    async with klient_fuer("ein-namenlos") as k:
        v = (await _vorschau(k, "Branche;Ort\nBau;Hamburg\n", entity="companies")).json()
    assert v["bilanz"]["anlegen"] == 0
    assert v["bilanz"]["gruende"] == {"leer": 1}


# ---- Rechte und Mandanten ----------------------------------------------


async def test_ein_mitglied_darf_nicht_einfuehren(datenbank):
    """Ein Import schreibt tausendfach in einen fremd gepflegten Bestand."""
    async with klient_fuer("ein-gast") as gast:
        wer = (await gast.get("/api/mitglieder/wer")).json()
        async with acquire() as conn:
            await conn.execute(
                "update public.user_org_roles set role = 'member' where user_id = $1",
                UUID(wer["user_id"]),
            )
        antwort = await _vorschau(gast, "Vorname;E-Mail\nA;a@x.de\n")
        assert antwort.status_code == 403
        # Lesen darf es weiter — die Ausfuhr zeigt nur, was die Liste zeigt.
        assert (await gast.get("/api/einfuhr")).status_code == 200


async def test_eine_fremde_organisation_sieht_den_import_nicht(datenbank):
    async with klient_fuer("ein-meins") as k:
        await _einfuehren(k, "Vorname;E-Mail\nAnna;geheim@x.de\n")
    async with klient_fuer("ein-fremd") as fremd:
        assert (await fremd.get("/api/einfuhr")).json() == []


def test_einfuhren_stehen_im_abzug():
    """Sonst wäre nach einer Neuinstallation nicht mehr erklärbar, was kam."""
    assert "einfuhren" in sicherung.TABELLEN


# ---- Die reinen Funktionen ---------------------------------------------


@pytest.mark.parametrize(
    "name,erwartet",
    [
        ("Nordwind Logistik GmbH", "nordwind logistik"),
        ("Nordwind Logistik", "nordwind logistik"),
        ("Meyer & Co. KG", "meyer"),
        ("Hanseatic Legal Partner mbB", "hanseatic legal partner"),
        ("GmbH", "gmbh"),
    ],
)
def test_der_firmenschluessel_wirft_nur_hinten_weg(name, erwartet):
    assert einfuhr.firmenschluessel(name) == erwartet


@pytest.mark.parametrize(
    "eingabe",
    ["acme.de", "www.acme.de", "https://www.acme.de", "http://acme.de/kontakt?x=1", " ACME.de "],
)
def test_domains_werden_auf_denselben_kern_gebracht(eingabe):
    assert einfuhr.domain_normalisieren(eingabe) == "acme.de"
