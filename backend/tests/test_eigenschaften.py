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


# ---- Mehrfachauswahl ----------------------------------------------------
#
# Eine Eigenschaft, die mehrere Werte gleichzeitig trägt. Drei Dinge sind
# daran heikel: dass nur Bekanntes durchkommt, dass die Reihenfolge fest
# ist, und dass eine leere Auswahl leer heißt und nicht „[]".

ZERTIFIKATE = ["ISO 9001", "ISO 27001", "TISAX"]


def test_mehrfachauswahl_nimmt_mehrere_werte():
    defs = [_def("zert", "multiselect", ZERTIFIKATE)]
    assert pruefen({"zert": ["TISAX", "ISO 9001"]}, defs) == {"zert": ["ISO 9001", "TISAX"]}


def test_mehrfachauswahl_ordnet_nach_der_definition():
    """Zwei Datensätze mit derselben Auswahl sollen gleich aussehen.

    Sonst hängt die Reihenfolge daran, in welcher jemand geklickt hat, und
    jeder Vergleich zweier Zeilen wird zur Suche.
    """
    defs = [_def("zert", "multiselect", ZERTIFIKATE)]
    a = pruefen({"zert": ["TISAX", "ISO 27001"]}, defs)
    b = pruefen({"zert": ["ISO 27001", "TISAX"]}, defs)
    assert a == b == {"zert": ["ISO 27001", "TISAX"]}


def test_mehrfachauswahl_wirft_doppelte_weg():
    defs = [_def("zert", "multiselect", ZERTIFIKATE)]
    assert pruefen({"zert": ["TISAX", "TISAX"]}, defs) == {"zert": ["TISAX"]}


def test_mehrfachauswahl_lehnt_unbekanntes_ab():
    defs = [_def("zert", "multiselect", ZERTIFIKATE)]
    with pytest.raises(Ungueltig, match="Erfunden"):
        pruefen({"zert": ["TISAX", "Erfunden"]}, defs)


def test_einzelner_text_wird_zur_liste():
    """Ein Import liefert selten schon ein Array."""
    defs = [_def("zert", "multiselect", ZERTIFIKATE)]
    assert pruefen({"zert": "TISAX"}, defs) == {"zert": ["TISAX"]}


def test_leere_auswahl_ist_leer_nicht_eine_leere_liste():
    """`[]` im JSON ließe „ist leer" nicht greifen."""
    defs = [_def("zert", "multiselect", ZERTIFIKATE)]
    assert pruefen({"zert": []}, defs) == {"zert": None}
    assert pruefen({"zert": None}, defs) == {"zert": None}


def test_option_traegt_wert_und_beschriftung():
    """Die alte Kurzform bleibt gültig, die neue trennt beide Namen."""
    from app.eigenschaften import optionen, optionstexte, optionswerte

    alt = optionen(["Nord", "Süd"])
    assert alt == [
        {"wert": "Nord", "text": "Nord", "verborgen": False},
        {"wert": "Süd", "text": "Süd", "verborgen": False},
    ]

    neu = [{"wert": "nord", "text": "Region Nord"}, {"wert": "alt", "text": "Alt", "verborgen": True}]
    assert optionswerte(neu) == ["nord", "alt"]
    assert optionswerte(neu, auch_verborgene=False) == ["nord"]
    assert optionstexte(neu) == ["Region Nord", "Alt"]


def test_archivierter_wert_bleibt_gueltig():
    """Wer den Wert aus dem Verkehr zieht, entwertet die Datensätze nicht."""
    defs = [_def("zert", "multiselect", [
        {"wert": "ISO 9001", "text": "ISO 9001"},
        {"wert": "TISAX", "text": "TISAX", "verborgen": True},
    ])]
    assert pruefen({"zert": ["TISAX"]}, defs) == {"zert": ["TISAX"]}


# ---- Über die Schnittstelle --------------------------------------------

