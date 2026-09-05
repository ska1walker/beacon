"""Listen und Kampagnen — was sonst erst beim ersten Versand auffällt.

Die Liste sagt, wen man meint; der Kontakt, ob man darf; die Kampagne
schreibt nur denen, bei denen beides stimmt — und zählt den Rest. Jeder
Link wird zum Klick-Link je Empfänger, der Abmeldelink hängt an der
Kampagne, und die Zahlen entstehen aus den Zeilen.
"""

import re
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from app import versand
from app.db import acquire_as
from app.oeffentlich import app as oeffentlich
from tests.conftest import klient_fuer
from tests.test_versand import SMTP, Briefkasten, conn_nutzer


@pytest.fixture
def briefkasten(monkeypatch):
    b = Briefkasten()
    monkeypatch.setattr(versand, "senden_smtp", b)
    return b


async def _kontakt(k, einwilligung=None, **felder):
    antwort = await k.post("/api/contacts", json={
        "first_name": "Ann", "last_name": "Peters", "email": f"p-{uuid4().hex[:8]}@fremd.de", **felder,
    })
    assert antwort.status_code == 201, antwort.text
    kontakt = antwort.json()
    if einwilligung:
        r = await k.post(f"/api/contacts/{kontakt['id']}/einwilligung", json={"aktion": einwilligung})
        assert r.status_code == 200, r.text
    return kontakt


async def _statische_liste(k, *kontakte):
    liste = (await k.post("/api/listen", json={"name": "Messe 2026"})).json()
    if kontakte:
        r = await k.post(f"/api/listen/{liste['id']}/mitglieder", json={"contact_ids": [x["id"] for x in kontakte]})
        assert r.status_code == 200, r.text
        liste = r.json()
    return liste


# ---- Listen ------------------------------------------------------------

async def test_statische_liste_zaehlt_gemeinte_und_berechtigte(datenbank):
    async with klient_fuer("li-statisch") as k:
        a = await _kontakt(k, "bestandskunde")
        b = await _kontakt(k)
        liste = await _statische_liste(k, a, b)
        assert liste["art"] == "statisch"
        assert (liste["gemeint"], liste["berechtigt"]) == (2, 1)

        m = (await k.get(f"/api/listen/{liste['id']}/mitglieder")).json()
        assert {x["id"] for x in m} == {a["id"], b["id"]}
        assert all(x["hinzugefuegt_am"] for x in m)

        liste = (await k.delete(f"/api/listen/{liste['id']}/mitglieder/{b['id']}")).json()
        assert liste["gemeint"] == 1
        # Der Kontakt weiß, in welchen Listen er steht.
        assert [x["id"] for x in (await k.get(f"/api/listen/von/{a['id']}")).json()] == [liste["id"]]
        assert (await k.get(f"/api/listen/von/{b['id']}")).json() == []


async def test_aktive_liste_ist_eine_frage_an_den_bestand(datenbank):
    async with klient_fuer("li-aktiv") as k:
        await _kontakt(k, "bestandskunde", job_title="Geschäftsführung")
        await _kontakt(k, job_title="Einkauf")
        antwort = await k.post("/api/listen", json={
            "name": "Entscheider", "art": "aktiv",
            "filter": [{"feld": "job_title", "operator": "enthaelt", "wert": "führung"}],
        })
        assert antwort.status_code == 201, antwort.text
        liste = antwort.json()
        assert (liste["gemeint"], liste["berechtigt"]) == (1, 1)
        # Die Einwilligung ist selbst ein Filterfeld.
        liste = (await k.patch(f"/api/listen/{liste['id']}", json={
            "filter": [{"feld": "marketing_einwilligung", "operator": "ist", "wert": "keine"}],
        })).json()
        assert (liste["gemeint"], liste["berechtigt"]) == (1, 0)
        r = await k.post(f"/api/listen/{liste['id']}/mitglieder", json={"contact_ids": [str(uuid4())]})
        assert r.status_code == 400


