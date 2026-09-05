"""Segmentierung: Bedingungen werden zu Abfragen.

Zwei Dinge prüfen diese Tests. Erstens, dass die Filter das Richtige
finden — eine Segmentierung, die daneben greift, ist schlimmer als keine,
weil man ihr glaubt. Zweitens, dass ein Feldname aus der Anfrage die
Datenbank nie als Text erreicht: Das ist die Stelle, an der ein CRM zum
Datenleck würde.
"""

import orjson
import pytest

from app import segmente
from app.segmente import Bedingung, Ungueltig
from tests.conftest import klient_fuer

# ---- Die Übersetzung ----------------------------------------------------


def test_unbekanntes_feld_wird_abgelehnt():
    """Der einzige Weg in die Abfrage führt über die Liste bekannter Felder."""
    args: list = []
    with pytest.raises(Ungueltig):
        segmente.bedingung_zu_sql("contacts", Bedingung("passwort", "ist", "x"), args)
    with pytest.raises(Ungueltig):
        segmente.bedingung_zu_sql(
            "contacts", Bedingung("k.email; drop table users --", "ist", "x"), args
        )


def test_werte_gehen_als_parameter_nicht_in_den_text():
    """Auch ein Wert, der wie SQL aussieht, bleibt ein Wert."""
    args: list = []
    sql = segmente.bedingung_zu_sql(
        "contacts", Bedingung("email", "enthaelt", "'; drop table users; --"), args
    )
    assert "drop table" not in sql
    assert args == ["%'; drop table users; --%"]
    assert "$1" in sql


def test_eigene_eigenschaft_geht_als_parameter():
    """Ein frei gewählter Eigenschaftsname ist deshalb unbedenklich."""
    args: list = []
    sql = segmente.bedingung_zu_sql(
        "companies", Bedingung("custom.kammer'; drop --", "ist", "IHK"), args
    )
    assert "drop" not in sql
    assert args[0] == "kammer'; drop --"
    assert "custom ->> $1" in sql


def test_sortierung_nur_aus_der_liste():
    with pytest.raises(Ungueltig):
        segmente.sortierung_zu_sql("contacts", "email; drop table users", "asc")
    with pytest.raises(Ungueltig):
        # Auch der Weg über eine eigene Eigenschaft ist verschlossen: Dort
        # kann kein Parameter gebunden werden, also wird geprüft.
        segmente.sortierung_zu_sql("companies", "custom.a'; drop --", "asc")
    assert "order by k.email asc" in segmente.sortierung_zu_sql("contacts", "email", "asc")


def test_operator_muss_zum_feld_passen():
    args: list = []
    with pytest.raises(Ungueltig):
        # „enthält" an einer Zahl ist ein Bedienfehler, kein Filter.
        segmente.bedingung_zu_sql("companies", Bedingung("employee_count", "enthaelt", "5"), args)


def test_operator_ohne_wert_braucht_keinen():
    args: list = []
    sql = segmente.bedingung_zu_sql("contacts", Bedingung("email", "leer", None), args)
    assert args == []
    assert "is null" in sql

    with pytest.raises(Ungueltig):
        segmente.bedingung_zu_sql("contacts", Bedingung("email", "ist", None), args)


def test_berechnete_spalte_ist_nicht_filterbar():
    """Die Zahl der Kontakte entsteht erst im SELECT — im WHERE gibt es sie nicht."""
    args: list = []
    with pytest.raises(Ungueltig):
        segmente.bedingung_zu_sql("companies", Bedingung("contact_count", "groesser", 2), args)
    # Sortieren geht trotzdem: dort steht sie schon.
    assert "contact_count" in segmente.sortierung_zu_sql("companies", "contact_count", "desc")


def test_zu_viele_bedingungen():
    args: list = []
    viele = [Bedingung("city", "ist", str(i)) for i in range(21)]
    with pytest.raises(Ungueltig):
        segmente.filter_zu_sql("companies", viele, args)


# ---- Gegen echte Daten --------------------------------------------------


async def _bestand(klient):
    await klient.post("/api/companies", json={
        "name": "Nordwind Logistik", "city": "Hamburg", "industry": "Logistik",
        "employee_count": 120, "lifecycle_stage": "customer",
    })
    await klient.post("/api/companies", json={
        "name": "Südlicht Beratung", "city": "München", "industry": "Beratung",
        "employee_count": 12, "lifecycle_stage": "lead",
    })
    await klient.post("/api/companies", json={
        "name": "Hanse Werft", "city": "Hamburg", "industry": "Industrie",
        "lifecycle_stage": "qualified",
    })


def f(*bedingungen):
    return orjson.dumps(list(bedingungen)).decode()


