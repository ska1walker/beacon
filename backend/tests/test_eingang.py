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


async def test_wiederholung_legt_nichts_doppelt_an(datenbank):
    """Insilo wiederholt bei 5xx. Derselbe Schlüssel darf nur einmal wirken."""
    async with klient_fuer("eingang-e") as klient:
        quelle_id, secret = await _quelle(klient)
        await klient.post("/api/companies", json={"name": "Wiederholfirma"})

        koerper = ereignis("Besprechung mit Wiederholfirma", markdown="# Protokoll")
        lieferung = uuid4().hex
        kopf = {
            "X-Insilo-Event": "meeting.ready",
            "X-Insilo-Delivery-ID": lieferung,
            "X-Insilo-Signature": signiere(secret, koerper),
        }

        async with await _absender() as absender:
            erst = await absender.post(f"/api/eingang/{quelle_id}", content=koerper, headers=kopf)
            zweit = await absender.post(f"/api/eingang/{quelle_id}", content=koerper, headers=kopf)

        assert erst.status_code == 200
        assert erst.json()["status"] == "angenommen"
        assert zweit.status_code == 200
        assert zweit.json()["status"] == "schon empfangen"
        assert zweit.json()["eingang_id"] == erst.json()["eingang_id"]

        posten = (await klient.get("/api/eingang?status=zugeordnet")).json()
        assert len([p for p in posten if p["company_name"] == "Wiederholfirma"]) == 1


async def test_eindeutige_zuordnung_landet_am_deal(datenbank):
    async with klient_fuer("eingang-f") as klient:
        quelle_id, secret = await _quelle(klient)
        firma = (await klient.post("/api/companies", json={"name": "Nordlicht"})).json()
        deal = (
            await klient.post(
                "/api/deals", json={"name": "Analyst", "company_id": firma["id"]}
            )
        ).json()

        koerper = ereignis("Erstgespräch Nordlicht", markdown="# Protokoll\n\nInhalt.")
        async with await _absender() as absender:
            antwort = await absender.post(
                f"/api/eingang/{quelle_id}",
                content=koerper,
                headers={
                    "X-Insilo-Event": "meeting.ready",
                    "X-Insilo-Delivery-ID": uuid4().hex,
                    "X-Insilo-Signature": signiere(secret, koerper),
                },
            )

        assert antwort.json()["zugeordnet"] is True

        verlauf = (await klient.get(f"/api/activities?deal_id={deal['id']}")).json()
        besprechung = next(a for a in verlauf if a["kind"] == "meeting")
        assert besprechung["subject"] == "Erstgespräch Nordlicht"
        assert "Protokoll" in besprechung["body"]


async def test_mehrdeutiges_bleibt_im_eingang(datenbank):
    """Ein Protokoll am falschen Kunden ist schlimmer als eines im Korb."""
    async with klient_fuer("eingang-g") as klient:
        quelle_id, secret = await _quelle(klient)
        for name in ("Meyer GmbH", "Meyer & Söhne"):
            await klient.post("/api/companies", json={"name": name})

        koerper = ereignis("Termin Meyer GmbH und Meyer & Söhne")
        async with await _absender() as absender:
            antwort = await absender.post(
                f"/api/eingang/{quelle_id}",
                content=koerper,
                headers={
                    "X-Insilo-Event": "meeting.ready",
                    "X-Insilo-Delivery-ID": uuid4().hex,
                    "X-Insilo-Signature": signiere(secret, koerper),
                },
            )

        assert antwort.json()["zugeordnet"] is False
        assert "mehrdeutig" in antwort.json()["grund"]

        offen = (await klient.get("/api/eingang")).json()
        assert len(offen) == 1
        assert "mehrdeutig" in offen[0]["zuordnung_grund"]


async def test_nur_fertige_besprechungen_werden_aktivitaet(datenbank):
    """„angelegt" oder „fehlgeschlagen" hat am Deal nichts verloren."""
    async with klient_fuer("eingang-h") as klient:
        quelle_id, secret = await _quelle(klient)
        firma = (await klient.post("/api/companies", json={"name": "Frühfirma"})).json()
        deal = (
            await klient.post("/api/deals", json={"name": "D", "company_id": firma["id"]})
        ).json()

        koerper = ereignis("Aufnahme Frühfirma", event="meeting.created")
        async with await _absender() as absender:
            antwort = await absender.post(
                f"/api/eingang/{quelle_id}",
                content=koerper,
                headers={
                    "X-Insilo-Event": "meeting.created",
                    "X-Insilo-Delivery-ID": uuid4().hex,
                    "X-Insilo-Signature": signiere(secret, koerper),
                },
            )

        assert antwort.json()["zugeordnet"] is False
        verlauf = (await klient.get(f"/api/activities?deal_id={deal['id']}")).json()
        assert [a for a in verlauf if a["kind"] == "meeting"] == []


