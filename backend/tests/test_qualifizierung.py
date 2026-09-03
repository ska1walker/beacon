"""Qualifizierung, Verlustgründe und Prognose."""


from app.qualifizierung import offen, punkte
from app.schemas import Qualifizierung
from tests.conftest import klient_fuer

# ---- Punkte -------------------------------------------------------------

def test_leere_qualifizierung_hat_null_punkte():
    assert punkte(Qualifizierung()) == 0
    assert len(offen(Qualifizierung())) == 6


def test_volle_qualifizierung_hat_hundert():
    voll = Qualifizierung(
        bedarf="Auswertung von Jahresabschlüssen",
        ausloeser="Kammerauflage",
        entscheider="Frau Vosskamp, Partnerin",
        budget_geklaert=True,
        zeitrahmen="bis Jahresende",
        standort_geklaert=True,
    )
    assert punkte(voll) == 100
    assert offen(voll) == []


def test_gewichte_addieren_sich_auf_hundert():
    """Sonst wäre die Punktzahl keine Prozentangabe, sähe aber aus wie eine."""
    from app.qualifizierung import GEWICHTE

    assert sum(g for _, g, _ in GEWICHTE) == 100


def test_leerzeichen_zaehlen_nicht_als_antwort():
    assert punkte(Qualifizierung(bedarf="   ")) == 0


def test_offene_punkte_sind_fragen(monkeypatch):
    """Eine Punktzahl allein sagt niemandem, was als Nächstes zu tun ist."""
    teil = Qualifizierung(bedarf="Auswertung", budget_geklaert=True)
    fragen = offen(teil)
    assert all(f.endswith("?") for f in fragen)
    assert any("entscheidet" in f for f in fragen)


# ---- Über die API -------------------------------------------------------

async def _deal(klient, marke: str) -> str:
    firma = (await klient.post("/api/companies", json={"name": f"Qualifirma {marke}"})).json()
    return (
        await klient.post("/api/deals", json={"name": f"Q {marke}", "company_id": firma["id"],
                                              "amount_cents": 1450000})
    ).json()["id"]


async def test_qualifizierung_schreiben_und_lesen(kai):
    deal_id = await _deal(kai, "A")

    leer = (await kai.get(f"/api/deals/{deal_id}/qualifizierung")).json()
    assert leer["punkte"] == 0
    assert len(leer["offen"]) == 6

    geschrieben = (
        await kai.put(
            f"/api/deals/{deal_id}/qualifizierung",
            json={
                "bedarf": "Auswertung von Jahresabschlüssen",
                "entscheider": "Frau Vosskamp",
                "budget_geklaert": True,
            },
        )
    ).json()
    assert geschrieben["punkte"] == 25 + 25 + 20
    assert geschrieben["qualifikation_am"] is not None
    assert len(geschrieben["offen"]) == 3

    wieder = (await kai.get(f"/api/deals/{deal_id}/qualifizierung")).json()
    assert wieder["punkte"] == geschrieben["punkte"]


async def test_verlustgruende_sind_ausgesaet(kai):
    gruende = (await kai.get("/api/verlustgruende")).json()
    namen = [g["name"] for g in gruende]
    assert "Preis" in namen
    assert "Widerstand aus der IT" in namen


async def test_verlustgrund_setzen_hinterlaesst_verlauf(kai):
    deal_id = await _deal(kai, "B")
    gruende = (await kai.get("/api/verlustgruende")).json()
    preis = next(g for g in gruende if g["name"] == "Preis")

    antwort = await kai.post(
        f"/api/deals/{deal_id}/verloren",
        json={"lost_reason_id": preis["id"], "lost_reason": "20 % über dem Mitbewerber"},
    )
    assert antwort.status_code == 200
    assert antwort.json()["grund"] == "Preis"

    verlauf = (await kai.get(f"/api/activities?deal_id={deal_id}")).json()
    assert any("Verlustgrund: Preis" in (a["subject"] or "") for a in verlauf)


async def test_erfundener_verlustgrund_wird_abgelehnt(kai):
    from uuid import uuid4

    deal_id = await _deal(kai, "C")
    antwort = await kai.post(
        f"/api/deals/{deal_id}/verloren", json={"lost_reason_id": str(uuid4())}
    )
    assert antwort.status_code == 400


# ---- Prognose -----------------------------------------------------------

async def test_prognose_ohne_abschluss_sagt_das(datenbank):
    """Trefferquote null und „noch nichts entschieden" sind zwei Aussagen."""
    async with klient_fuer("prognose-leer") as klient:
        await _deal(klient, "L")
        p = (await klient.get("/api/prognose")).json()

    assert p["anzahl_offen"] == 1
    assert p["trefferquote"] is None, "0 % würde behaupten, es sei etwas verloren gegangen"
    assert p["durchschnittsdauer_tage"] is None


