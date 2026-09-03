"""Was hinter den nachgereichten Knöpfen hängt: Verlustgründe, Verlauf,
Aufgaben mit Bezug — und die Post nach dem Vertrag aus post.py."""

import hashlib
import hmac
import json

from httpx import ASGITransport, AsyncClient

from app.main import app
from tests.conftest import klient_fuer


async def test_verlustgrund_anlegen_und_umbenennen(datenbank):
    async with klient_fuer("kn-a") as k:
        g = (await k.post("/api/verlustgruende", json={"name": "Hardware zu teuer"})).json()
        u = (await k.patch(f"/api/verlustgruende/{g['id']}", json={"name": "Hardwarepreis"})).json()
        assert u["name"] == "Hardwarepreis"
        await k.patch(f"/api/verlustgruende/{g['id']}", json={"is_active": False})
        namen = [x["name"] for x in (await k.get("/api/verlustgruende")).json()]
    assert "Hardwarepreis" not in namen


async def test_notiz_aendern_und_zuruecknehmen(datenbank):
    async with klient_fuer("kn-b") as k:
        f = (await k.post("/api/companies", json={"name": "F"})).json()
        n = (await k.post("/api/activities", json={"kind": "note", "body": "falsch", "company_id": f["id"]})).json()
        u = (await k.patch(f"/api/activities/{n['id']}", json={"body": "richtig"})).json()
        assert u["body"] == "richtig"
        assert (await k.delete(f"/api/activities/{n['id']}")).status_code == 204
        verlauf = (await k.get(f"/api/activities?company_id={f['id']}")).json()
    assert verlauf == []


async def test_geschichte_bleibt_unantastbar(datenbank):
    async with klient_fuer("kn-c") as k:
        stufen = (await k.get("/api/pipelines")).json()[0]["stages"]
        d = (await k.post("/api/deals", json={"name": "D"})).json()
        await k.post(f"/api/deals/{d['id']}/stage", json={"stage_id": stufen[1]["id"]})
        wechsel = next(a for a in (await k.get(f"/api/activities?deal_id={d['id']}")).json() if a["kind"] == "stage_change")
        assert (await k.delete(f"/api/activities/{wechsel['id']}")).status_code == 409
        assert (await k.patch(f"/api/activities/{wechsel['id']}", json={"body": "x"})).status_code == 409


async def test_aufgabe_kennt_ihr_geschaeft(datenbank):
    async with klient_fuer("kn-d") as k:
        f = (await k.post("/api/companies", json={"name": "Bezugsfirma"})).json()
        d = (await k.post("/api/deals", json={"name": "Bezugsgeschäft", "company_id": f["id"]})).json()
        await k.post("/api/tasks", json={"title": "T", "deal_id": d["id"], "company_id": f["id"]})
        t = (await k.get("/api/tasks?status=open")).json()[0]
    assert t["deal_name"] == "Bezugsgeschäft"
    assert t["company_name"] == "Bezugsfirma"


# ---- Post -----------------------------------------------------------------

def sig(secret: str, body: bytes) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


async def test_senden_ohne_postausgang_sagt_das(datenbank):
    async with klient_fuer("kn-e") as k:
        p = (await k.post("/api/contacts", json={"first_name": "A", "last_name": "B", "email": "a@b.de"})).json()
        antwort = await k.post("/api/post/senden", json={"contact_id": p["id"], "subject": "Hallo", "text": "Text"})
    assert antwort.status_code == 409


