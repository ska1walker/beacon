"""Eigene Eigenschaften.

Die Datenbank sieht nur JSON. Ob ein Datum ein Datum ist, prüft allein
das Backend — und genau das wird hier nachgehalten.
"""

import pytest

from app.eigenschaften import Ungueltig, pruefen, schluessel_aus
from tests.conftest import klient_fuer


class D(dict):
    """Ein Ersatz für die asyncpg-Zeile — Zugriff wie auf ein Record."""


def _def(key, kind, options=None):
    return D(key=key, label=key.capitalize(), kind=kind, options=options or [])


# ---- Prüfung ------------------------------------------------------------

def test_schluessel_aus_beschriftung():
    assert schluessel_aus("Wartungsvertrag bis") == "wartungsvertrag_bis"
    assert schluessel_aus("Serverraum vorhanden?") == "serverraum_vorhanden"
    assert schluessel_aus("Größe (m²)") == "groesse_m"
    assert schluessel_aus("   ") == "eigenschaft"


def test_typen_werden_erzwungen():
    defs = [_def("zahl", "number"), _def("datum", "date"), _def("ja", "bool"),
            _def("wahl", "select", ["Nord", "Süd"])]
    ok = pruefen({"zahl": "12.5", "datum": "2026-12-24", "ja": "nein", "wahl": "Süd"}, defs)
    assert ok == {"zahl": 12.5, "datum": "2026-12-24", "ja": False, "wahl": "Süd"}


def test_unbekannter_schluessel_wird_abgelehnt():
    """Ein Tippfehler im Client landete sonst als stiller Fremdschlüssel im JSON."""
    with pytest.raises(Ungueltig, match="Unbekannte"):
        pruefen({"gibtsnicht": 1}, [_def("zahl", "number")])


def test_falscher_typ_nennt_das_feld():
    with pytest.raises(Ungueltig, match="Zahl"):
        pruefen({"zahl": "zwölf"}, [_def("zahl", "number")])
    with pytest.raises(Ungueltig, match="Datum"):
        pruefen({"datum": "Weihnachten"}, [_def("datum", "date")])
    with pytest.raises(Ungueltig, match="erlaubt nur"):
        pruefen({"wahl": "West"}, [_def("wahl", "select", ["Nord", "Süd"])])


def test_bool_ist_keine_zahl():
    with pytest.raises(Ungueltig):
        pruefen({"zahl": True}, [_def("zahl", "number")])


def test_leer_loescht():
    assert pruefen({"zahl": None, "datum": ""}, [_def("zahl", "number"), _def("datum", "date")]) == {
        "zahl": None, "datum": None,
    }


# ---- Über die API -------------------------------------------------------

async def test_definieren_setzen_lesen(datenbank):
    async with klient_fuer("eig-a") as k:
        d = (await k.post("/api/eigenschaften", json={
            "entity": "companies", "label": "Serverraum vorhanden", "kind": "bool"})).json()
        assert d["key"] == "serverraum_vorhanden"

        firma = (await k.post("/api/companies", json={
            "name": "Eigenschaftsfirma", "custom": {"serverraum_vorhanden": True}})).json()
        assert firma["custom"] == {"serverraum_vorhanden": True}

        gelesen = (await k.get(f"/api/companies/{firma['id']}")).json()
        assert gelesen["custom"]["serverraum_vorhanden"] is True

        liste = (await k.get("/api/eigenschaften?entity=companies")).json()
        assert [x["key"] for x in liste] == ["serverraum_vorhanden"]


async def test_patch_fuehrt_zusammen_statt_zu_ersetzen(datenbank):
    """Wer eine Eigenschaft ändert, schickt nur diese eine."""
    async with klient_fuer("eig-b") as k:
        for label, kind in (("Kammer", "text"), ("Wartung bis", "date")):
            await k.post("/api/eigenschaften", json={"entity": "deals", "label": label, "kind": kind})
        deal = (await k.post("/api/deals", json={
            "name": "D", "custom": {"kammer": "Hamburg", "wartung_bis": "2027-01-31"}})).json()

        geaendert = (await k.patch(f"/api/deals/{deal['id']}", json={"custom": {"kammer": "Lüneburg"}})).json()
        assert geaendert["custom"] == {"kammer": "Lüneburg", "wartung_bis": "2027-01-31"}

        geleert = (await k.patch(f"/api/deals/{deal['id']}", json={"custom": {"wartung_bis": None}})).json()
        assert geleert["custom"]["wartung_bis"] is None
        assert geleert["custom"]["kammer"] == "Lüneburg"


