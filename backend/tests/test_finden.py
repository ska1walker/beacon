"""Beschreiben statt tippen.

Nachgebaute Welt: ein Suchdienst im SearXNG-Format, drei Websites, ein
Modell aus dem Skript. Geprüft wird, was uns gehört — dass Kandidaten nur
aus den Treffern kommen, dass Verzeichnisse keine Website sind, dass eine
Person ohne belegten Nachnamen keine Person ist, und dass ein gesperrter
Suchdienst als gesperrt gemeldet wird, nicht als leer.
"""

import httpx
import pytest

from app import anreicherung
from tests.conftest import klient_fuer

ANFRAGEN: list[dict[str, str]] = []

START = """<html><head><title>Brinkmann Baustoffe</title></head><body>
<nav><a href="/impressum">Impressum</a> <a href="/team">Team</a></nav>
<p>Baustoffhandel für Tecklenburg, Lengerich und Ibbenbüren. Seit 1962 im Tecklenburger Land.</p>
</body></html>"""
IMPRESSUM = """<html><head><title>Impressum – Brinkmann Baustoffe</title></head><body>
<h1>Impressum</h1><p>Brinkmann Baustoffe GmbH<br>Industriestraße 4<br>49545 Tecklenburg</p>
<p>Telefon: +49 5482 1234-0 · info@baustoffe-brinkmann.de</p>
<p>Geschäftsführer: Sebastian Brinkmann</p></body></html>"""
TEAM = """<html><head><title>Team – Brinkmann Baustoffe</title></head><body>
<h2>Sebastian Brinkmann</h2><p>Geschäftsführer · s.brinkmann@baustoffe-brinkmann.de · +49 5482 1234-10</p>
<h2>Petra Lüttmann</h2><p>Verkauf Innendienst</p></body></html>"""

TREFFER_BAUSTOFF = [
    {"url": "https://www.gelbeseiten.de/branchen/baustoffhandel/tecklenburg",
     "title": "Baustoffhandel Tecklenburg – Gelbe Seiten", "content": "Brinkmann Baustoffe GmbH, Westerhoff Holz & Baustoffe …"},
    {"url": "https://www.baustoffe-brinkmann.de/", "title": "Brinkmann Baustoffe GmbH – Tecklenburg",
     "content": "Baustoffhandel im Tecklenburger Land seit 1962."},
    {"url": "https://holz-westerhoff.de/sortiment", "title": "Westerhoff Holz & Baustoffe – Lengerich",
     "content": "Holz und Baustoffe für Handwerk und Bauherren."},
    {"url": "https://www.linkedin.com/company/brinkmann-baustoffe", "title": "Brinkmann Baustoffe | LinkedIn",
     "content": "Baustoffe · 11–50 Beschäftigte · Tecklenburg"},
]
TREFFER_PERSON = [
    {"url": "https://de.linkedin.com/in/sebastian-brinkmann-tecklenburg",
     "title": "Sebastian Brinkmann – Geschäftsführer – Brinkmann Baustoffe GmbH | LinkedIn",
     "content": "Sebastian Brinkmann. Geschäftsführer bei Brinkmann Baustoffe GmbH. Tecklenburg."},
]


def _welt(request: httpx.Request) -> httpx.Response:
    url = str(request.url)
    if url.startswith("https://such.local/search"):
        ANFRAGEN.append(dict(request.url.params))
        q = request.url.params.get("q", "")
        # Anfragen mit Anführungszeichen stammen aus Schritt 2 und 3 — die
        # Beschreibung aus Schritt 1 geht ohne hinaus.
        if "site:linkedin.com/company" in q:
            return httpx.Response(200, json={"results": TREFFER_BAUSTOFF[3:]})
        if q.startswith('"'):
            return httpx.Response(200, json={"results": TREFFER_PERSON})
        if "Baustoff" in q:
            return httpx.Response(200, json={"results": TREFFER_BAUSTOFF})
        return httpx.Response(200, json={"results": []})
    if url.startswith("https://gesperrt.local/search"):
        return httpx.Response(200, json={"results": [], "unresponsive_engines": [
            ["brave", "Suspended: too many requests"], ["duckduckgo", "CAPTCHA"]]})
    seiten = {
        "https://www.baustoffe-brinkmann.de": START,
        "https://www.baustoffe-brinkmann.de/impressum": IMPRESSUM,
        "https://www.baustoffe-brinkmann.de/team": TEAM,
    }
    seite = seiten.get(url.rstrip("/"))
    if seite is None:
        return httpx.Response(404, text="nicht da")
    return httpx.Response(200, text=seite, headers={"content-type": "text/html; charset=utf-8"})


