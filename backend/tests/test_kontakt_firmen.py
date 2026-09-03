"""Ein Kontakt, mehrere Firmen."""

from tests.conftest import klient_fuer


async def _aufbau(k):
    a = (await k.post("/api/companies", json={"name": "Holding"})).json()
    b = (await k.post("/api/companies", json={"name": "Tochter"})).json()
    person = (await k.post("/api/contacts", json={"first_name": "Sven", "last_name": "Kolb", "company_id": a["id"]})).json()
    return a, b, person


async def test_weitere_firma_verknuepfen(datenbank):
    async with klient_fuer("kf-a") as k:
        a, b, p = await _aufbau(k)
        liste = (await k.post(f"/api/contacts/{p['id']}/firmen", json={"company_id": b["id"], "role": "IT-Leitung"})).json()
        assert [(f["company_name"], f["ist_haupt"]) for f in liste] == [("Holding", True), ("Tochter", False)]
        assert liste[1]["role"] == "IT-Leitung"
        # Die Firmenseite der Tochter zeigt ihn jetzt auch
        namen = [c["last_name"] for c in (await k.get(f"/api/contacts?company_id={b['id']}")).json()]
    assert "Kolb" in namen


async def test_ohne_hauptfirma_wird_die_erste_zur_hauptfirma(datenbank):
    async with klient_fuer("kf-b") as k:
        firma = (await k.post("/api/companies", json={"name": "Erste"})).json()
        p = (await k.post("/api/contacts", json={"first_name": "Ohne", "last_name": "Firma"})).json()
        liste = (await k.post(f"/api/contacts/{p['id']}/firmen", json={"company_id": firma["id"]})).json()
        kontakt = (await k.get(f"/api/contacts/{p['id']}")).json()
    assert liste[0]["ist_haupt"] is True
    assert kontakt["company_id"] == firma["id"]


async def test_hauptfirma_wechseln(datenbank):
    async with klient_fuer("kf-c") as k:
        a, b, p = await _aufbau(k)
        await k.post(f"/api/contacts/{p['id']}/firmen", json={"company_id": b["id"]})
        liste = (await k.post(f"/api/contacts/{p['id']}/firmen/{b['id']}/haupt")).json()
        assert next(f for f in liste if f["ist_haupt"])["company_name"] == "Tochter"
        assert any(f["company_name"] == "Holding" and not f["ist_haupt"] for f in liste), "die alte Hauptfirma bleibt verknüpft"
        kontakt = (await k.get(f"/api/contacts/{p['id']}")).json()
    assert kontakt["company_name"] == "Tochter"


async def test_hauptfirma_loesen_rueckt_nach(datenbank):
    async with klient_fuer("kf-d") as k:
        a, b, p = await _aufbau(k)
        await k.post(f"/api/contacts/{p['id']}/firmen", json={"company_id": b["id"]})
        liste = (await k.delete(f"/api/contacts/{p['id']}/firmen/{a['id']}")).json()
    assert [(f["company_name"], f["ist_haupt"]) for f in liste] == [("Tochter", True)]


async def test_letzte_firma_loesen_laesst_kontakt_ohne_firma(datenbank):
    async with klient_fuer("kf-e") as k:
        a, _, p = await _aufbau(k)
        liste = (await k.delete(f"/api/contacts/{p['id']}/firmen/{a['id']}")).json()
        kontakt = (await k.get(f"/api/contacts/{p['id']}")).json()
    assert liste == []
    assert kontakt["company_id"] is None


async def test_nicht_verknuepfte_firma_wird_nicht_haupt(datenbank):
    async with klient_fuer("kf-f") as k:
        a, b, p = await _aufbau(k)
        antwort = await k.post(f"/api/contacts/{p['id']}/firmen/{b['id']}/haupt")
    assert antwort.status_code == 400


async def test_fremde_firma_laesst_sich_nicht_verknuepfen(datenbank):
    async with klient_fuer("kf-g") as a, klient_fuer("kf-h") as b:
        fremd = (await a.post("/api/companies", json={"name": "Fremd"})).json()
        p = (await b.post("/api/contacts", json={"first_name": "X"})).json()
        antwort = await b.post(f"/api/contacts/{p['id']}/firmen", json={"company_id": fremd["id"]})
    assert antwort.status_code == 404
