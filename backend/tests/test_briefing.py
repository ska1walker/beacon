"""Das Tagesbriefing.

Geprüft wird vor allem, dass die Zahlen aus der Datenbank kommen und
nicht aus einem Modell. Ein Briefing, dem man nicht trauen kann, liest
niemand zweimal.
"""

from datetime import date, timedelta

from tests.conftest import klient_fuer


async def test_leeres_briefing_ist_leer(datenbank):
    async with klient_fuer("brief-leer") as klient:
        b = (await klient.get("/api/briefing")).json()
    assert b["gesamt"] == 0
    assert b["faellige_aufgaben"] == []


async def test_faellige_und_ueberfaellige_aufgaben(datenbank):
    async with klient_fuer("brief-aufgaben") as klient:
        firma = (await klient.post("/api/companies", json={"name": "Brieffirma"})).json()
        await klient.post(
            "/api/tasks",
            json={
                "title": "Heute fällig",
                "due_at": f"{date.today()}T09:00:00",
                "company_id": firma["id"],
            },
        )
        await klient.post(
            "/api/tasks",
            json={
                "title": "Längst überfällig",
                "due_at": f"{date.today() - timedelta(days=5)}T09:00:00",
                "company_id": firma["id"],
            },
        )
        # Eine ohne Frist und eine in der Zukunft dürfen nicht auftauchen.
        await klient.post("/api/tasks", json={"title": "Irgendwann"})
        await klient.post(
            "/api/tasks",
            json={"title": "Nächste Woche", "due_at": f"{date.today() + timedelta(days=7)}T09:00:00"},
        )

        b = (await klient.get("/api/briefing")).json()

    titel = [p["titel"] for p in b["faellige_aufgaben"]]
    assert titel == ["Längst überfällig", "Heute fällig"], "nach Fälligkeit sortiert"
    assert "Irgendwann" not in titel
    assert "Nächste Woche" not in titel

    ueberfaellig = next(p for p in b["faellige_aufgaben"] if p["titel"] == "Längst überfällig")
    assert ueberfaellig["hinweis"] == "überfällig"
    assert ueberfaellig["tage"] == 5


async def test_geschaeft_mit_verstrichenem_datum(datenbank):
    async with klient_fuer("brief-ueberfaellig") as klient:
        firma = (await klient.post("/api/companies", json={"name": "Spätfirma"})).json()
        await klient.post(
            "/api/deals",
            json={
                "name": "Längst fällig",
                "company_id": firma["id"],
                "amount_cents": 1450000,
                "close_date": str(date.today() - timedelta(days=30)),
            },
        )
        b = (await klient.get("/api/briefing")).json()

    assert len(b["ueberfaellige_geschaefte"]) == 1
    posten = b["ueberfaellige_geschaefte"][0]
    assert posten["tage"] == 30
    assert posten["betrag_cents"] == 1450000
    assert "Spätfirma" in posten["hinweis"]


async def test_gewonnenes_geschaeft_taucht_nicht_auf(datenbank):
    """Ein abgeschlossenes Geschäft ist nicht überfällig, es ist fertig."""
    async with klient_fuer("brief-gewonnen") as klient:
        stufen = (await klient.get("/api/pipelines")).json()[0]["stages"]
        gewonnen = next(s for s in stufen if s["kind"] == "won")
        deal = (
            await klient.post(
                "/api/deals",
                json={"name": "Abgeschlossen", "close_date": str(date.today() - timedelta(days=10))},
            )
        ).json()
        await klient.post(f"/api/deals/{deal['id']}/stage", json={"stage_id": gewonnen["id"]})

        b = (await klient.get("/api/briefing")).json()

    assert b["ueberfaellige_geschaefte"] == []
    assert b["verstummte_geschaefte"] == []