async def test_kaputter_filter_wird_nicht_gespeichert(datenbank):
    async with klient_fuer("li-kaputt") as k:
        r = await k.post("/api/listen", json={"name": "x", "art": "aktiv",
                                              "filter": [{"feld": "gibtsnicht", "operator": "ist", "wert": 1}]})
        assert r.status_code == 400


# ---- Kampagnen ---------------------------------------------------------

async def test_kampagne_schreibt_nur_berechtigten_und_zaehlt_den_rest(datenbank, briefkasten):
    async with klient_fuer("ka-start") as k:
        await k.put("/api/settings", json=SMTP)
        ja = await _kontakt(k, "bestandskunde")
        nein = await _kontakt(k)  # keine Einwilligung
        ohne = await _kontakt(k, "bestandskunde")
        await k.patch(f"/api/contacts/{ohne['id']}", json={"email": None})
        liste = await _statische_liste(k, ja, nein, ohne)

        kampagne = (await k.post("/api/kampagnen", json={
            "name": "Herbstpost", "betreff": "Neu für {{firma}}", "liste_id": liste["id"],
            "text": "{{anrede}},\n\nunser Programm: https://aimighty.de/programm — bis bald.\n",
        })).json()
        v = (await k.get(f"/api/kampagnen/{kampagne['id']}/vorschau")).json()
        assert (v["gemeint"], v["berechtigt"], v["uebergangen"]) == (3, 1, 2)
        assert "Guten Tag Ann Peters" in v["beispiel_text"]

        r = await k.post(f"/api/kampagnen/{kampagne['id']}/starten")
        assert r.status_code == 200, r.text
        kampagne = r.json()
        assert kampagne["status"] == "laeuft"
        assert (kampagne["empfaenger"], kampagne["uebergangen"], kampagne["wartend"]) == (1, 2, 1)
        # Einmal ist einmal.
        assert (await k.post(f"/api/kampagnen/{kampagne['id']}/starten")).status_code == 409
        assert (await k.patch(f"/api/kampagnen/{kampagne['id']}", json={"text": "neu"})).status_code == 409

        # Die Schleife schickt — hier von Hand angestoßen.
        async with acquire_as(await conn_nutzer(k)) as conn:
            org = await conn.fetchval("select org_id from public.kampagnen where id = $1", kampagne["id"])
            bilanz = await versand.verarbeiten(conn, org)
        assert bilanz["gesendet"] == 1
        _, m = briefkasten.nachrichten[-1]
        assert m["To"] == ja["email"]
        text = m.get_content()
        assert "aimighty.de/programm" not in text  # umgeschrieben
        klick = re.search(r"https://links\.test/o/k/(\S+)", text)
        assert klick, text
        assert m["List-Unsubscribe"].startswith("<https://links.test/o/abmelden/")

        # Der Klick zählt und leitet weiter; der Abmeldelink zählt an der Kampagne.
        async with AsyncClient(transport=ASGITransport(app=oeffentlich), base_url="http://links.test") as d:
            weiter = await d.get(f"/o/k/{klick.group(1)}")
            assert weiter.status_code == 302 and weiter.headers["location"] == "https://aimighty.de/programm"
            ab = re.search(r"/o/abmelden/(\S+)", text).group(1)
            assert (await d.get(f"/o/abmelden/{ab}")).status_code == 200

        kampagne = (await k.get(f"/api/kampagnen/{kampagne['id']}")).json()
        assert kampagne["status"] == "abgeschlossen"
        assert (kampagne["gesendet"], kampagne["klicks"], kampagne["klicker"], kampagne["abgemeldet"]) == (1, 1, 1, 1)


