"""Der Eingang aus Insilo.

Der Vertrag steht in insilo/docs/WEBHOOKS.md. Diese Tests halten ihn
nach — vor allem die Signatur und die Idempotenz, denn beides fällt sonst
erst auf der Box auf, und dann fehlen Protokolle oder es gibt sie doppelt.
"""

import hashlib
import hmac
import json
from uuid import uuid4

from httpx import ASGITransport, AsyncClient

from app.main import app
from tests.conftest import klient_fuer


def signiere(secret: str, koerper: bytes) -> str:
    return "sha256=" + hmac.new(secret.encode(), koerper, hashlib.sha256).hexdigest()


def ereignis(titel: str, *, event: str = "meeting.ready", markdown: str | None = None) -> bytes:
    return json.dumps(
        {
            "id": uuid4().hex,
            "event": event,
            "occurred_at": "2026-09-03T14:30:00+00:00",
            "meeting": {
                "id": uuid4().hex,
                "title": titel,
                "status": "ready",
                "recorded_at": "2026-09-03T14:00:00+00:00",
                "duration_sec": 1800,
                "language": "de",
                "tags": [],
            },
            **({"markdown": markdown} if markdown else {}),
        },
        ensure_ascii=False,
    ).encode()


async def _absender():
    """Ein Klient ohne Olares-Kopf — der Absender ist eine Maschine."""
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _quelle(klient) -> tuple[str, str]:
    q = (await klient.post("/api/quellen", json={"name": "Insilo auf der Box"})).json()
    return q["id"], q["secret"]


async def test_geheimnis_kommt_nur_einmal(datenbank):
    async with klient_fuer("eingang-a") as klient:
        angelegt = (await klient.post("/api/quellen", json={"name": "Insilo"})).json()
        assert angelegt["secret"]
        assert angelegt["pfad"] == f"/api/eingang/{angelegt['id']}"

        liste = (await klient.get("/api/quellen")).json()

    assert "secret" not in liste[0], "das Geheimnis darf nie wieder ausgeliefert werden"


async def test_falsche_signatur_wird_abgewiesen(datenbank):
    async with klient_fuer("eingang-b") as klient:
        quelle_id, _ = await _quelle(klient)

    koerper = ereignis("Irgendetwas")
    async with await _absender() as absender:
        antwort = await absender.post(
            f"/api/eingang/{quelle_id}",
            content=koerper,
            headers={
                "X-Insilo-Event": "meeting.ready",
                "X-Insilo-Delivery-ID": uuid4().hex,
                "X-Insilo-Signature": signiere("das-falsche-geheimnis", koerper),
            },
        )
    assert antwort.status_code == 401


async def test_fehlende_signatur_wird_abgewiesen(datenbank):
    async with klient_fuer("eingang-c") as klient:
        quelle_id, _ = await _quelle(klient)

    async with await _absender() as absender:
        antwort = await absender.post(
            f"/api/eingang/{quelle_id}",
            content=ereignis("Ohne Unterschrift"),
            headers={"X-Insilo-Delivery-ID": uuid4().hex},
        )
    assert antwort.status_code == 401


async def test_unbekannte_quelle_wird_abgewiesen(datenbank):
    koerper = ereignis("x")
    async with await _absender() as absender:
        antwort = await absender.post(
            f"/api/eingang/{uuid4()}",
            content=koerper,
            headers={
                "X-Insilo-Delivery-ID": uuid4().hex,
                "X-Insilo-Signature": signiere("egal", koerper),
            },
        )
    assert antwort.status_code == 401


async def test_signatur_wird_ueber_den_rohen_koerper_geprueft(datenbank):
    """Über das geparste JSON zu hashen wäre der klassische Fehler.

    Leerzeichen und Schlüsselreihenfolge ändern den Hash — eine
    Neu-Serialisierung auf Empfängerseite ließe jede echte Auslieferung
    scheitern.
    """
    async with klient_fuer("eingang-d") as klient:
        quelle_id, secret = await _quelle(klient)

    # Derselbe Inhalt, andere Formatierung.
    koerper = b'{"id":"abc","event":"meeting.created","meeting":{"title":"Test",  "id":"m1"}}'
    async with await _absender() as absender:
        antwort = await absender.post(
            f"/api/eingang/{quelle_id}",
            content=koerper,
            headers={
                "X-Insilo-Event": "meeting.created",
                "X-Insilo-Delivery-ID": "abc",
                "X-Insilo-Signature": signiere(secret, koerper),
            },
        )
    assert antwort.status_code == 200


# Was eine Insilo-Besprechung wird, prüft tests/test_besprechungen.py. Hier
# bleibt, was für jede Quelle gilt: Signatur, Idempotenz, Sichtbarkeit —
# an einer Quelle der Art `api`, deren Ereignisse weiter im Eingang warten.