KANDIDATEN = (
    '{"kandidaten": ['
    '{"name": "Brinkmann Baustoffe GmbH", "website": "https://www.baustoffe-brinkmann.de", "ort": "Tecklenburg", '
    '"grund": "Baustoffhandel im Tecklenburger Land", "quelle": 2},'
    '{"name": "Westerhoff Holz & Baustoffe", "website": "https://holz-westerhoff.de", "ort": "Lengerich", "grund": "Baustoffe, Lengerich", "quelle": 3},'
    '{"name": "Gelbe Seiten", "website": "https://www.gelbeseiten.de", "ort": null, "grund": "Verzeichnis", "quelle": 1},'
    '{"name": "Ausgedacht Bau GmbH", "website": "https://ausgedacht-bau.de", "ort": "Tecklenburg", "grund": "klingt passend", "quelle": 2}'
    '], "person": {"vorname": "Sebastian", "rolle": "Geschäftsführer"}}'
)
FIRMA = (
    '{"felder": {"street": {"wert": "Industriestraße 4", "quelle": 2}, "postal_code": {"wert": "49545", "quelle": 2},'
    '"city": {"wert": "Tecklenburg", "quelle": 2}, "country": {"wert": "DE", "quelle": 2},'
    '"phone": {"wert": "+49 5482 1234-0", "quelle": 2}, "industry": {"wert": "Baustoffhandel", "quelle": 1}}}'
)
PERSON = (
    '{"felder": {"first_name": {"wert": "Sebastian", "quelle": 1}, "last_name": {"wert": "Brinkmann", "quelle": 1},'
    '"job_title": {"wert": "Geschäftsführer", "quelle": 1}, "email": {"wert": "s.brinkmann@baustoffe-brinkmann.de", "quelle": 1},'
    '"mobile": {"wert": "+49 170 9999999", "quelle": 1}}}'
)
FREMDE_PERSON = (
    '{"felder": {"first_name": {"wert": "Sebastian", "quelle": 1}, "last_name": {"wert": "Meier", "quelle": 1}},'
    ' "andere": [{"first_name": "Sebastian", "last_name": "Brinkmann", "job_title": "Geschäftsführer", "quelle": 2},'
    ' {"first_name": "Petra", "last_name": "Lüttmann", "job_title": "Verkauf Innendienst", "quelle": 3},'
    ' {"first_name": "Karl", "last_name": "Erfunden", "job_title": "Inhaber", "quelle": 2}]}'
)


PERSONEN = (
    '{"andere": [{"first_name": "Sebastian", "last_name": "Brinkmann", "job_title": "Geschäftsführer",'
    ' "email": "s.brinkmann@baustoffe-brinkmann.de", "phone": "+49 5482 1234-10", "quelle": 3},'
    ' {"first_name": "Petra", "last_name": "Lüttmann", "job_title": "Verkauf Innendienst", "email": "p.luettmann@baustoffe-brinkmann.de", "quelle": 3},'
    ' {"first_name": "Karl", "last_name": "Erfunden", "job_title": "Inhaber", "quelle": 2}]}'
)


@pytest.fixture
def welt(monkeypatch):
    ANFRAGEN.clear()
    monkeypatch.setattr(
        anreicherung, "http_client",
        lambda: httpx.AsyncClient(transport=httpx.MockTransport(_welt), follow_redirects=True),
    )
    skript = {"person": PERSON}

    async def modell(cfg, system, user, **kwargs):
        if user.startswith("Beschreibung:"):
            return KANDIDATEN
        if "Alle Personen" in user:
            return PERSONEN
        if "Gesucht:" in user.split("\n", 2)[1]:
            return skript["person"]
        return FIRMA

    monkeypatch.setattr(anreicherung, "chat", modell)
    return skript


async def _eingerichtet(k, suche="https://such.local"):
    await k.put("/api/settings", json={
        "llm_base_url": "http://modell.local/v1", "llm_model": "t",
        "suche_endpoint_url": suche, "anreicherung_automatisch": False,
    })


