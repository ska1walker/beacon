"""Eine Suche über alles — und sie sieht nur den eigenen Mandanten."""

from uuid import uuid4

from tests.conftest import klient_fuer


async def test_suche_findet_ueber_alle_objekte(datenbank):
    async with klient_fuer("suche-a") as k:
        f = (await k.post("/api/companies", json={"name": "Nordlicht Reederei", "domain": "nordlicht.de"})).json()
        p = (await k.post("/api/contacts", json={"first_name": "Britta", "last_name": "Nordlicht", "email": f"b-{uuid4().hex[:6]}@x.de", "company_id": f["id"]})).json()
        t = (await k.post("/api/tickets", json={"betreff": "Nordlicht: Drucker streikt"})).json()
        li = (await k.post("/api/listen", json={"name": "Nordlicht-Kunden"})).json()
        e = (await k.get("/api/suche?q=nordlicht")).json()
    arten = {(x["art"], x["id"]) for x in e["treffer"]}
    assert ("firma", f["id"]) in arten and ("kontakt", p["id"]) in arten
    assert ("ticket", t["id"]) in arten and ("liste", li["id"]) in arten
    ticket = next(x for x in e["treffer"] if x["art"] == "ticket")
    assert ticket["pfad"] == f"/tickets/{t['id']}" and ticket["untertitel"].startswith("T-")


async def test_suche_sieht_fremde_mandanten_nicht(datenbank):
    async with klient_fuer("suche-b") as k:
        await k.post("/api/companies", json={"name": "Geheimfirma Süd"})
    async with klient_fuer("suche-c") as fremd:
        e = (await fremd.get("/api/suche?q=Geheimfirma")).json()
    assert e["treffer"] == []


async def test_suche_braucht_einen_begriff(datenbank):
    async with klient_fuer("suche-d") as k:
        assert (await k.get("/api/suche?q=")).status_code == 422
