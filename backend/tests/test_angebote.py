"""Angebote.

Der Schwerpunkt liegt auf den Summen. Ein Angebot ist das eine Dokument,
das das Haus verlässt und an dem ein Kunde eine Unterschrift setzt — ein
Rundungsfehler darin ist teurer als jeder Anzeigefehler in der Oberfläche.
"""

import pytest

from app.routers.angebote import nummer, summen, zeilenbetrag
from app.schemas import QuoteItem
from tests.conftest import klient_fuer


def _pos(betrag: int) -> QuoteItem:
    from uuid import uuid4

    return QuoteItem(
        id=uuid4(), title="x", quantity=1, unit_price_cents=betrag, line_total_cents=betrag
    )


# ---- Rechnen ------------------------------------------------------------

def test_zeilenbetrag_ohne_nachlass():
    assert zeilenbetrag(1, 990000, 0) == 990000
    assert zeilenbetrag(3, 990000, 0) == 2970000


def test_zeilenbetrag_mit_nachlass():
    # 9.900 € minus 10 % = 8.910 €
    assert zeilenbetrag(1, 990000, 10) == 891000


def test_zeilenbetrag_rundet_erst_am_ende():
    """Drei Stück mit 7,5 % Nachlass.

    Erst je Stück runden und dann multiplizieren ergäbe einen anderen
    Betrag als erst multiplizieren und dann runden. Der Unterschied sind
    Cent — und die stehen später in einer Rechnung.
    """
    einzeln_gerundet = round(990000 * 0.925) * 3
    assert zeilenbetrag(3, 990000, 7.5) == round(3 * 990000 * 0.925)
    assert zeilenbetrag(3, 990000, 7.5) != einzeln_gerundet or einzeln_gerundet == 2747250


def test_summen_mit_steuer():
    ergebnis = summen([_pos(1450000)], discount_cents=0, tax_rate=0.19)
    assert ergebnis["net_cents"] == 1450000
    assert ergebnis["tax_cents"] == 275500
    assert ergebnis["gross_cents"] == 1725500


def test_summen_mit_nachlass():
    ergebnis = summen([_pos(1450000)], discount_cents=50000, tax_rate=0.19)
    assert ergebnis["taxable_cents"] == 1400000
    assert ergebnis["tax_cents"] == 266000
    assert ergebnis["gross_cents"] == 1666000


def test_nachlass_groesser_als_summe_wird_gedeckelt():
    """Ein Tippfehler im Nachlassfeld darf keinen negativen Betrag ergeben."""
    ergebnis = summen([_pos(100000)], discount_cents=999999999, tax_rate=0.19)
    assert ergebnis["taxable_cents"] == 0
    assert ergebnis["gross_cents"] == 0
    assert ergebnis["discount_total_cents"] == 100000


def test_nummer_ist_sortierbar():
    from datetime import datetime

    assert nummer(7, datetime(2026, 5, 1)) == "AG-2026-0007"
    assert nummer(123, datetime(2026, 5, 1)) < nummer(124, datetime(2026, 5, 1))


# ---- Über die API -------------------------------------------------------

async def _deal(klient, marke: str) -> str:
    firma = (await klient.post("/api/companies", json={"name": f"Angebotsfirma {marke}"})).json()
    return (
        await klient.post(
            "/api/deals",
            json={"name": f"Geschäft {marke}", "company_id": firma["id"], "product": "analyst"},
        )
    ).json()["id"]


async def test_katalog_ist_ausgesaet(kai):
    produkte = (await kai.get("/api/products")).json()
    schluessel = {p["key"] for p in produkte}
    assert {"assistent", "analyst", "experte"} <= schluessel

    analyst = next(p for p in produkte if p["key"] == "analyst")
    assert analyst["list_price_cents"] == 1450000
    assert analyst["default_service_days"] == 8

    # Der Servicetag steht ohne Preis: In der Produktbeschreibung ist
    # keiner genannt, und ein geratener Tagessatz landete im Angebot.
    servicetag = next(p for p in produkte if p["key"] == "servicetag")
    assert servicetag["list_price_cents"] == 0