async def test_fortgeschritten_ohne_naechsten_schritt(datenbank):
    """Frühe Stufen bleiben außen vor — dort ist ein fehlender Schritt normal."""
    async with klient_fuer("brief-schritt") as klient:
        stufen = (await klient.get("/api/pipelines")).json()[0]["stages"]
        vorfuehrung = next(s for s in stufen if s["name"] == "Vorführung")

        # Bleibt in der ersten Stufe stehen und darf deshalb nicht auftauchen.
        await klient.post("/api/deals", json={"name": "Ganz am Anfang"})
        spaet = (
            await klient.post("/api/deals", json={"name": "Schon weit", "amount_cents": 990000})
        ).json()
        await klient.post(f"/api/deals/{spaet['id']}/stage", json={"stage_id": vorfuehrung["id"]})

        mit_schritt = (
            await klient.post(
                "/api/deals", json={"name": "Weit und geplant", "next_step": "Termin am Montag"}
            )
        ).json()
        await klient.post(
            f"/api/deals/{mit_schritt['id']}/stage", json={"stage_id": vorfuehrung["id"]}
        )

        b = (await klient.get("/api/briefing")).json()

    titel = [p["titel"] for p in b["ohne_naechsten_schritt"]]
    assert "Schon weit" in titel
    assert "Ganz am Anfang" not in titel, "in der ersten Stufe ist das normal"
    assert "Weit und geplant" not in titel


async def test_ablaufende_angebote(datenbank):
    async with klient_fuer("brief-angebot") as klient:
        deal = (await klient.post("/api/deals", json={"name": "Angebotsgeschäft"})).json()

        bald = (
            await klient.post(
                "/api/quotes",
                json={"deal_id": deal["id"], "valid_until": str(date.today() + timedelta(days=3))},
            )
        ).json()
        await klient.post(f"/api/quotes/{bald['id']}/status", json={"status": "sent"})

        # Ein Entwurf läuft nicht ab — er liegt ja bei niemandem.
        await klient.post(
            "/api/quotes",
            json={"deal_id": deal["id"], "valid_until": str(date.today() + timedelta(days=2))},
        )
        # Und eines weit in der Zukunft drängt nicht.
        spaet = (
            await klient.post(
                "/api/quotes",
                json={"deal_id": deal["id"], "valid_until": str(date.today() + timedelta(days=60))},
            )
        ).json()
        await klient.post(f"/api/quotes/{spaet['id']}/status", json={"status": "sent"})

        b = (await klient.get("/api/briefing")).json()

    assert len(b["ablaufende_angebote"]) == 1
    assert b["ablaufende_angebote"][0]["tage"] == 3


async def test_briefingtext_ohne_modell_meldet_das(datenbank):
    async with klient_fuer("brief-ki") as klient:
        await klient.post(
            "/api/tasks", json={"title": "Etwas", "due_at": f"{date.today()}T09:00:00"}
        )
        antwort = await klient.post("/api/briefing/text")
    assert antwort.status_code == 409


async def test_briefingtext_bei_leerer_lage_ruft_kein_modell(datenbank, monkeypatch):
    """Nichts zu tun ist keine Frage an ein Sprachmodell."""
    from app.routers import briefing as modul

    async def darf_nicht(*args, **kwargs):
        raise AssertionError("es wurde ein Modell aufgerufen, obwohl nichts anlag")

    monkeypatch.setattr(modul, "chat", darf_nicht)

    async with klient_fuer("brief-still") as klient:
        antwort = await klient.post("/api/briefing/text")

    assert antwort.status_code == 200
    assert "Nichts liegt an" in antwort.json()["text"]


async def test_offener_eingang_steht_im_briefing(datenbank):
    """Was niemandem zugeordnet ist, darf morgens nicht unsichtbar sein."""
    import hashlib
    import hmac
    import json
    from uuid import uuid4

    from httpx import ASGITransport, AsyncClient

    from app.main import app

    async with klient_fuer("brief-eingang") as klient:
        q = (await klient.post("/api/quellen", json={"name": "Insilo"})).json()
        body = json.dumps({"id": uuid4().hex, "event": "meeting.ready", "meeting": {"id": "m", "title": "Ohne Firma", "tags": []}, "markdown": "#"}).encode()
        sig = "sha256=" + hmac.new(q["secret"].encode(), body, hashlib.sha256).hexdigest()
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as maschine:
            await maschine.post(f"/api/eingang/{q['id']}", content=body, headers={"X-Insilo-Event": "meeting.ready", "X-Insilo-Delivery-ID": uuid4().hex, "X-Insilo-Signature": sig})
        b = (await klient.get("/api/briefing")).json()

    assert [p["titel"] for p in b["offener_eingang"]] == ["Ohne Firma"]
    assert b["gesamt"] == 1
