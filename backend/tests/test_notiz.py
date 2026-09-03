"""Aus einer Notiz wird Struktur.

Das ist der Vorgang, der im Vertrieb täglich Zeit frisst — und damit der,
bei dem ein Fehler am häufigsten durchrutscht.
"""

from datetime import date, timedelta

from app.routers.notiz import _relative_frist
from tests.conftest import klient_fuer

# ---- Fristen ------------------------------------------------------------

def test_relative_fristen_werden_gerechnet():
    """Ein Modell kennt das heutige Datum nicht.

    Nach einem ISO-Datum zu fragen führt zuverlässig zu erfundenen Daten.
    Also fragen wir nach der Zeitangabe aus dem Text und rechnen hier.
    """
    heute = date.today()
    assert _relative_frist("morgen") == heute + timedelta(days=1)
    assert _relative_frist("nächste Woche") == heute + timedelta(days=7)
    assert _relative_frist("in 3 Tagen") == heute + timedelta(days=3)
    assert _relative_frist("in 2 Wochen") == heute + timedelta(weeks=2)


def test_unverstandene_frist_ist_keine_frist():
    """Lieber keine Frist als eine geratene."""
    assert _relative_frist(None) is None
    assert _relative_frist("irgendwann mal") is None
    assert _relative_frist("") is None


def test_echtes_datum_wird_uebernommen():
    assert _relative_frist("2026-12-24") == date(2026, 12, 24)


# ---- Verarbeiten --------------------------------------------------------

ANTWORT = (
    '{"art": "call",'
    ' "betreff": "Telefonat Frau Vosskamp",'
    ' "zusammenfassung": "45 Minuten. Kernfrage war die Kammerauflage.",'
    ' "aufgaben": [{"titel": "Datenweg-Beschreibung senden", "wann": "morgen"},'
    '              {"titel": "Termin mit der IT", "wann": null},'
    '              {"titel": "   ", "wann": "morgen"}],'
    ' "naechster_schritt": "Beschreibung des Datenwegs bis Freitag schicken",'
    ' "qualifizierung": {"bedarf": "Auswertung von Jahresabschlüssen",'
    '                    "ausloeser": "Kammerauflage",'
    '                    "entscheider": "unbekannt",'
    '                    "budget_geklaert": false,'
    '                    "zeitrahmen": null,'
    '                    "standort_geklaert": false},'
    ' "personen": ["Andrea Vosskamp", "Herr Brinkmann"]}'
)


async def _aufbau(klient):
    firma = (await klient.post("/api/companies", json={"name": "Notizfirma"})).json()
    await klient.post(
        "/api/contacts",
        json={"first_name": "Andrea", "last_name": "Vosskamp", "company_id": firma["id"]},
    )
    deal = (
        await klient.post("/api/deals", json={"name": "Notizgeschäft", "company_id": firma["id"]})
    ).json()
    return firma["id"], deal["id"]


async def test_notiz_wird_zu_struktur(datenbank, monkeypatch):
    from app.routers import notiz as modul

    async def antwort(cfg, system, user, **kwargs):
        return ANTWORT

    monkeypatch.setattr(modul, "chat", antwort)

    async with klient_fuer("notiz-a") as klient:
        await klient.put("/api/settings", json={"llm_base_url": "http://test/v1"})
        firma_id, deal_id = await _aufbau(klient)

        vorschlag = (
            await klient.post(
                "/api/notiz/verarbeiten",
                json={"text": "Langes Telefonat mit Frau Vosskamp …", "deal_id": deal_id,
                      "company_id": firma_id},
            )
        ).json()

    assert vorschlag["art"] == "call"
    assert vorschlag["betreff"] == "Telefonat Frau Vosskamp"

    # Die Aufgabe ohne Titel fliegt raus, die ohne Frist bleibt ohne Frist.
    assert len(vorschlag["aufgaben"]) == 2
    mit_frist = next(a for a in vorschlag["aufgaben"] if a["titel"].startswith("Datenweg"))
    assert mit_frist["faellig_am"] == str(date.today() + timedelta(days=1))
    assert next(a for a in vorschlag["aufgaben"] if a["titel"] == "Termin mit der IT")["faellig_am"] is None

    # „unbekannt" ist keine Antwort und gibt keine Punkte.
    assert vorschlag["qualifizierung"]["entscheider"] is None
    assert vorschlag["qualifikation_punkte"] == 25 + 15

    # Ein Name, den das CRM nicht kennt, wird genannt und nicht angelegt.
    assert vorschlag["unbekannte_personen"] == ["Herr Brinkmann"]