async def test_angebot_anlegen_und_rechnen(kai):
    deal_id = await _deal(kai, "A")
    produkte = (await kai.get("/api/products")).json()
    analyst = next(p for p in produkte if p["key"] == "analyst")

    antwort = await kai.post(
        "/api/quotes",
        json={
            "deal_id": deal_id,
            "valid_until": "2026-12-31",
            "items": [
                {
                    "product_id": analyst["id"],
                    "title": "Analyst",
                    "quantity": 1,
                    "unit_price_cents": analyst["list_price_cents"],
                },
                {"title": "Zusätzliche Servicetage", "quantity": 4, "unit_price_cents": 120000},
            ],
        },
    )
    assert antwort.status_code == 201
    angebot = antwort.json()

    assert angebot["number"].startswith("AG-")
    assert angebot["status"] == "draft"
    assert len(angebot["items"]) == 2
    assert angebot["net_cents"] == 1450000 + 480000
    assert angebot["gross_cents"] == round(1930000 * 1.19)
    assert angebot["company_name"] == "Angebotsfirma A"


async def test_nummern_zaehlen_fort(kai):
    erst = await _deal(kai, "B1")
    zweit = await _deal(kai, "B2")
    a = (await kai.post("/api/quotes", json={"deal_id": erst})).json()
    b = (await kai.post("/api/quotes", json={"deal_id": zweit})).json()
    assert b["number_seq"] == a["number_seq"] + 1
    assert a["number"] != b["number"]


async def test_status_hinterlaesst_verlauf(kai):
    deal_id = await _deal(kai, "C")
    angebot = (await kai.post("/api/quotes", json={"deal_id": deal_id})).json()

    verschickt = (
        await kai.post(f"/api/quotes/{angebot['id']}/status", json={"status": "sent"})
    ).json()
    assert verschickt["status"] == "sent"
    assert verschickt["sent_at"] is not None

    angenommen = (
        await kai.post(
            f"/api/quotes/{angebot['id']}/status",
            json={"status": "accepted", "decision_note": "Herr Meyer hat zugesagt"},
        )
    ).json()
    assert angenommen["decided_at"] is not None

    verlauf = (await kai.get(f"/api/activities?deal_id={deal_id}")).json()
    betreffe = [a["subject"] for a in verlauf if a["kind"] == "quote"]
    assert any("verschickt" in b for b in betreffe)
    assert any("angenommen" in b for b in betreffe)


async def test_verschicktes_angebot_wird_nicht_mehr_geaendert(kai):
    """Was beim Kunden liegt, ändert sich nicht hinter seinem Rücken."""
    deal_id = await _deal(kai, "D")
    angebot = (
        await kai.post(
            "/api/quotes",
            json={"deal_id": deal_id, "items": [{"title": "Analyst", "unit_price_cents": 1450000}]},
        )
    ).json()

    # Solange es ein Entwurf ist, geht das Ändern.
    geaendert = await kai.put(
        f"/api/quotes/{angebot['id']}/positionen",
        json=[{"title": "Analyst", "unit_price_cents": 1400000}],
    )
    assert geaendert.status_code == 200

    await kai.post(f"/api/quotes/{angebot['id']}/status", json={"status": "sent"})

    gesperrt = await kai.put(
        f"/api/quotes/{angebot['id']}/positionen",
        json=[{"title": "Analyst", "unit_price_cents": 1}],
    )
    assert gesperrt.status_code == 409
    assert "neues" in gesperrt.json()["detail"]


async def test_frist_laeuft_ab(kai):
    deal_id = await _deal(kai, "E")
    angebot = (
        await kai.post("/api/quotes", json={"deal_id": deal_id, "valid_until": "2020-01-01"})
    ).json()
    await kai.post(f"/api/quotes/{angebot['id']}/status", json={"status": "sent"})

    ergebnis = (await kai.post("/api/quotes/fristen-pruefen")).json()
    assert ergebnis["abgelaufen"] >= 1

    nachher = (await kai.get(f"/api/quotes/{angebot['id']}")).json()
    assert nachher["status"] == "expired"


async def test_angebot_eines_fremden_ist_unsichtbar(kai, marc):
    deal_id = await _deal(kai, "F")
    angebot = (await kai.post("/api/quotes", json={"deal_id": deal_id})).json()
    assert (await marc.get(f"/api/quotes/{angebot['id']}")).status_code == 404


