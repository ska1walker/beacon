"""Die Art einer Quelle ist Teil des Vertrags — und ausgehende Post hat
eine Zustell-Kennung, ein Wiederholverfahren und einen Faden.

Drei Nachweise: Ein Insilo-Geheimnis öffnet den Post-Endpunkt nicht (und
umgekehrt). Zwei Aufträge mit derselben Kennung erzeugen beim Empfänger
eine Mail. Nach dem Senden steht die Message-ID des Dienstes am
Verlaufseintrag.
"""

import hashlib
import hmac
import json
from uuid import uuid4

from httpx import ASGITransport, AsyncClient

from app.main import app
from app.routers import post as modul
from tests.conftest import klient_fuer


def sig(secret: str, body: bytes) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


async def _draussen():
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _quelle(k, kind: str):
    q = (await k.post("/api/quellen", json={"name": kind, "kind": kind})).json()
    assert q["kind"] == kind, q
    return q


# ---- Art beim Empfang --------------------------------------------------

async def test_insilo_geheimnis_oeffnet_den_post_endpunkt_nicht(datenbank):
    async with klient_fuer("qa-post") as k:
        insilo = await _quelle(k, "insilo")
        post = await _quelle(k, "relay")
        assert post["pfad"].startswith("/api/post/eingang/")
        assert insilo["pfad"].startswith("/api/eingang/")
    koerper = json.dumps({"message_id": "<m1@fremd.de>", "from": "a@fremd.de", "subject": "Hi", "text": "t"}).encode()
    async with await _draussen() as d:
        # Insilo-Quelle am Post-Endpunkt: 401, obwohl die Signatur stimmt.
        r = await d.post(f"/api/post/eingang/{insilo['id']}", content=koerper,
                         headers={"Content-Type": "application/json", "X-Post-Signature": sig(insilo["secret"], koerper)})
        assert r.status_code == 401, r.text
        # Die richtige Art kommt durch.
        r = await d.post(f"/api/post/eingang/{post['id']}", content=koerper,
                         headers={"Content-Type": "application/json", "X-Post-Signature": sig(post["secret"], koerper)})
        assert r.status_code == 200, r.text


async def test_post_geheimnis_oeffnet_den_ereignis_endpunkt_nicht(datenbank):
    async with klient_fuer("qa-ereignis") as k:
        post = await _quelle(k, "relay")
    koerper = json.dumps({"id": uuid4().hex, "event": "ticket.erstellt", "ticket": {"betreff": "x"}}).encode()
    async with await _draussen() as d:
        r = await d.post(f"/api/eingang/{post['id']}", content=koerper, headers={
            "Content-Type": "application/json", "X-Beacon-Event": "ticket.erstellt",
            "X-Beacon-Delivery-Id": uuid4().hex, "X-Beacon-Signature": sig(post["secret"], koerper)})
        assert r.status_code == 401, r.text


async def test_unbekannte_art_wird_nicht_angelegt(datenbank):
    async with klient_fuer("qa-art") as k:
        assert (await k.post("/api/quellen", json={"name": "x", "kind": "telepathie"})).status_code == 422


# ---- Ausgehende Post ---------------------------------------------------

class Relay:
    """Ein Postdienst, der sich merkt, was ankam, und Message-IDs vergibt."""

    def __init__(self, *, fehler_vorab: int = 0):
        self.aufrufe: list[dict] = []
        self.fehler_vorab = fehler_vorab

    def klient(self):
        relay = self

        class Antwort:
            def __init__(self, status, daten):
                self.status_code = status
                self._daten = daten

            def json(self):
                return self._daten

        class Klient:
            def __init__(self, *a, **kw):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                pass

            async def post(self, url, content=None, headers=None):
                relay.aufrufe.append({"url": url, "content": content, "headers": headers})
                if relay.fehler_vorab > 0:
                    relay.fehler_vorab -= 1
                    return Antwort(503, {})
                return Antwort(200, {"message_id": f"<{headers['X-Post-Delivery-ID']}@relay.test>"})

        return Klient