async def test_prognose_rechnet_gewichtet_und_zaehlt(datenbank):
    async with klient_fuer("prognose-voll") as klient:
        stufen = (await klient.get("/api/pipelines")).json()[0]["stages"]
        gewonnen = next(s for s in stufen if s["kind"] == "won")
        verloren = next(s for s in stufen if s["kind"] == "lost")
        angebot = next(s for s in stufen if s["name"] == "Angebot")

        a = await _deal(klient, "P1")
        b = await _deal(klient, "P2")
        c = await _deal(klient, "P3")
        offen_deal = await _deal(klient, "P4")

        await klient.post(f"/api/deals/{a}/stage", json={"stage_id": gewonnen["id"]})
        await klient.post(f"/api/deals/{b}/stage", json={"stage_id": gewonnen["id"]})
        await klient.post(f"/api/deals/{c}/stage", json={"stage_id": verloren["id"]})
        await klient.post(f"/api/deals/{offen_deal}/stage", json={"stage_id": angebot["id"]})

        gruende = (await klient.get("/api/verlustgruende")).json()
        await klient.post(
            f"/api/deals/{c}/verloren",
            json={"lost_reason_id": next(g["id"] for g in gruende if g["name"] == "Preis")},
        )

        p = (await klient.get("/api/prognose")).json()

    assert p["anzahl_gewonnen"] == 2
    assert p["anzahl_verloren"] == 1
    assert p["gewonnen_cents"] == 2 * 1450000
    assert abs(p["trefferquote"] - 2 / 3) < 0.001

    # 60 % Wahrscheinlichkeit auf der Stufe „Angebot"
    assert p["anzahl_offen"] == 1
    assert p["gewichtet_cents"] == round(1450000 * 0.6)

    assert p["verlustgruende"][0]["grund"] == "Preis"
    assert p["verlustgruende"][0]["anzahl"] == 1


async def test_prognose_zeigt_ueberfaellige(datenbank):
    """Ein Geschäft, dessen Abschlussdatum verstrichen ist, muss auffallen."""
    async with klient_fuer("prognose-alt") as klient:
        firma = (await klient.post("/api/companies", json={"name": "Alte Firma"})).json()
        await klient.post(
            "/api/deals",
            json={
                "name": "Längst fällig",
                "company_id": firma["id"],
                "amount_cents": 990000,
                "close_date": "2020-01-01",
            },
        )
        p = (await klient.get("/api/prognose")).json()

    assert p["ueberfaellig_anzahl"] == 1
    assert p["ueberfaellig_cents"] == 990000


# ---- KI-Qualifizierung --------------------------------------------------

async def test_ki_erfindet_nichts(datenbank, monkeypatch):
    """Eine Lücke ist ein brauchbares Ergebnis, eine Vermutung nicht.

    Modelle schreiben statt `null` gern „unbekannt" in ein Feld. Das sieht
    aus wie eine Antwort, ist keine — und würde Punkte geben, die das
    Geschäft nicht verdient hat.
    """
    from app.routers import ki

    async def antwort(cfg, system, user, **kwargs):
        return (
            '{"bedarf": "Auswertung von Jahresabschlüssen",'
            ' "ausloeser": "unbekannt",'
            ' "entscheider": null,'
            ' "budget_geklaert": false,'
            ' "zeitrahmen": "  ",'
            ' "standort_geklaert": false,'
            ' "belege": {"bedarf": "Frau Vosskamp sprach von 40 Abschlüssen im Jahr"}}'
        )

    monkeypatch.setattr(ki, "chat", antwort)

    async with klient_fuer("ki-qual") as klient:
        await klient.put("/api/settings", json={"llm_base_url": "http://test/v1"})
        deal_id = await _deal(klient, "KI")
        ergebnis = (await klient.post(f"/api/ki/deals/{deal_id}/qualifizieren")).json()

    assert ergebnis["bedarf"] == "Auswertung von Jahresabschlüssen"
    assert ergebnis['ausloeser'] is None, 'das Wort „unbekannt“ ist keine Antwort'
    assert ergebnis['zeitrahmen'] is None, 'Leerzeichen sind keine Antwort'
    assert ergebnis["punkte"] == 25, "nur der Bedarf zählt"
    assert len(ergebnis["offen"]) == 5
    assert "bedarf" in ergebnis["belege"]


async def test_ki_schreibt_die_qualifizierung_nicht_selbst(datenbank, monkeypatch):
    """Der Vorschlag füllt die Maske. Speichern tut ein Mensch."""
    from app.routers import ki

    async def antwort(cfg, system, user, **kwargs):
        return '{"bedarf": "Etwas", "entscheider": "Jemand", "budget_geklaert": true}'

    monkeypatch.setattr(ki, "chat", antwort)

    async with klient_fuer("ki-qual2") as klient:
        await klient.put("/api/settings", json={"llm_base_url": "http://test/v1"})
        deal_id = await _deal(klient, "KI2")
        vorschlag = (await klient.post(f"/api/ki/deals/{deal_id}/qualifizieren")).json()
        gespeichert = (await klient.get(f"/api/deals/{deal_id}/qualifizierung")).json()

    assert vorschlag["punkte"] == 70
    assert gespeichert["punkte"] == 0, "der Vorschlag darf nichts geschrieben haben"


async def test_schema_ist_die_eine_quelle(kai):
    """Die Oberfläche rechnet ihre Vorschau mit diesen Gewichten.

    Stünden sie dort noch einmal, zeigte die Maske irgendwann 70 an,
    während die Prognose mit 55 rechnet.
    """
    schema = (await kai.get("/api/qualifizierung/schema")).json()
    assert sum(f["gewicht"] for f in schema) == 100
    assert {f["feld"] for f in schema} == {
        "bedarf", "ausloeser", "entscheider", "budget_geklaert",
        "zeitrahmen", "standort_geklaert",
    }
    assert all(f["frage"].endswith("?") for f in schema)
    ja_nein = {f["feld"] for f in schema if f["art"] == "ja_nein"}
    assert ja_nein == {"budget_geklaert", "standort_geklaert"}