async def test_filter_findet_und_zaehlt(datenbank):
    async with klient_fuer("segment-a") as k:
        await _bestand(k)

        hamburg = f({"feld": "city", "operator": "ist", "wert": "Hamburg"})
        treffer = (await k.get(f"/api/companies?filter={hamburg}")).json()
        assert {t["name"] for t in treffer} == {"Nordwind Logistik", "Hanse Werft"}

        # Die Gesamtzahl ist die Antwort auf die Frage, nicht die Länge der Seite.
        assert (await k.get(f"/api/companies/anzahl?filter={hamburg}")).json()["anzahl"] == 2

        # Zwei Bedingungen gelten zusammen.
        eng = f(
            {"feld": "city", "operator": "ist", "wert": "Hamburg"},
            {"feld": "employee_count", "operator": "groesser", "wert": 50},
        )
        assert [t["name"] for t in (await k.get(f"/api/companies?filter={eng}")).json()] == [
            "Nordwind Logistik"
        ]

        # Leer heißt leer — die Werft hat keine Mitarbeiterzahl.
        ohne = f({"feld": "employee_count", "operator": "leer"})
        assert [t["name"] for t in (await k.get(f"/api/companies?filter={ohne}")).json()] == [
            "Hanse Werft"
        ]


async def test_filter_auf_stufe_und_mehrfachauswahl(datenbank):
    async with klient_fuer("segment-stufe") as k:
        await _bestand(k)
        mehrere = f({
            "feld": "lifecycle_stage", "operator": "ist_eines_von",
            "wert": ["customer", "qualified"],
        })
        namen = {t["name"] for t in (await k.get(f"/api/companies?filter={mehrere}")).json()}
        assert namen == {"Nordwind Logistik", "Hanse Werft"}


async def test_filter_auf_eigene_eigenschaft(datenbank):
    async with klient_fuer("segment-eigen") as k:
        await k.post("/api/eigenschaften", json={
            "entity": "companies", "label": "Kammer", "kind": "select",
            "options": ["IHK", "Handwerkskammer"],
        })
        await k.post("/api/companies", json={"name": "Mit Kammer", "custom": {"kammer": "IHK"}})
        await k.post("/api/companies", json={"name": "Ohne Kammer"})

        ihk = f({"feld": "custom.kammer", "operator": "ist", "wert": "IHK"})
        assert [t["name"] for t in (await k.get(f"/api/companies?filter={ihk}")).json()] == [
            "Mit Kammer"
        ]

        # Die Eigenschaft steht auch in der Feldliste, aus der die
        # Oberfläche ihre Auswahl baut.
        felder = (await k.get("/api/ansichten/felder?entity=companies")).json()
        eigen = [x for x in felder["felder"] if x["schluessel"] == "custom.kammer"]
        assert eigen and eigen[0]["art"] == "auswahl"
        assert eigen[0]["optionen"] == [
            {"wert": "IHK", "text": "IHK", "verborgen": False},
            {"wert": "Handwerkskammer", "text": "Handwerkskammer", "verborgen": False},
        ]


async def test_sortierung_wirkt(datenbank):
    async with klient_fuer("segment-sort") as k:
        await _bestand(k)
        auf = (await k.get("/api/companies?sort=name&richtung=asc")).json()
        assert [t["name"] for t in auf] == ["Hanse Werft", "Nordwind Logistik", "Südlicht Beratung"]
        ab = (await k.get("/api/companies?sort=name&richtung=desc")).json()
        assert [t["name"] for t in ab][0] == "Südlicht Beratung"


async def test_kaputter_filter_meldet_sich(datenbank):
    async with klient_fuer("segment-kaputt") as k:
        assert (await k.get("/api/companies?filter=keinjson")).status_code == 400
        schlecht = f({"feld": "gibtsnicht", "operator": "ist", "wert": "x"})
        antwort = await k.get(f"/api/companies?filter={schlecht}")
        assert antwort.status_code == 400
        assert "gibtsnicht" in antwort.json()["detail"]
        assert (await k.get("/api/companies?sort=drop%20table")).status_code == 400


# ---- Ansichten ----------------------------------------------------------


