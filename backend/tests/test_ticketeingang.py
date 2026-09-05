"""Tickets, die von einer Maschine kommen.

Vier Dinge fallen sonst erst im Betrieb auf, und dann teuer: dass die
SLA-Uhr am falschen Zeitpunkt startet, dass ein Absender ohne Kontakt
unbeantwortbar wird, dass eine Wiederholung ein zweites Ticket erzeugt,
und dass eine Quelle ohne Freigabe durchregiert.
"""

import hashlib
import hmac
import json
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from httpx import ASGITransport, AsyncClient

from app.main import app
from tests.conftest import klient_fuer


def signiere(secret: str, koerper: bytes) -> str:
    return "sha256=" + hmac.new(secret.encode(), koerper, hashlib.sha256).hexdigest()


def anfrage(betreff: str, **felder) -> bytes:
    ticket = {"betreff": betreff, **felder}
    return json.dumps(
        {"id": uuid4().hex, "event": "ticket.erstellt", "ticket": ticket},
        ensure_ascii=False,
    ).encode()


async def _absender():
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _schicke(quelle_id: str, secret: str, koerper: bytes, *, alt: str = "beacon"):
    kopf = {
        f"X-{alt.title()}-Event": "ticket.erstellt",
        f"X-{alt.title()}-Delivery-Id": uuid4().hex,
        f"X-{alt.title()}-Signature": signiere(secret, koerper),
        "Content-Type": "application/json",
    }
    async with await _absender() as a:
        return await a.post(f"/api/eingang/{quelle_id}", content=koerper, headers=kopf)


async def test_aus_der_schnittstelle_wird_ein_ticket(datenbank):
    async with klient_fuer("tick-api") as k:
        q = (await k.post("/api/quellen", json={"name": "Zapier", "kind": "api"})).json()

        koerper = anfrage(
            "Drucker im zweiten Stock streikt",
            beschreibung="Papierstau, lässt sich nicht beheben.",
            prioritaet="hoch",
            kategorie="Hardware",
            absender={"email": "neu@fremd.de", "name": "Frau Peters"},
        )
        antwort = await _schicke(q["id"], q["secret"], koerper)
        assert antwort.status_code == 200, antwort.text
        assert antwort.json()["ticket_id"]

        t = (await k.get(f"/api/tickets/{antwort.json()['ticket_id']}")).json()
        assert t["betreff"] == "Drucker im zweiten Stock streikt"
        assert t["prioritaet"] == "hoch"
        assert t["quelle"] == "api"
        assert t["kategorie"] == "Hardware"
        # Der Absender bleibt am Ticket, auch ohne Kontakt dahinter —
        # sonst kann niemand antworten.
        assert t["absender_email"] == "neu@fremd.de"
        assert t["absender_name"] == "Frau Peters"
        assert t["contact_id"] is None


async def test_bekannter_absender_wird_zugeordnet(datenbank):
    async with klient_fuer("tick-kontakt") as k:
        firma = (await k.post("/api/companies", json={"name": "Werft Nord"})).json()
        kontakt = (await k.post("/api/contacts", json={
            "first_name": "Bernd", "last_name": "Meyer",
            "email": "b.meyer@werft-nord.de", "company_id": firma["id"],
        })).json()
        q = (await k.post("/api/quellen", json={"name": "Bot", "kind": "bot"})).json()

        koerper = anfrage("Kran hakt", absender={"email": "B.Meyer@Werft-Nord.de"})
        v = (await _schicke(q["id"], q["secret"], koerper)).json()

        t = (await k.get(f"/api/tickets/{v['ticket_id']}")).json()
        # Groß- und Kleinschreibung darf keine Rolle spielen.
        assert t["contact_id"] == kontakt["id"]
        assert t["company_id"] == firma["id"]
        assert t["quelle"] == "bot"
        assert "trifft einen Kontakt" in v["grund"]