async def _api_quelle(klient) -> tuple[str, str]:
    q = (await klient.post("/api/quellen", json={"name": "Eigene Anbindung", "kind": "api"})).json()
    return q["id"], q["secret"]


async def _schicken(quelle_id: str, secret: str, koerper: bytes, *, event: str = "notiz.neu", lieferung: str | None = None):
    async with await _absender() as absender:
        return await absender.post(
            f"/api/eingang/{quelle_id}",
            content=koerper,
            headers={
                "X-Beacon-Event": event,
                "X-Beacon-Delivery-Id": lieferung or uuid4().hex,
                "X-Beacon-Signature": signiere(secret, koerper),
            },
        )


async def test_wiederholung_legt_nichts_doppelt_an(datenbank):
    """Ein Absender wiederholt bei 5xx. Derselbe Schlüssel darf nur einmal wirken."""
    async with klient_fuer("eingang-e") as klient:
        quelle_id, secret = await _api_quelle(klient)
        koerper = ereignis("Rückruf erbeten", event="notiz.neu")
        lieferung = uuid4().hex

        erst = await _schicken(quelle_id, secret, koerper, lieferung=lieferung)
        zweit = await _schicken(quelle_id, secret, koerper, lieferung=lieferung)

        assert erst.json()["status"] == "angenommen"
        assert zweit.json()["status"] == "schon empfangen"
        assert zweit.json()["eingang_id"] == erst.json()["eingang_id"]
        assert len((await klient.get("/api/eingang")).json()) == 1


async def test_nichts_wird_ueber_den_titel_zugeordnet(datenbank):
    """Bis 0.9.9 legte ein Firmenname im Titel ein Ereignis an den Lead.

    Das war für Insilo gedacht und traf jede Quelle. Jetzt wartet alles, was
    kein Ticket ist, im Eingang, bis ein Mensch es zuordnet.
    """
    async with klient_fuer("eingang-f") as klient:
        quelle_id, secret = await _api_quelle(klient)
        firma = (await klient.post("/api/companies", json={"name": "Nordlicht"})).json()
        deal = (await klient.post("/api/deals", json={"name": "Analyst", "company_id": firma["id"]})).json()

        antwort = await _schicken(quelle_id, secret, ereignis("Erstgespräch Nordlicht", event="notiz.neu"))

        assert antwort.json()["zugeordnet"] is False
        verlauf = (await klient.get(f"/api/activities?deal_id={deal['id']}")).json()
        assert verlauf == []
        assert len((await klient.get("/api/eingang")).json()) == 1


async def test_zuordnen_von_hand(datenbank):
    async with klient_fuer("eingang-i") as klient:
        quelle_id, secret = await _api_quelle(klient)
        firma = (await klient.post("/api/companies", json={"name": "Handfirma"})).json()
        deal = (await klient.post("/api/deals", json={"name": "Handgeschäft", "company_id": firma["id"]})).json()

        await _schicken(quelle_id, secret, ereignis("Ein Posten", event="notiz.neu", markdown="# Inhalt"))
        offen = (await klient.get("/api/eingang")).json()
        assert len(offen) == 1

        antwort = await klient.post(f"/api/eingang/{offen[0]['id']}/zuordnen", json={"deal_id": deal["id"]})
        assert antwort.status_code == 200
        assert (await klient.get(f"/api/activities?deal_id={deal['id']}")).json()
        assert (await klient.get("/api/eingang")).json() == []


async def test_fremder_eingang_bleibt_unsichtbar(datenbank):
    async with klient_fuer("eingang-j") as a, klient_fuer("eingang-k") as b:
        quelle_id, secret = await _api_quelle(a)
        await _schicken(quelle_id, secret, ereignis("Geheim", event="notiz.neu"))

        assert len((await a.get("/api/eingang")).json()) == 1
        assert (await b.get("/api/eingang")).json() == []


async def test_insilo_landet_nicht_mehr_im_eingang(datenbank):
    """Insilo-Gespräche haben seit 0.10.0 ihren eigenen Bereich."""
    async with klient_fuer("eingang-m") as klient:
        quelle_id, secret = await _quelle(klient)
        for event in ("meeting.created", "meeting.ready", "meeting.failed", "test.ping"):
            koerper = ereignis("Termin", event=event, markdown="# Protokoll")
            async with await _absender() as absender:
                antwort = await absender.post(
                    f"/api/eingang/{quelle_id}",
                    content=koerper,
                    headers={
                        "X-Insilo-Event": event,
                        "X-Insilo-Delivery-ID": uuid4().hex,
                        "X-Insilo-Signature": signiere(secret, koerper),
                    },
                )
            assert antwort.status_code == 200, event

        assert (await klient.get("/api/eingang")).json() == []
        assert (await klient.get("/api/eingang?status=zugeordnet")).json() == []