async def test_mehrfachauswahl_am_datensatz(datenbank):
    async with klient_fuer("eig-multi") as k:
        d = (await k.post("/api/eigenschaften", json={
            "entity": "companies", "label": "Zertifikate", "kind": "multiselect",
            "options": ZERTIFIKATE,
        })).json()
        assert d["key"] == "zertifikate"
        assert [o["wert"] for o in d["options"]] == ZERTIFIKATE
        assert all(o["text"] == o["wert"] and not o["verborgen"] for o in d["options"])

        firma = (await k.post("/api/companies", json={"name": "Werft Nord"})).json()
        gesetzt = (await k.patch(f"/api/companies/{firma['id']}", json={
            "custom": {"zertifikate": ["TISAX", "ISO 9001"]},
        })).json()
        assert gesetzt["custom"]["zertifikate"] == ["ISO 9001", "TISAX"]

        # Ein erfundener Wert kommt nicht durch.
        schief = await k.patch(f"/api/companies/{firma['id']}", json={
            "custom": {"zertifikate": ["ISO 9001", "Goldstern"]},
        })
        assert schief.status_code == 400
        assert "Goldstern" in schief.json()["detail"]


async def test_beschriftung_aendern_laesst_werte_stehen(datenbank):
    """Der Grund, warum eine Option zwei Namen hat."""
    async with klient_fuer("eig-umbenennen") as k:
        d = (await k.post("/api/eigenschaften", json={
            "entity": "companies", "label": "Region", "kind": "select",
            "options": ["Nord", "Süd"],
        })).json()
        firma = (await k.post("/api/companies", json={"name": "Kai GmbH"})).json()
        await k.patch(f"/api/companies/{firma['id']}", json={"custom": {"region": "Nord"}})

        umbenannt = (await k.patch(f"/api/eigenschaften/{d['id']}", json={
            "options": [{"wert": "Nord", "text": "Region Nord"}, {"wert": "Süd", "text": "Region Süd"}],
        })).json()
        assert [o["text"] for o in umbenannt["options"]] == ["Region Nord", "Region Süd"]

        # Der Datensatz trägt weiter „Nord" — und lässt sich weiter speichern.
        gelesen = (await k.get(f"/api/companies/{firma['id']}")).json()
        assert gelesen["custom"]["region"] == "Nord"
        wieder = await k.patch(f"/api/companies/{firma['id']}", json={"custom": {"region": "Nord"}})
        assert wieder.status_code == 200


async def test_benutzte_option_laesst_sich_nicht_streichen(datenbank):
    async with klient_fuer("eig-streichen") as k:
        d = (await k.post("/api/eigenschaften", json={
            "entity": "companies", "label": "Zertifikate", "kind": "multiselect",
            "options": ZERTIFIKATE,
        })).json()
        firma = (await k.post("/api/companies", json={"name": "Werft"})).json()
        await k.patch(f"/api/companies/{firma['id']}", json={"custom": {"zertifikate": ["TISAX"]}})

        weg = await k.patch(f"/api/eigenschaften/{d['id']}", json={
            "options": ["ISO 9001", "ISO 27001"],
        })
        assert weg.status_code == 409
        assert "TISAX" in weg.json()["detail"]

        # Archivieren geht dagegen — und der Datensatz bleibt gültig.
        archiviert = (await k.patch(f"/api/eigenschaften/{d['id']}", json={
            "options": [
                {"wert": "ISO 9001", "text": "ISO 9001"},
                {"wert": "ISO 27001", "text": "ISO 27001"},
                {"wert": "TISAX", "text": "TISAX", "verborgen": True},
            ],
        })).json()
        assert [o["verborgen"] for o in archiviert["options"]] == [False, False, True]
        assert (await k.get(f"/api/companies/{firma['id']}")).json()["custom"]["zertifikate"] == ["TISAX"]


async def test_unbenutzte_option_darf_weg(datenbank):
    async with klient_fuer("eig-weg") as k:
        d = (await k.post("/api/eigenschaften", json={
            "entity": "companies", "label": "Zertifikate", "kind": "multiselect",
            "options": ZERTIFIKATE,
        })).json()
        uebrig = (await k.patch(f"/api/eigenschaften/{d['id']}", json={
            "options": ["ISO 9001", "TISAX"],
        })).json()
        assert [o["wert"] for o in uebrig["options"]] == ["ISO 9001", "TISAX"]


async def test_leere_auswahl_wird_abgelehnt(datenbank):
    async with klient_fuer("eig-leer-auswahl") as k:
        antwort = await k.post("/api/eigenschaften", json={
            "entity": "companies", "label": "Nichts", "kind": "multiselect", "options": [],
        })
        assert antwort.status_code == 400