async def test_kandidaten_kommen_nur_aus_den_treffern(datenbank, welt):
    async with klient_fuer("finden-kandidaten") as k:
        await _eingerichtet(k)
        r = await k.post("/api/finden/kandidaten", json={"beschreibung": "Baustoffhandel Tecklenburger Land, Geschäftsführer heißt vermutlich Sebastian"})
        assert r.status_code == 200, r.text
        d = r.json()
        namen = [x["name"] for x in d["kandidaten"]]
        # Zwei echte Firmen — kein Verzeichnis, keine erfundene Website.
        assert namen == ["Brinkmann Baustoffe GmbH", "Westerhoff Holz & Baustoffe"]
        assert d["kandidaten"][0]["website"] == "https://www.baustoffe-brinkmann.de"
        assert d["kandidaten"][0]["quelle"].startswith("https://www.baustoffe-brinkmann.de")
        assert d["person"] == {"vorname": "Sebastian", "rolle": "Geschäftsführer"}
        # Was den Suchdienst verlassen hat, steht im Nachweis — und mit Region.
        assert [q["anfrage"] for q in d["quellen"] if q["art"] == "suche"]
        assert all(a.get("language") == "de-DE" for a in ANFRAGEN)


async def test_ohne_suchdienst_keine_kandidaten(datenbank, welt):
    async with klient_fuer("finden-ohne-suche") as k:
        await k.put("/api/settings", json={"llm_base_url": "http://modell.local/v1", "llm_model": "t"})
        r = await k.post("/api/finden/kandidaten", json={"beschreibung": "Baustoffhandel Tecklenburg"})
        assert r.status_code == 409
        assert "Suchdienst" in r.json()["detail"]


async def test_gesperrte_instanz_nennt_die_anbieter_und_einen_ausweg(datenbank, welt):
    """Bis 0.9.3 hieß es „gesperrt … gibt sich nach einigen Stunden".

    Es gibt sich nicht: Eine selbst betriebene Instanz wird dauerhaft
    abgewiesen, und Marc wartete darauf, dass es von allein wiederkommt.
    Der Satz nennt jetzt die Anbieter **und** den Weg heraus.
    """
    async with klient_fuer("finden-gesperrt") as k:
        await _eingerichtet(k, suche="https://gesperrt.local")
        r = await k.post("/api/finden/kandidaten", json={"beschreibung": "Baustoffhandel Tecklenburg"})
        assert r.status_code == 503
        satz = r.json()["detail"]
        assert "brave" in satz and "duckduckgo" in satz
        assert "Tavily" in satz
        assert "Stunden" not in satz


async def test_region_leer_geht_ohne_sprache(datenbank, welt):
    async with klient_fuer("finden-region") as k:
        await _eingerichtet(k)
        await k.put("/api/settings", json={"suche_region": ""})
        assert (await k.get("/api/settings")).json()["suche_region"] == ""
        await k.post("/api/finden/kandidaten", json={"beschreibung": "Baustoffhandel Tecklenburg"})
        assert all("language" not in a for a in ANFRAGEN)
        assert (await k.put("/api/settings", json={"suche_region": "deutschland"})).status_code == 422


async def test_firma_wird_aus_impressum_gefuellt(datenbank, welt):
    async with klient_fuer("finden-firma") as k:
        await _eingerichtet(k)
        r = await k.post("/api/finden/firma", json={"name": "Brinkmann Baustoffe GmbH", "website": "https://www.baustoffe-brinkmann.de"})
        assert r.status_code == 200, r.text
        d = r.json()
        f = d["felder"]
        assert f["name"] == "Brinkmann Baustoffe GmbH"
        assert f["website"] == "https://www.baustoffe-brinkmann.de"
        assert f["domain"] == "baustoffe-brinkmann.de"
        assert f["street"] == "Industriestraße 4" and f["postal_code"] == "49545" and f["city"] == "Tecklenburg"
        assert f["phone"] == "+49 5482 1234-0"
        assert d["belege"]["phone"] == {"quelle": "https://www.baustoffe-brinkmann.de/impressum", "belegt": True}
        assert f["linkedin_url"] == "https://www.linkedin.com/company/brinkmann-baustoffe"
        assert d["dublette"] is None

        # Gibt es sie schon, sagt der Fund das — angelegt wird trotzdem nichts von selbst.
        await k.post("/api/companies", json={"name": "Brinkmann Baustoffe GmbH", "domain": "baustoffe-brinkmann.de"})
        d2 = (await k.post("/api/finden/firma", json={"name": "Brinkmann Baustoffe GmbH", "website": "https://www.baustoffe-brinkmann.de"})).json()
        assert d2["dublette"]["grund"] == "gleiche Domain"
        assert (await k.get("/api/companies?limit=50")).json().__len__() == 1