async def test_ansicht_speichern_und_wiederfinden(datenbank):
    async with klient_fuer("ansicht-a") as k:
        ansicht = (await k.post("/api/ansichten", json={
            "entity": "companies",
            "name": "Kunden in Hamburg",
            "filter": [
                {"feld": "city", "operator": "ist", "wert": "Hamburg"},
                {"feld": "lifecycle_stage", "operator": "ist", "wert": "customer"},
            ],
            "spalten": ["name", "city", "lifecycle_stage"],
            "sort_feld": "name",
            "sort_richtung": "asc",
        })).json()
        assert ansicht["name"] == "Kunden in Hamburg"
        assert len(ansicht["filter"]) == 2

        liste = (await k.get("/api/ansichten?entity=companies")).json()
        assert [a["name"] for a in liste] == ["Kunden in Hamburg"]
        # Für ein anderes Objekt gilt sie nicht.
        assert (await k.get("/api/ansichten?entity=contacts")).json() == []

        geaendert = (await k.patch(f"/api/ansichten/{ansicht['id']}", json={
            "name": "Kunden Hamburg", "spalten": ["name", "industry"],
        })).json()
        assert geaendert["name"] == "Kunden Hamburg"
        assert geaendert["spalten"] == ["name", "industry"]

        assert (await k.delete(f"/api/ansichten/{ansicht['id']}")).status_code == 204
        assert (await k.get("/api/ansichten?entity=companies")).json() == []


async def test_ansicht_mit_unbrauchbarem_filter_wird_nicht_gespeichert(datenbank):
    """Eine Ansicht, die beim Öffnen fehlschlägt, wäre schlimmer als keine."""
    async with klient_fuer("ansicht-pruef") as k:
        antwort = await k.post("/api/ansichten", json={
            "entity": "companies", "name": "Kaputt",
            "filter": [{"feld": "erfunden", "operator": "ist", "wert": "x"}],
        })
        assert antwort.status_code == 400
        assert (await k.get("/api/ansichten?entity=companies")).json() == []


async def test_ansichten_bleiben_in_der_organisation(datenbank):
    async with klient_fuer("ansicht-x") as x, klient_fuer("ansicht-y") as y:
        a = (await x.post("/api/ansichten", json={"entity": "contacts", "name": "Meine Liste"})).json()
        assert (await y.get("/api/ansichten?entity=contacts")).json() == []
        assert (await y.delete(f"/api/ansichten/{a['id']}")).status_code == 404


async def test_private_ansicht_erscheint_nur_bei_ihrer_person(datenbank):
    """Wer sich eine Arbeitsliste baut, hängt sie nicht jedem in die Leiste."""
    from tests.test_mitglieder import mit_sitzplatz

    async with klient_fuer("ansicht-privat") as k:
        marc = (await k.post("/api/mitglieder", json={"display_name": "Marc Bayer"})).json()
        await k.post("/api/ansichten", json={
            "entity": "contacts", "name": "Nur meine", "nur_ich": True,
        })
        assert [a["name"] for a in (await k.get("/api/ansichten?entity=contacts")).json()] == ["Nur meine"]

    async with mit_sitzplatz("ansicht-privat", marc["id"]) as m:
        assert (await m.get("/api/ansichten?entity=contacts")).json() == []


# ---- Stapel -------------------------------------------------------------


async def test_mehrere_auf_einmal_aendern(datenbank):
    async with klient_fuer("stapel-a") as k:
        ids = [
            (await k.post("/api/companies", json={"name": f"Messe {i}"})).json()["id"]
            for i in range(3)
        ]
        bilanz = (await k.post("/api/companies/mehrere", json={
            "ids": ids, "lifecycle_stage": "qualified", "source": "Messe Hamburg",
        })).json()
        assert bilanz["geaendert"] == 3

        alle = (await k.get("/api/companies?q=Messe")).json()
        assert all(c["lifecycle_stage"] == "qualified" for c in alle)
        assert all(c["source"] == "Messe Hamburg" for c in alle)

        # Und wieder weg, ebenfalls im Stapel.
        assert (await k.post("/api/companies/mehrere/loeschen", json={"ids": ids[:2]})).json()["geloescht"] == 2
        assert len((await k.get("/api/companies?q=Messe")).json()) == 1


async def test_stapel_ohne_auswahl_und_ohne_aenderung(datenbank):
    async with klient_fuer("stapel-leer") as k:
        assert (await k.post("/api/companies/mehrere", json={"ids": []})).status_code == 400
        id_ = (await k.post("/api/companies", json={"name": "Einzeln"})).json()["id"]
        assert (await k.post("/api/companies/mehrere", json={"ids": [id_]})).status_code == 400


async def test_stapel_greift_nicht_in_fremde_organisation(datenbank):
    async with klient_fuer("stapel-x") as x, klient_fuer("stapel-y") as y:
        fremd = (await x.post("/api/companies", json={"name": "Fremd"})).json()["id"]
        bilanz = (await y.post("/api/companies/mehrere", json={
            "ids": [fremd], "lifecycle_stage": "customer",
        })).json()
        assert bilanz["geaendert"] == 0
        assert (await x.get(f"/api/companies/{fremd}")).json()["lifecycle_stage"] == "lead"