async def test_verarbeiten_schreibt_nichts(datenbank, monkeypatch):
    from app.routers import notiz as modul

    async def antwort(cfg, system, user, **kwargs):
        return ANTWORT

    monkeypatch.setattr(modul, "chat", antwort)

    async with klient_fuer("notiz-b") as klient:
        await klient.put("/api/settings", json={"llm_base_url": "http://test/v1"})
        firma_id, deal_id = await _aufbau(klient)
        await klient.post(
            "/api/notiz/verarbeiten", json={"text": "Ein Gespräch …", "deal_id": deal_id}
        )

        verlauf = (await klient.get(f"/api/activities?deal_id={deal_id}")).json()
        aufgaben = (await klient.get(f"/api/tasks?deal_id={deal_id}")).json()

    assert verlauf == [], "der Vorschlag darf nichts in den Verlauf schreiben"
    assert aufgaben == []


async def test_uebernehmen_schreibt_alles_zusammen(datenbank):
    async with klient_fuer("notiz-c") as klient:
        firma_id, deal_id = await _aufbau(klient)

        bilanz = (
            await klient.post(
                "/api/notiz/uebernehmen",
                json={
                    "company_id": firma_id,
                    "deal_id": deal_id,
                    "art": "call",
                    "betreff": "Telefonat",
                    "text": "Inhalt des Gesprächs.",
                    "aufgaben": [
                        {"titel": "Datenweg senden", "faellig_am": str(date.today())},
                        {"titel": "Termin finden"},
                    ],
                    "naechster_schritt": "Angebot nachfassen",
                    "qualifizierung": {
                        "bedarf": "Auswertung",
                        "ausloeser": None,
                        "entscheider": None,
                        "budget_geklaert": True,
                        "zeitrahmen": None,
                        "standort_geklaert": False,
                    },
                },
            )
        ).json()

        assert bilanz["aufgaben"] == 2
        assert bilanz["naechster_schritt_gesetzt"] is True
        assert bilanz["qualifizierung_gesetzt"] is True

        verlauf = (await klient.get(f"/api/activities?deal_id={deal_id}")).json()
        assert len(verlauf) == 1
        assert verlauf[0]["kind"] == "call"

        aufgaben = (await klient.get(f"/api/tasks?deal_id={deal_id}")).json()
        assert len(aufgaben) == 2

        deal = (await klient.get(f"/api/deals/{deal_id}")).json()
        assert deal["next_step"] == "Angebot nachfassen"

        qual = (await klient.get(f"/api/deals/{deal_id}/qualifizierung")).json()
        assert qual["bedarf"] == "Auswertung"
        assert qual["budget_geklaert"] is True
        assert qual["punkte"] == 45


async def test_uebernehmen_loescht_nichts_bestehendes(datenbank):
    """Eine Notiz ergänzt die Qualifizierung, sie ersetzt sie nicht.

    Sonst löschte ein Telefonat, in dem das Budget nicht vorkam, die
    Budgetangabe aus dem Gespräch davor.
    """
    async with klient_fuer("notiz-d") as klient:
        _, deal_id = await _aufbau(klient)

        await klient.put(
            f"/api/deals/{deal_id}/qualifizierung",
            json={
                "bedarf": "Aus dem ersten Gespräch",
                "entscheider": "Frau Vosskamp",
                "budget_geklaert": True,
            },
        )

        await klient.post(
            "/api/notiz/uebernehmen",
            json={
                "deal_id": deal_id,
                "betreff": "Zweites Telefonat",
                "text": "Es ging nur um den Zeitplan.",
                "qualifizierung": {
                    "bedarf": None,
                    "ausloeser": None,
                    "entscheider": None,
                    "budget_geklaert": False,
                    "zeitrahmen": "bis Jahresende",
                    "standort_geklaert": False,
                },
            },
        )

        qual = (await klient.get(f"/api/deals/{deal_id}/qualifizierung")).json()

    assert qual["bedarf"] == "Aus dem ersten Gespräch"
    assert qual["entscheider"] == "Frau Vosskamp"
    assert qual["budget_geklaert"] is True, "das Budget war geklärt und bleibt es"
    assert qual["zeitrahmen"] == "bis Jahresende"
    assert qual["punkte"] == 25 + 25 + 20 + 10


async def test_notiz_braucht_einen_bezug(kai):
    antwort = await kai.post("/api/notiz/uebernehmen", json={"betreff": "x", "text": "y"})
    assert antwort.status_code == 400


# ---- Namensabgleich -----------------------------------------------------

def test_anrede_macht_niemanden_unbekannt():
    """„Frau Lohse" und „Katrin Lohse" sind dieselbe Person.

    Ein Vergleich auf Gleichheit meldete sie als unbekannt — und der
    Hinweis, den man dreimal zu Unrecht bekommt, wird beim vierten Mal
    nicht mehr gelesen.
    """
    from app.routers.notiz import _ist_bekannt

    bekannte = ["Katrin Lohse", "Bernd Meyer"]
    assert _ist_bekannt("Frau Lohse", bekannte)
    assert _ist_bekannt("Herr Meyer", bekannte)
    assert _ist_bekannt("Dr. Katrin Lohse", bekannte)
    assert not _ist_bekannt("Herr Brinkmann", bekannte)


def test_reine_anrede_gilt_nicht_als_person():
    from app.routers.notiz import _ist_bekannt

    assert not _ist_bekannt("Herr", ["Katrin Lohse"])