async def test_senden_signiert_und_haelt_fest(datenbank, monkeypatch):
    """Der Postausgang bekommt einen signierten POST; der Verlauf den Eintrag."""

    from app.routers import post as modul

    gesehen = {}

    class Antwort:
        status_code = 200
        def raise_for_status(self):
            pass

    class Klient:
        def __init__(self, *a, **kw):
            pass
        async def __aenter__(self):
            return self
        async def __aexit__(self, *a):
            pass
        async def post(self, url, content=None, headers=None):
            gesehen.update(url=url, content=content, headers=headers)
            return Antwort()

    monkeypatch.setattr(modul.httpx, "AsyncClient", Klient)
    async with klient_fuer("kn-f") as k:
        await k.put("/api/settings", json={"mail_endpoint_url": "http://relay.test/send", "mail_endpoint_secret": "geheim", "mail_absender": "kai@aimighty.de"})
        p = (await k.post("/api/contacts", json={"first_name": "Andrea", "last_name": "V", "email": "a.v@nordlicht.de"})).json()
        antwort = await k.post("/api/post/senden", json={"contact_id": p["id"], "subject": "Angebot", "text": "Sehr geehrte …"})
        assert antwort.status_code == 200
        verlauf = (await k.get(f"/api/activities?contact_id={p['id']}")).json()

    assert gesehen["url"] == "http://relay.test/send"
    assert gesehen["headers"]["X-Post-Signature"] == sig("geheim", gesehen["content"])
    body = json.loads(gesehen["content"])
    assert body["to"] == "a.v@nordlicht.de" and body["from"] == "kai@aimighty.de"
    assert verlauf[0]["kind"] == "email" and verlauf[0]["payload"]["richtung"] == "ausgehend"


async def test_eingehende_mail_landet_am_kontakt(datenbank):
    async with klient_fuer("kn-g") as k:
        q = (await k.post("/api/quellen", json={"name": "Relay", "kind": "relay"})).json()
        f = (await k.post("/api/companies", json={"name": "Nordlicht"})).json()
        p = (await k.post("/api/contacts", json={"first_name": "Andrea", "last_name": "V", "email": "A.V@Nordlicht.de", "company_id": f["id"]})).json()
        body = json.dumps({"message_id": "m1", "from": "a.v@nordlicht.de", "to": ["kai@aimighty.de"], "subject": "Rückfrage", "text": "Wann?", "received_at": "2026-09-03T10:00:00+00:00"}).encode()
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as maschine:
            a = await maschine.post(f"/api/post/eingang/{q['id']}", content=body, headers={"X-Post-Event": "mail.received", "X-Post-Delivery-ID": "m1", "X-Post-Signature": sig(q["secret"], body)})
            b = await maschine.post(f"/api/post/eingang/{q['id']}", content=body, headers={"X-Post-Event": "mail.received", "X-Post-Delivery-ID": "m1", "X-Post-Signature": sig(q["secret"], body)})
        verlauf = (await k.get(f"/api/activities?contact_id={p['id']}")).json()
    assert a.json()["zugeordnet"] is True
    assert b.json()["status"] == "schon empfangen"
    assert len([x for x in verlauf if x["kind"] == "email"]) == 1
    assert verlauf[0]["subject"] == "Von a.v@nordlicht.de: Rückfrage"


async def test_unbekannter_absender_wartet_im_eingang(datenbank):
    async with klient_fuer("kn-h") as k:
        q = (await k.post("/api/quellen", json={"name": "Relay", "kind": "relay"})).json()
        body = json.dumps({"message_id": "m2", "from": "fremd@example.org", "subject": "Hi", "text": "…"}).encode()
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as maschine:
            a = await maschine.post(f"/api/post/eingang/{q['id']}", content=body, headers={"X-Post-Delivery-ID": "m2", "X-Post-Signature": sig(q["secret"], body)})
        offen = (await k.get("/api/eingang")).json()
    assert a.json()["zugeordnet"] is False
    assert len(offen) == 1 and "nicht im CRM" in offen[0]["zuordnung_grund"]


async def test_falsche_signatur_an_der_post(datenbank):
    async with klient_fuer("kn-i") as k:
        q = (await k.post("/api/quellen", json={"name": "Relay", "kind": "relay"})).json()
    body = b'{"message_id":"m3","from":"x@y.de"}'
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as maschine:
        a = await maschine.post(f"/api/post/eingang/{q['id']}", content=body, headers={"X-Post-Delivery-ID": "m3", "X-Post-Signature": sig("falsch", body)})
    assert a.status_code == 401