async def test_angebot_braucht_einen_deal(kai):
    from uuid import uuid4

    antwort = await kai.post("/api/quotes", json={"deal_id": str(uuid4())})
    assert antwort.status_code == 404


# ---- KI-Vorschlag -------------------------------------------------------

def test_json_aus_antwort_vertraegt_zaeune():
    """Modelle rahmen ihre Antwort gern ein, egal wie klar die Ansage war."""
    from app.llm import json_aus_antwort

    assert json_aus_antwort('{"a": 1}') == {"a": 1}
    assert json_aus_antwort('```json\n{"a": 1}\n```') == {"a": 1}
    assert json_aus_antwort('Gern! Hier:\n{"a": 1}\nViel Erfolg.') == {"a": 1}

    with pytest.raises(ValueError, match="kein JSON"):
        json_aus_antwort("Dazu kann ich nichts sagen.")


async def test_vorschlag_erfindet_keine_preise(datenbank, monkeypatch):
    """Der Kern der Sache.

    Ein Sprachmodell, das einen Betrag erfindet, erfindet ihn plausibel —
    und plausibel falsch ist genau die Sorte Fehler, die bis zum Kunden
    durchkommt. Deshalb kommen Preise aus dem Katalog, und ein Schlüssel,
    den der Katalog nicht kennt, wird zur Position ohne Preis mit einem
    Vermerk.
    """
    from app.routers import ki

    async def gefaelschte_antwort(cfg, system, user, **kwargs):
        return (
            '{"begruendung": "Analyst passt zum Bedarf.",'
            ' "anschreiben": "Sehr geehrte Frau Vosskamp, ...",'
            ' "positionen": ['
            '   {"produkt_key": "analyst", "titel": "Analyst", "menge": 1},'
            '   {"produkt_key": "premium-gold", "titel": "Premiumpaket", "menge": 1}'
            ' ],'
            ' "offene_punkte": ["Zahlungsziel unklar"]}'
        )

    monkeypatch.setattr(ki, "chat", gefaelschte_antwort)

    # Eigene Organisation: Dieser Test trägt eine LLM-Adresse ein, und die
    # bliebe sonst für jeden folgenden Test stehen — der Test, der prüft,
    # dass ohne Endpunkt nichts passiert, fiel daran schon einmal um.
    async with klient_fuer("angebot-ki") as klient:
        await klient.put(
            "/api/settings", json={"llm_base_url": "http://test/v1", "llm_model": "probe"}
        )
        deal_id = await _deal(klient, "KI")
        antwort = await klient.post(f"/api/ki/deals/{deal_id}/angebotsvorschlag")
        assert antwort.status_code == 200
        vorschlag = antwort.json()
        verlauf = (await klient.get(f"/api/activities?deal_id={deal_id}")).json()

    analyst = next(p for p in vorschlag["positionen"] if p["produkt_key"] == "analyst")
    assert analyst["einzelpreis_cents"] == 1450000, "der Preis muss aus dem Katalog kommen"

    erfunden = next(p for p in vorschlag["positionen"] if p["titel"] == "Premiumpaket")
    assert erfunden["produkt_key"] is None
    assert erfunden["einzelpreis_cents"] == 0, "ein unbekanntes Produkt bekommt keinen Preis"

    assert any("Premiumpaket" in punkt for punkt in vorschlag["offene_punkte"])
    assert "Zahlungsziel unklar" in vorschlag["offene_punkte"]

    # Und der Vorschlag steht im Verlauf, als KI gekennzeichnet.
    assert any(a["kind"] == "ai" and "Angebotsvorschlag" in (a["subject"] or "") for a in verlauf)


async def test_unlesbare_modellantwort_wird_gemeldet(datenbank, monkeypatch):
    from app.routers import ki

    async def geschwaetz(cfg, system, user, **kwargs):
        return "Da müsste ich raten."

    monkeypatch.setattr(ki, "chat", geschwaetz)

    async with klient_fuer("angebot-ki2") as klient:
        await klient.put(
            "/api/settings", json={"llm_base_url": "http://test/v1", "llm_model": "probe"}
        )
        deal_id = await _deal(klient, "KI2")
        antwort = await klient.post(f"/api/ki/deals/{deal_id}/angebotsvorschlag")

    assert antwort.status_code == 502
    assert "kein verwertbares Ergebnis" in antwort.json()["detail"]