async def test_zustellkennung_wiederholung_und_faden(datenbank, monkeypatch):
    relay = Relay()
    monkeypatch.setattr(modul.httpx, "AsyncClient", relay.klient())
    async with klient_fuer("qa-senden") as k:
        await k.put("/api/settings", json={"mail_endpoint_url": "http://relay.test/send", "mail_endpoint_secret": "geheim", "mail_absender": "kai@aimighty.de"})
        p = (await k.post("/api/contacts", json={"first_name": "A", "last_name": "V", "email": f"v-{uuid4().hex[:6]}@nordlicht.de"})).json()
        auftrag = {"contact_id": p["id"], "subject": "Angebot", "text": "Sehr geehrte …", "delivery_id": "auftrag-4711"}
        eins = (await k.post("/api/post/senden", json=auftrag)).json()
        zwei = (await k.post("/api/post/senden", json=auftrag)).json()
        verlauf = (await k.get(f"/api/activities?contact_id={p['id']}")).json()

    # Zwei identische Aufträge, derselbe Kopf, ein Aufruf beim Dienst.
    assert len(relay.aufrufe) == 1
    assert relay.aufrufe[0]["headers"]["X-Post-Delivery-ID"] == "auftrag-4711"
    assert relay.aufrufe[0]["headers"]["X-Post-Signature"] == sig("geheim", relay.aufrufe[0]["content"])
    assert json.loads(relay.aufrufe[0]["content"])["delivery_id"] == "auftrag-4711"
    assert zwei["wiederholung"] is True and zwei["activity_id"] == eins["activity_id"]
    # Und die Message-ID des Dienstes steht am Verlaufseintrag.
    mail = next(a for a in verlauf if a["kind"] == "email")
    assert mail["payload"]["message_id"] == "<auftrag-4711@relay.test>"
    assert mail["payload"]["delivery_id"] == "auftrag-4711"
    assert eins["message_id"] == "<auftrag-4711@relay.test>"


async def test_wiederholung_mit_backoff_bei_ausfall(datenbank, monkeypatch):
    relay = Relay(fehler_vorab=2)
    monkeypatch.setattr(modul.httpx, "AsyncClient", relay.klient())
    monkeypatch.setattr(modul, "WIEDERHOLUNGEN", (0.0, 0.0, 0.0))  # ohne Warten im Test
    async with klient_fuer("qa-backoff") as k:
        await k.put("/api/settings", json={"mail_endpoint_url": "http://relay.test/send", "mail_endpoint_secret": "g", "mail_absender": "kai@aimighty.de"})
        p = (await k.post("/api/contacts", json={"first_name": "B", "last_name": "V", "email": f"b-{uuid4().hex[:6]}@nordlicht.de"})).json()
        r = await k.post("/api/post/senden", json={"contact_id": p["id"], "subject": "S", "text": "T"})
        assert r.status_code == 200, r.text
    # Zweimal 503, beim dritten Mal durch — dieselbe Kennung bei jedem Anlauf.
    assert len(relay.aufrufe) == 3
    assert len({a["headers"]["X-Post-Delivery-ID"] for a in relay.aufrufe}) == 1


async def test_nach_allen_anlaeufen_502(datenbank, monkeypatch):
    relay = Relay(fehler_vorab=9)
    monkeypatch.setattr(modul.httpx, "AsyncClient", relay.klient())
    monkeypatch.setattr(modul, "WIEDERHOLUNGEN", (0.0, 0.0, 0.0))
    async with klient_fuer("qa-502") as k:
        await k.put("/api/settings", json={"mail_endpoint_url": "http://relay.test/send", "mail_endpoint_secret": "g", "mail_absender": "kai@aimighty.de"})
        p = (await k.post("/api/contacts", json={"first_name": "C", "last_name": "V", "email": f"c-{uuid4().hex[:6]}@nordlicht.de"})).json()
        r = await k.post("/api/post/senden", json={"contact_id": p["id"], "subject": "S", "text": "T"})
        assert r.status_code == 502
        # Nichts im Verlauf — was nie ankam, war keine Mail.
        assert [a for a in (await k.get(f"/api/activities?contact_id={p['id']}")).json() if a["kind"] == "email"] == []


# ---- Probe ---------------------------------------------------------------

async def test_probe_verlangt_anmeldung(datenbank):
    async with await _draussen() as d:
        assert (await d.get("/api/fragen/probe?frage=Wer+hat+Serverraum")).status_code == 401
    async with klient_fuer("qa-probe") as k:
        assert (await k.get("/api/fragen/probe?frage=Wer+hat+Serverraum")).status_code == 200