async def test_zuordnen_von_hand(datenbank):
    async with klient_fuer("eingang-i") as klient:
        quelle_id, secret = await _quelle(klient)
        firma = (await klient.post("/api/companies", json={"name": "Handfirma"})).json()
        deal = (
            await klient.post("/api/deals", json={"name": "Handgeschäft", "company_id": firma["id"]})
        ).json()

        koerper = ereignis("Ein Gespräch ohne Firmennamen", markdown="# Protokoll")
        async with await _absender() as absender:
            await absender.post(
                f"/api/eingang/{quelle_id}",
                content=koerper,
                headers={
                    "X-Insilo-Event": "meeting.ready",
                    "X-Insilo-Delivery-ID": uuid4().hex,
                    "X-Insilo-Signature": signiere(secret, koerper),
                },
            )

        offen = (await klient.get("/api/eingang")).json()
        assert len(offen) == 1

        antwort = await klient.post(
            f"/api/eingang/{offen[0]['id']}/zuordnen", json={"deal_id": deal["id"]}
        )
        assert antwort.status_code == 200

        verlauf = (await klient.get(f"/api/activities?deal_id={deal['id']}")).json()
        assert any(a["kind"] == "meeting" for a in verlauf)
        assert (await klient.get("/api/eingang")).json() == []


async def test_fremder_eingang_bleibt_unsichtbar(datenbank):
    async with klient_fuer("eingang-j") as a, klient_fuer("eingang-k") as b:
        quelle_id, secret = await _quelle(a)
        await a.post("/api/companies", json={"name": "Geheimfirma"})

        koerper = ereignis("Termin Geheimfirma")
        async with await _absender() as absender:
            await absender.post(
                f"/api/eingang/{quelle_id}",
                content=koerper,
                headers={
                    "X-Insilo-Event": "meeting.ready",
                    "X-Insilo-Delivery-ID": uuid4().hex,
                    "X-Insilo-Signature": signiere(secret, koerper),
                },
            )

        assert (await b.get("/api/eingang")).json() == []
        assert (await b.get("/api/eingang?status=zugeordnet")).json() == []


async def test_dieselbe_besprechung_zweimal_zeigt_auf_dieselbe_aktivitaet(datenbank):
    """Ein zweites Ereignis zur selben Besprechung darf nicht ins Leere zeigen.

    Der eindeutige Index verhindert die zweite Aktivität. Ohne die
    Nachsuche stünde der zweite Eingangsposten auf „zugeordnet" und
    zeigte auf nichts.
    """
    async with klient_fuer("eingang-l") as klient:
        quelle_id, secret = await _quelle(klient)
        firma = (await klient.post("/api/companies", json={"name": "Doppelfirma"})).json()
        await klient.post("/api/deals", json={"name": "D", "company_id": firma["id"]})

        besprechung = uuid4().hex

        async def schicken() -> dict:
            koerper = json.dumps(
                {
                    "id": uuid4().hex,
                    "event": "meeting.ready",
                    "occurred_at": "2026-09-03T14:30:00+00:00",
                    "meeting": {
                        "id": besprechung,
                        "title": "Termin Doppelfirma",
                        "status": "ready",
                        "tags": [],
                    },
                    "markdown": "# Protokoll",
                },
                ensure_ascii=False,
            ).encode()
            async with await _absender() as absender:
                antwort = await absender.post(
                    f"/api/eingang/{quelle_id}",
                    content=koerper,
                    headers={
                        "X-Insilo-Event": "meeting.ready",
                        "X-Insilo-Delivery-ID": uuid4().hex,
                        "X-Insilo-Signature": signiere(secret, koerper),
                    },
                )
            return antwort.json()

        erst = await schicken()
        zweit = await schicken()

        assert erst["eingang_id"] != zweit["eingang_id"], "zwei Auslieferungen, zwei Posten"
        assert zweit["zugeordnet"] is True

        zugeordnet = (await klient.get("/api/eingang?status=zugeordnet")).json()
        posten = [p for p in zugeordnet if p["titel"] == "Termin Doppelfirma"]
        assert len(posten) == 2

        # Aber nur eine Aktivität — sonst stünde das Protokoll doppelt am Deal.
        deal_id = posten[0]["deal_id"]
        verlauf = (await klient.get(f"/api/activities?deal_id={deal_id}")).json()
        assert len([a for a in verlauf if a["kind"] == "meeting"]) == 1