# ---- Mehrfachauswahl im Filter -----------------------------------------
#
# Der Unterschied zwischen „hat eines von" und „hat alle von" ist der
# zwischen einer Zielgruppe und einer Schnittmenge — und er ist der
# einzige Grund, warum eine Mehrfachauswahl eigene Operatoren braucht.

async def test_listenfilter_auf_mehrfachauswahl(datenbank):
    async with klient_fuer("segment-multi") as k:
        await k.post("/api/eigenschaften", json={
            "entity": "companies", "label": "Zertifikate", "kind": "multiselect",
            "options": ["ISO 9001", "ISO 27001", "TISAX"],
        })
        await k.post("/api/companies", json={
            "name": "Beide", "custom": {"zertifikate": ["ISO 9001", "TISAX"]},
        })
        await k.post("/api/companies", json={
            "name": "Nur ISO", "custom": {"zertifikate": ["ISO 9001"]},
        })
        await k.post("/api/companies", json={"name": "Ohne"})

        async def namen(operator, wert):
            f = orjson.dumps([{"feld": "custom.zertifikate", "operator": operator, "wert": wert}]).decode()
            return sorted(c["name"] for c in (await k.get(f"/api/companies?filter={f}")).json())

        assert await namen("hat_eines_von", ["TISAX", "ISO 27001"]) == ["Beide"]
        assert await namen("hat_eines_von", ["ISO 9001"]) == ["Beide", "Nur ISO"]
        assert await namen("hat_alle_von", ["ISO 9001", "TISAX"]) == ["Beide"]
        assert await namen("hat_alle_von", ["ISO 9001"]) == ["Beide", "Nur ISO"]

        # Wer nichts eingetragen hat, hat auch keines davon — das ist die
        # wörtliche Lesart, und sie ist die nützliche: „zeig mir alle ohne
        # TISAX" soll die ohne Angabe einschließen.
        assert await namen("hat_keines_von", ["TISAX"]) == ["Nur ISO", "Ohne"]
        assert await namen("hat_nicht_alle_von", ["ISO 9001", "TISAX"]) == ["Nur ISO", "Ohne"]

        f = orjson.dumps([{"feld": "custom.zertifikate", "operator": "leer"}]).decode()
        assert [c["name"] for c in (await k.get(f"/api/companies?filter={f}")).json()] == ["Ohne"]


async def test_mehrfachauswahl_steht_mit_ihren_operatoren_in_der_feldliste(datenbank):
    async with klient_fuer("segment-multi-felder") as k:
        await k.post("/api/eigenschaften", json={
            "entity": "contacts", "label": "Interessen", "kind": "multiselect",
            "options": ["Wartung", "Schulung"],
        })
        felder = (await k.get("/api/ansichten/felder?entity=contacts")).json()
        feld = next(x for x in felder["felder"] if x["schluessel"] == "custom.interessen")
        assert feld["art"] == "mehrfachauswahl"
        assert feld["operatoren"] == [
            "hat_eines_von", "hat_alle_von", "hat_keines_von", "hat_nicht_alle_von",
            "leer", "nicht_leer",
        ]
        # „ist" gibt es hier nicht: Ein Feld mit drei Werten *ist* keiner davon.
        assert "ist" not in feld["operatoren"]


def test_listenoperator_nur_an_eigener_eigenschaft():
    """`hat eines von` an einer festen Spalte wäre eine stille Falschaussage."""
    with pytest.raises(segmente.Ungueltig):
        segmente.bedingung_zu_sql(
            "companies", Bedingung("name", "hat_eines_von", ["Werft"]), []
        )


async def test_quellenliste_deckt_die_aufzaehlung(datenbank):
    """Die Filterauswahl und die Datenbank-Aufzählung müssen dasselbe sagen.

    Sie stehen an zwei Stellen, und genau daran ist es einmal
    auseinandergelaufen: `api` und `bot` gab es in der Datenbank, aber
    nicht im Filter — Tickets aus der Schnittstelle waren damit über ihre
    Herkunft nicht auffindbar. Niemand vermisst einen Filter, den es nie
    gab; deshalb prüft das ein Test und kein Mensch.
    """
    from app.db import acquire

    async with klient_fuer("segment-quellen") as k:
        felder = (await k.get("/api/ansichten/felder?entity=tickets")).json()["felder"]
    angeboten = {
        o["wert"] for o in next(f for f in felder if f["schluessel"] == "quelle")["optionen"]
    }

    async with acquire() as conn:
        in_der_datenbank = set(
            await conn.fetchval("select enum_range(null::public.ticket_quelle)::text[]")
        )

    assert angeboten == in_der_datenbank, (
        f"nur im Filter: {angeboten - in_der_datenbank} · "
        f"nur in der Datenbank: {in_der_datenbank - angeboten}"
    )