async def test_person_wird_gefunden_und_belegt(datenbank, welt):
    async with klient_fuer("finden-person") as k:
        await _eingerichtet(k)
        r = await k.post("/api/finden/kontakt", json={
            "firma": {"name": "Brinkmann Baustoffe GmbH", "website": "https://www.baustoffe-brinkmann.de"},
            "person": {"vorname": "Sebastian", "rolle": "Geschäftsführer"},
        })
        assert r.status_code == 200, r.text
        d = r.json()
        f = d["felder"]
        assert f["first_name"] == "Sebastian" and f["last_name"] == "Brinkmann"
        assert f["job_title"] == "Geschäftsführer"
        assert f["email"] == "s.brinkmann@baustoffe-brinkmann.de"
        # Die erfundene Mobilnummer steht in keiner Quelle — weg.
        assert "mobile" not in f
        assert f["firma_name"] == "Brinkmann Baustoffe GmbH" and f["firma_domain"] == "baustoffe-brinkmann.de"
        assert d["belege"]["last_name"]["belegt"] is True


async def test_person_ohne_beleg_ist_keine_person(datenbank, welt):
    welt["person"] = FREMDE_PERSON
    async with klient_fuer("finden-fremd") as k:
        await _eingerichtet(k)
        d = (await k.post("/api/finden/kontakt", json={
            "firma": {"name": "Brinkmann Baustoffe GmbH", "website": "https://www.baustoffe-brinkmann.de"},
            "person": {"vorname": "Sebastian"},
        })).json()
        assert "last_name" not in d["felder"] and "first_name" not in d["felder"]
        assert d["felder"]["firma_name"] == "Brinkmann Baustoffe GmbH"
        assert any("Keine Quelle nennt" in h for h in d["hinweise"])
        # Die anderen Genannten kommen als Wahl — nur mit belegtem Nachnamen.
        assert [(a["first_name"], a["last_name"], a["job_title"]) for a in d["alternativen"]] == [
            ("Sebastian", "Brinkmann", "Geschäftsführer"), ("Petra", "Lüttmann", "Verkauf Innendienst"),
        ]
        assert d["alternativen"][0]["quelle"].startswith("https://www.baustoffe-brinkmann.de")


async def test_ohne_modell_409(datenbank, welt):
    async with klient_fuer("finden-ohne-modell") as k:
        await k.put("/api/settings", json={"llm_base_url": None, "suche_endpoint_url": "https://such.local"})
        r = await k.post("/api/finden/kandidaten", json={"beschreibung": "Baustoffhandel Tecklenburg"})
        assert r.status_code == 409


async def test_personen_bei_einer_firma(datenbank, welt):
    """Alle Genannten als Wahl — mit belegten Kontaktdaten, ohne Erfundenes."""
    async with klient_fuer("finden-personen") as k:
        await _eingerichtet(k)
        r = await k.post("/api/finden/personen", json={"firma": {"name": "Brinkmann Baustoffe GmbH", "website": "https://www.baustoffe-brinkmann.de"}, "wunsch": "Geschäftsführung"})
        assert r.status_code == 200, r.text
        d = r.json()
        p = d["personen"]
        assert [(x["first_name"], x["last_name"]) for x in p] == [("Sebastian", "Brinkmann"), ("Petra", "Lüttmann")]
        assert p[0]["email"] == "s.brinkmann@baustoffe-brinkmann.de" and p[0]["phone"] == "+49 5482 1234-10"
        # Die E-Mail von Petra steht in keiner Quelle — weg.
        assert "email" not in p[1]
        assert p[0]["quelle"].startswith("https://www.baustoffe-brinkmann.de")
        assert any(q.get("anfrage", "").endswith("Geschäftsführung") for q in d["quellen"] if q["art"] == "suche")