async def test_sla_uhr_startet_beim_absender(datenbank):
    """Ein Ereignis, das drei Stunden in der Warteschlange hing, ist drei
    Stunden alt. Wer die Uhr beim Lesen startet, misst sich selbst."""
    async with klient_fuer("tick-sla") as k:
        q = (await k.post("/api/quellen", json={"name": "API", "kind": "api"})).json()
        vorhin = datetime.now(UTC) - timedelta(hours=3)

        koerper = json.dumps({
            "id": uuid4().hex, "event": "ticket.erstellt",
            "occurred_at": vorhin.isoformat(),
            "ticket": {"betreff": "Alt", "prioritaet": "mittel"},
        }).encode()
        v = (await _schicke(q["id"], q["secret"], koerper)).json()

        t = (await k.get(f"/api/tickets/{v['ticket_id']}")).json()
        faellig = datetime.fromisoformat(t["faellig_am"])
        # Die Frist rechnet ab dem Eingang beim Absender, nicht ab jetzt.
        abstand = (faellig - datetime.now(UTC)).total_seconds() / 3600
        vorgabe = 24  # mittel, laut SLA-Vorgabe
        assert vorgabe - 4 < abstand < vorgabe - 2, f"{abstand} Stunden"


async def test_wiederholung_legt_kein_zweites_ticket_an(datenbank):
    async with klient_fuer("tick-idem") as k:
        q = (await k.post("/api/quellen", json={"name": "API", "kind": "api"})).json()
        koerper = anfrage("Nur einmal")
        lieferung = uuid4().hex
        kopf = {
            "X-Beacon-Event": "ticket.erstellt",
            "X-Beacon-Delivery-Id": lieferung,
            "X-Beacon-Signature": signiere(q["secret"], koerper),
            "Content-Type": "application/json",
        }
        async with await _absender() as a:
            erste = await a.post(f"/api/eingang/{q['id']}", content=koerper, headers=kopf)
            zweite = await a.post(f"/api/eingang/{q['id']}", content=koerper, headers=kopf)

        assert erste.json()["ticket_id"]
        assert zweite.json()["status"] == "schon empfangen"
        assert len((await k.get("/api/tickets")).json()) == 1


async def test_quelle_ohne_freigabe_regiert_nicht_durch(datenbank):
    """Was von einem öffentlichen Formular kommt, wartet im Eingang."""
    async with klient_fuer("tick-formular") as k:
        q = (await k.post("/api/quellen", json={
            "name": "Website-Formular", "kind": "formular", "tickets_direkt": False,
        })).json()

        v = (await _schicke(q["id"], q["secret"], anfrage("Aus dem Netz"))).json()
        assert "ticket_id" not in v
        assert "wartet im Eingang" in v["hinweis"]
        assert (await k.get("/api/tickets")).json() == []
        assert len((await k.get("/api/eingang")).json()) == 1


async def test_ohne_betreff_kein_ticket(datenbank):
    async with klient_fuer("tick-leer") as k:
        q = (await k.post("/api/quellen", json={"name": "API", "kind": "api"})).json()
        koerper = json.dumps({"id": uuid4().hex, "event": "ticket.erstellt",
                              "ticket": {"beschreibung": "nur Text"}}).encode()
        antwort = await _schicke(q["id"], q["secret"], koerper)
        assert antwort.status_code == 400
        assert "Betreff" in antwort.json()["detail"]
        assert (await k.get("/api/tickets")).json() == []


async def test_englische_felder_gehen_auch(datenbank):
    """Wer eine Schnittstelle bedient, soll nicht an der Sprache scheitern."""
    async with klient_fuer("tick-en") as k:
        q = (await k.post("/api/quellen", json={"name": "API", "kind": "api"})).json()
        koerper = json.dumps({
            "id": uuid4().hex, "event": "ticket.created",
            "subject": "Printer jam", "body": "Second floor.",
            "priority": "dringend", "from": {"email": "x@y.de", "name": "Ann"},
        }).encode()
        v = (await _schicke(q["id"], q["secret"], koerper)).json()
        t = (await k.get(f"/api/tickets/{v['ticket_id']}")).json()
        assert t["betreff"] == "Printer jam"
        assert t["prioritaet"] == "dringend"
        assert t["absender_name"] == "Ann"


async def test_insilo_kopfzeilen_bleiben_gueltig(datenbank):
    """Insilo ändert seinen Vertrag nicht unsertwegen."""
    async with klient_fuer("tick-alias") as k:
        q = (await k.post("/api/quellen", json={"name": "Alt", "kind": "api"})).json()
        koerper = anfrage("Über den alten Kopf")
        antwort = await _schicke(q["id"], q["secret"], koerper, alt="insilo")
        assert antwort.status_code == 200
        assert antwort.json()["ticket_id"]