async def test_ohne_liste_oder_text_kein_start(datenbank, briefkasten):
    async with klient_fuer("ka-leer") as k:
        await k.put("/api/settings", json=SMTP)
        kampagne = (await k.post("/api/kampagnen", json={"name": "Leer"})).json()
        r = await k.post(f"/api/kampagnen/{kampagne['id']}/starten")
        assert r.status_code == 409 and "Betreff" in r.json()["detail"]
        await k.patch(f"/api/kampagnen/{kampagne['id']}", json={"betreff": "x", "text": "y"})
        r = await k.post(f"/api/kampagnen/{kampagne['id']}/starten")
        assert r.status_code == 409 and "Liste" in r.json()["detail"]


async def test_abbrechen_haelt_wartendes_an(datenbank, briefkasten):
    async with klient_fuer("ka-abbruch") as k:
        await k.put("/api/settings", json=SMTP)
        a = await _kontakt(k, "bestandskunde")
        liste = await _statische_liste(k, a)
        kampagne = (await k.post("/api/kampagnen", json={"name": "Stopp", "betreff": "b", "text": "t", "liste_id": liste["id"]})).json()
        await k.post(f"/api/kampagnen/{kampagne['id']}/starten")
        kampagne = (await k.post(f"/api/kampagnen/{kampagne['id']}/abbrechen")).json()
        assert kampagne["status"] == "abgebrochen"
        assert (kampagne["wartend"], kampagne["fehlgeschlagen"]) == (0, 1)
        assert briefkasten.nachrichten == []


async def test_testmail_geht_an_mich_mit_musterwerten(datenbank, briefkasten):
    async with klient_fuer("ka-test") as k:
        await k.put("/api/settings", json={**SMTP, "marketing_absender": "news@aimighty.de", "marketing_absender_name": "AImighty Neuigkeiten"})
        kampagne = (await k.post("/api/kampagnen", json={"name": "T", "betreff": "Hallo {{vorname}}", "text": "{{anrede}}"})).json()
        r = await k.post(f"/api/kampagnen/{kampagne['id']}/testen")
        assert r.status_code == 200, r.text
        konto, m = briefkasten.nachrichten[-1]
        assert r.json()["an"] == "news@aimighty.de"
        assert m["Subject"] == "[Test] Hallo Erika"
        assert m["From"] == "AImighty Neuigkeiten <news@aimighty.de>"


async def test_brevo_ist_der_zweite_weg(datenbank, monkeypatch):
    gesendet = []

    async def brevo(konto, nachricht):
        gesendet.append((konto, nachricht))

    monkeypatch.setattr(versand, "senden_brevo", brevo)
    async with klient_fuer("ka-brevo") as k:
        await k.put("/api/settings", json={**SMTP, "marketing_versand": "brevo", "brevo_api_key": "xkeysib-test"})
        e = (await k.get("/api/settings")).json()
        assert e["brevo_api_key_set"] is True and "brevo_api_key" not in e
        kampagne = (await k.post("/api/kampagnen", json={"name": "B", "betreff": "b", "text": "t"})).json()
        r = await k.post(f"/api/kampagnen/{kampagne['id']}/testen")
        assert r.status_code == 200, r.text
        konto, m = gesendet[-1]
        assert isinstance(konto, versand.Brevo) and konto.api_key == "xkeysib-test"
        assert m["To"] == "kai@aimighty.de"


# ---- Vorlagen ----------------------------------------------------------

async def test_vorlagen_werden_gefuehrt(datenbank):
    async with klient_fuer("vorlagen") as k:
        v = (await k.post("/api/vorlagen", json={"name": "Nachfassen", "betreff": "Kurz nachgefragt, {{vorname}}", "text": "{{anrede}}, …"})).json()
        assert [x["name"] for x in (await k.get("/api/vorlagen")).json()] == ["Nachfassen"]
        v = (await k.patch(f"/api/vorlagen/{v['id']}", json={"name": "Nachfassen II"})).json()
        assert v["name"] == "Nachfassen II"
        assert (await k.delete(f"/api/vorlagen/{v['id']}")).status_code == 204
        assert (await k.get("/api/vorlagen")).json() == []