async def test_ungueltiger_wert_ist_400_mit_klartext(datenbank):
    async with klient_fuer("eig-c") as k:
        await k.post("/api/eigenschaften", json={
            "entity": "contacts", "label": "Region", "kind": "select", "options": ["Nord", "Süd"]})
        antwort = await k.post("/api/contacts", json={"first_name": "A", "custom": {"region": "West"}})
    assert antwort.status_code == 400
    assert "erlaubt nur" in antwort.json()["detail"]


async def test_auswahl_ohne_werte_wird_abgelehnt(datenbank):
    async with klient_fuer("eig-d") as k:
        antwort = await k.post("/api/eigenschaften", json={"entity": "deals", "label": "Leer", "kind": "select"})
    assert antwort.status_code == 400


async def test_doppelter_schluessel_je_objekt(datenbank):
    async with klient_fuer("eig-e") as k:
        await k.post("/api/eigenschaften", json={"entity": "companies", "label": "Kammer"})
        zweimal = await k.post("/api/eigenschaften", json={"entity": "companies", "label": "kammer"})
        anders = await k.post("/api/eigenschaften", json={"entity": "contacts", "label": "Kammer"})
    assert zweimal.status_code == 409
    assert anders.status_code == 201, "derselbe Schlüssel an einem anderen Objekt ist erlaubt"


async def test_abschalten_behaelt_werte(datenbank):
    """Ein Löschen, das Werte mitnähme, wäre ein Datenverlust hinter einem Knopf."""
    async with klient_fuer("eig-f") as k:
        d = (await k.post("/api/eigenschaften", json={"entity": "companies", "label": "Alt"})).json()
        firma = (await k.post("/api/companies", json={"name": "F", "custom": {"alt": "bleibt"}})).json()

        assert (await k.delete(f"/api/eigenschaften/{d['id']}")).status_code == 204
        assert (await k.get("/api/eigenschaften?entity=companies")).json() == []
        assert len((await k.get("/api/eigenschaften?entity=companies&auch_inaktive=true")).json()) == 1

        nachher = (await k.get(f"/api/companies/{firma['id']}")).json()
        assert nachher["custom"] == {"alt": "bleibt"}
        # Schreiben geht nicht mehr — die Definition ist abgeschaltet.
        assert (await k.patch(f"/api/companies/{firma['id']}", json={"custom": {"alt": "neu"}})).status_code == 400


async def test_typ_und_schluessel_sind_fest(datenbank):
    async with klient_fuer("eig-g") as k:
        d = (await k.post("/api/eigenschaften", json={"entity": "deals", "label": "Zahl", "kind": "number"})).json()
        geaendert = (await k.patch(f"/api/eigenschaften/{d['id']}", json={"label": "Anzahl Nutzer", "kind": "text", "key": "x"})).json()
    assert geaendert["label"] == "Anzahl Nutzer"
    assert geaendert["kind"] == "number"
    assert geaendert["key"] == "zahl"


async def test_fremde_definitionen_bleiben_unsichtbar(datenbank):
    async with klient_fuer("eig-h") as a, klient_fuer("eig-i") as b:
        await a.post("/api/eigenschaften", json={"entity": "companies", "label": "Geheim"})
        assert (await b.get("/api/eigenschaften")).json() == []
        # und B kann den Schlüssel auch nicht benutzen
        antwort = await b.post("/api/companies", json={"name": "X", "custom": {"geheim": "1"}})
    assert antwort.status_code == 400


async def test_suche_findet_eigene_werte(datenbank):
    async with klient_fuer("eig-j") as k:
        await k.post("/api/eigenschaften", json={"entity": "companies", "label": "Kammer"})
        await k.post("/api/companies", json={"name": "Suchfirma", "custom": {"kammer": "Steuerberaterkammer Niedersachsen"}})
        ergebnis = (await k.post("/api/fragen", json={"frage": "Niedersachsen"})).json()
    assert any(f["titel"] == "Suchfirma" for f in ergebnis["fundstellen"])


async def test_sicherung_nimmt_definitionen_mit(datenbank, tmp_path, monkeypatch):
    from app import sicherung
    monkeypatch.setattr(sicherung.settings, "app_data_dir", str(tmp_path))
    async with klient_fuer("eig-k") as k:
        await k.post("/api/eigenschaften", json={"entity": "deals", "label": "Kammer"})
        bilanz = (await k.post("/api/sicherung")).json()
    assert bilanz["zeilen"]["property_definitions"] == 1
