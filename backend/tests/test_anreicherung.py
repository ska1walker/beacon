"""Anreicherung aus öffentlichen Quellen.

Die Prüfungen laufen gegen nachgebaute Webseiten und einen nachgebauten
Suchdienst — echte Abrufe hätten in einem Test nichts verloren. Das
Modell antwortet aus einem Skript. Was geprüft wird, ist der Teil, der
uns gehört: Belegpflicht, Nie-Überschreiben, Ablage, Übernahme.
"""

import httpx
import orjson
import pytest

from app import anreicherung
from app.anreicherung import Quelle, ist_belegt, text_aus_html
from tests.conftest import klient_fuer

# ---- Bausteine ----------------------------------------------------------


def test_html_wird_lesbarer_text():
    titel, text = text_aus_html(
        "<html><head><title>Müller &amp; Co</title><style>p{}</style></head>"
        "<body><script>x()</script><h1>Impressum</h1><p>Musterstraße 1<br>20095 Hamburg</p></body></html>"
    )
    assert titel == "Müller & Co"
    assert "Impressum" in text
    assert "Musterstraße 1\n20095 Hamburg" in text
    assert "x()" not in text


def test_beleg_prueft_woertlich():
    q = Quelle(url="https://x.de/impressum", titel="", text="Tel. +49 (0)40 123 45-67 · post@x.de", bytes=1)
    assert ist_belegt("phone", "+49 40 1234567", q)
    assert not ist_belegt("phone", "+49 40 9999999", q)
    assert ist_belegt("email", "Post@x.de", q)
    assert not ist_belegt("email", "chef@x.de", q)
    assert ist_belegt("website", "https://www.x.de", q)
    li = Quelle(url="https://de.linkedin.com/in/anna-b", titel="Anna B – CTO", text="", bytes=1, art="suche")
    assert ist_belegt("linkedin_url", "https://linkedin.com/in/anna-b", li)


# ---- Nachgebaute Welt ---------------------------------------------------

STARTSEITE = """<html><head><title>Nordlicht Steuerberatung</title></head><body>
<nav><a href="/impressum">Impressum</a> <a href="/team">Team</a></nav>
<p>Wir beraten den Mittelstand in Hamburg seit 1998. Steuerberatung, Jahresabschluss, Lohn.</p>
<a href="https://www.linkedin.com/company/nordlicht-steuer">LinkedIn</a>
</body></html>"""

IMPRESSUM = """<html><head><title>Impressum – Nordlicht</title></head><body>
<h1>Impressum</h1>
<p>Nordlicht Steuerberatung GmbH<br>Alsterufer 12<br>20354 Hamburg</p>
<p>Telefon: +49 40 555 0199<br>E-Mail: kanzlei@nordlicht-steuer.de</p>
<p>Geschäftsführung: Anna Berg</p>
</body></html>"""

TEAM = """<html><head><title>Team – Nordlicht</title></head><body>
<h2>Anna Berg</h2><p>Geschäftsführerin, Steuerberaterin · a.berg@nordlicht-steuer.de · +49 40 555 0190</p>
<h2>Jonas Krüger</h2><p>Steuerfachangestellter</p>
</body></html>"""


def _welt(request: httpx.Request) -> httpx.Response:
    url = str(request.url)
    if url.startswith("https://such.local/search"):
        q = request.url.params.get("q", "")
        if "linkedin.com/in" in q and "Berg" in q:
            return httpx.Response(200, json={"results": [
                {"url": "https://de.linkedin.com/in/anna-berg-nordlicht",
                 "title": "Anna Berg – Geschäftsführerin – Nordlicht Steuerberatung | LinkedIn",
                 "content": "Anna Berg. Geschäftsführerin bei Nordlicht Steuerberatung GmbH. Hamburg."},
                {"url": "https://de.linkedin.com/in/anna-berg-other",
                 "title": "Anna Berg – Bäckerei Berg | LinkedIn", "content": "Inhaberin Bäckerei"},
            ]})
        if "linkedin.com/company" in q:
            return httpx.Response(200, json={"results": [
                {"url": "https://www.linkedin.com/company/nordlicht-steuer",
                 "title": "Nordlicht Steuerberatung | LinkedIn",
                 "content": "Steuerberatung · 11–50 Beschäftigte · Hamburg"},
            ]})
        return httpx.Response(200, json={"results": []})
    seiten = {
        "https://nordlicht-steuer.de": STARTSEITE,
        "https://nordlicht-steuer.de/impressum": IMPRESSUM,
        "https://nordlicht-steuer.de/team": TEAM,
    }
    seite = seiten.get(url.rstrip("/"))
    if seite is None:
        return httpx.Response(404, text="nicht da")
    return httpx.Response(200, text=seite, headers={"content-type": "text/html; charset=utf-8"})


FIRMENANTWORT = (
    '{"felder": {'
    '"industry": {"wert": "Steuerberatung", "quelle": 1},'
    '"street": {"wert": "Alsterufer 12", "quelle": 2},'
    '"postal_code": {"wert": "20354", "quelle": 2},'
    '"city": {"wert": "Hamburg", "quelle": 2},'
    '"country": {"wert": "DE", "quelle": 2},'
    '"phone": {"wert": "+49 40 555 0199", "quelle": 2},'
    '"employee_count": {"wert": "999", "quelle": 1},'
    '"description": {"wert": "Steuerberatung für den Mittelstand in Hamburg seit 1998.", "quelle": 1}'
    "}}"
)

KONTAKTANTWORT = (
    '{"felder": {'
    '"job_title": {"wert": "Geschäftsführerin", "quelle": 1},'
    '"email": {"wert": "a.berg@nordlicht-steuer.de", "quelle": 1},'
    '"phone": {"wert": "+49 40 555 0190", "quelle": 1},'
    '"mobile": {"wert": "+49 170 0000000", "quelle": 1}'
    "}}"
)


@pytest.fixture
def welt(monkeypatch):
    monkeypatch.setattr(
        anreicherung, "http_client",
        lambda: httpx.AsyncClient(transport=httpx.MockTransport(_welt), follow_redirects=True),
    )

    async def modell(cfg, system, user, **kwargs):
        return KONTAKTANTWORT if user.startswith("Person:") else FIRMENANTWORT

    monkeypatch.setattr(anreicherung, "chat", modell)


# ---- Firma --------------------------------------------------------------


async def test_firma_wird_aus_website_gefuellt(datenbank, welt):
    async with klient_fuer("anreich-firma") as k:
        await k.put("/api/settings", json={"llm_base_url": "http://modell.local/v1", "llm_model": "t",
                                            "anreicherung_automatisch": False})
        firma = (await k.post("/api/companies", json={"name": "Nordlicht Steuerberatung",
                                                       "domain": "nordlicht-steuer.de"})).json()
        lauf = (await k.post(f"/api/companies/{firma['id']}/anreichern")).json()

        # Leere Felder mit Beleg sind geschrieben …
        assert lauf["status"] == "vorschlag"
        assert lauf["uebernommen"]["street"] == "Alsterufer 12"
        assert lauf["uebernommen"]["postal_code"] == "20354"
        assert lauf["uebernommen"]["phone"] == "+49 40 555 0199"
        assert lauf["uebernommen"]["industry"] == "Steuerberatung"
        # … die LinkedIn-Seite kam aus dem Link auf der Startseite, ohne Modell …
        assert lauf["uebernommen"]["linkedin_url"] == "https://www.linkedin.com/company/nordlicht-steuer"
        # … die Beschreibung bleibt ein Vorschlag …
        assert lauf["vorschlag"]["description"]["lage"] == "neu"
        assert "uebernommen" not in lauf["vorschlag"]
        # … und die erfundene Beschäftigtenzahl steht nirgends: 999 kommt in keiner Quelle vor.
        assert "employee_count" not in lauf["uebernommen"]
        assert "employee_count" not in lauf["vorschlag"]
        # Der Ort stand schon? Nein — war leer, also übernommen.
        assert lauf["uebernommen"]["city"] == "Hamburg"

        # Am Datensatz angekommen
        f = (await k.get(f"/api/companies/{firma['id']}")).json()
        assert f["street"] == "Alsterufer 12" and f["phone"] == "+49 40 555 0199"
        assert f["description"] is None
        assert f["linkedin_url"].endswith("/company/nordlicht-steuer")

        # Jede gelesene Quelle steht mit Umfang im Lauf — der gemessene Nachweis.
        urls = {q["url"] for q in lauf["quellen"]}
        assert "https://nordlicht-steuer.de/impressum" in urls
        assert all(q["bytes"] > 0 for q in lauf["quellen"])

        # Protokoll und Verlauf
        verlauf = (await k.get(f"/api/activities?company_id={firma['id']}")).json()
        assert any(a["kind"] == "ai" and "Quellen" in (a["subject"] or "") for a in verlauf)


async def test_vorhandenes_wird_nie_ueberschrieben(datenbank, welt):
    async with klient_fuer("anreich-schutz") as k:
        await k.put("/api/settings", json={"llm_base_url": "http://modell.local/v1",
                                            "anreicherung_automatisch": False})
        firma = (await k.post("/api/companies", json={
            "name": "Nordlicht Steuerberatung", "website": "https://nordlicht-steuer.de",
            "phone": "+49 40 111 1111", "city": "Hamburg",
        })).json()
        lauf = (await k.post(f"/api/companies/{firma['id']}/anreichern")).json()
        assert "phone" not in lauf["uebernommen"]
        assert lauf["vorschlag"]["phone"]["lage"] == "abweichend"
        assert lauf["vorschlag"]["phone"]["wert"] == "+49 40 555 0199"
        # Gleicher Wert wie schon gespeichert taucht gar nicht auf.
        assert "city" not in lauf["vorschlag"] and "city" not in lauf["uebernommen"]
        f = (await k.get(f"/api/companies/{firma['id']}")).json()
        assert f["phone"] == "+49 40 111 1111"

        # Der Mensch nimmt den abweichenden Wert — gezielt nur den.
        nach = (await k.post(f"/api/anreicherungen/{lauf['id']}/uebernehmen", json={"felder": ["phone"]})).json()
        assert nach["status"] == "uebernommen"
        assert nach["uebernommen"]["phone"] == "+49 40 555 0199"
        f = (await k.get(f"/api/companies/{firma['id']}")).json()
        assert f["phone"] == "+49 40 555 0199"
        assert f["description"] is None  # nicht gewählt, nicht geschrieben

        # Ein zweites Übernehmen gibt es nicht.
        assert (await k.post(f"/api/anreicherungen/{lauf['id']}/uebernehmen", json={})).status_code == 409


async def test_nur_vorschlag_wenn_so_eingestellt(datenbank, welt):
    async with klient_fuer("anreich-vorschlag") as k:
        await k.put("/api/settings", json={"llm_base_url": "http://modell.local/v1",
                                            "anreicherung_automatisch": False,
                                            "anreicherung_uebernahme": "vorschlag"})
        firma = (await k.post("/api/companies", json={"name": "Nordlicht", "domain": "nordlicht-steuer.de"})).json()
        lauf = (await k.post(f"/api/companies/{firma['id']}/anreichern")).json()
        assert lauf["uebernommen"] == {}
        assert lauf["vorschlag"]["street"]["wert"] == "Alsterufer 12"
        f = (await k.get(f"/api/companies/{firma['id']}")).json()
        assert f["street"] is None

        weg = (await k.post(f"/api/anreicherungen/{lauf['id']}/verwerfen")).json()
        assert weg["status"] == "verworfen" and weg["vorschlag"] == {}
        # Verworfen bleibt in der Liste — die Spur bleibt.
        liste = (await k.get(f"/api/anreicherungen?entity=companies&entity_id={firma['id']}")).json()
        assert liste[0]["status"] == "verworfen"


async def test_ohne_modell_keine_anreicherung(datenbank, welt):
    async with klient_fuer("anreich-kein-modell") as k:
        firma = (await k.post("/api/companies", json={"name": "X", "domain": "nordlicht-steuer.de"})).json()
        antwort = await k.post(f"/api/companies/{firma['id']}/anreichern")
        assert antwort.status_code == 409
        status = (await k.get("/api/anreicherung/status")).json()
        assert status["llm_ready"] is False and "Sprachmodell" in status["hint"]


async def test_ohne_website_und_ohne_suche_bleibt_es_leer(datenbank, welt):
    async with klient_fuer("anreich-leer") as k:
        await k.put("/api/settings", json={"llm_base_url": "http://modell.local/v1",
                                            "anreicherung_automatisch": False})
        firma = (await k.post("/api/companies", json={"name": "Unbekannte GmbH"})).json()
        lauf = (await k.post(f"/api/companies/{firma['id']}/anreichern")).json()
        assert lauf["status"] == "leer"
        assert "Suchdienst" in lauf["fehler"]
        assert lauf["quellen"] == []


# ---- Kontakt ------------------------------------------------------------


async def test_kontakt_aus_team_seite_und_linkedin(datenbank, welt):
    async with klient_fuer("anreich-kontakt") as k:
        await k.put("/api/settings", json={"llm_base_url": "http://modell.local/v1",
                                            "suche_endpoint_url": "https://such.local",
                                            "anreicherung_automatisch": False})
        status = (await k.get("/api/anreicherung/status")).json()
        assert status["suche_eingerichtet"] is True and status["suche_art"] == "searxng"

        firma = (await k.post("/api/companies", json={"name": "Nordlicht Steuerberatung",
                                                       "website": "https://nordlicht-steuer.de"})).json()
        kontakt = (await k.post("/api/contacts", json={"first_name": "Anna", "last_name": "Berg",
                                                        "company_id": firma["id"]})).json()
        lauf = (await k.post(f"/api/contacts/{kontakt['id']}/anreichern")).json()

        # Die Profiladresse kommt aus der Trefferliste — der erste Treffer, der die Person nennt.
        assert lauf["uebernommen"]["linkedin_url"] == "https://de.linkedin.com/in/anna-berg-nordlicht"
        assert lauf["uebernommen"]["job_title"] == "Geschäftsführerin"
        assert lauf["uebernommen"]["email"] == "a.berg@nordlicht-steuer.de"
        assert lauf["uebernommen"]["phone"] == "+49 40 555 0190"
        # Die Mobilnummer stand in keiner Quelle — weg damit.
        assert "mobile" not in lauf["uebernommen"] and "mobile" not in lauf["vorschlag"]
        assert lauf["status"] == "uebernommen"

        # Die Suchanfrage steht im Lauf: Das ist, was den Suchdienst erreicht hat.
        anfragen = [q["anfrage"] for q in lauf["quellen"] if q.get("art") == "suche"]
        assert any("Anna Berg" in a and "linkedin.com/in" in a for a in anfragen)
        # Die Team-Seite ohne den Namen? Der Kollege Krüger ist nicht die Quelle.
        assert all("Berg" in q["titel"] or "nordlicht" in q["url"] for q in lauf["quellen"])

        kk = (await k.get(f"/api/contacts/{kontakt['id']}")).json()
        assert kk["job_title"] == "Geschäftsführerin" and kk["linkedin_url"].endswith("anna-berg-nordlicht")


async def test_kontakt_ohne_firma_und_suche(datenbank, welt):
    async with klient_fuer("anreich-kontakt-leer") as k:
        await k.put("/api/settings", json={"llm_base_url": "http://modell.local/v1",
                                            "anreicherung_automatisch": False})
        kontakt = (await k.post("/api/contacts", json={"first_name": "Anna", "last_name": "Berg"})).json()
        lauf = (await k.post(f"/api/contacts/{kontakt['id']}/anreichern")).json()
        assert lauf["status"] == "leer"
        assert "Suchdienst" in lauf["fehler"]


# ---- Von selbst ---------------------------------------------------------


async def test_anlegen_stoesst_lauf_im_hintergrund_an(datenbank, welt):
    async with klient_fuer("anreich-auto") as k:
        await k.put("/api/settings", json={"llm_base_url": "http://modell.local/v1"})
        firma = (await k.post("/api/companies", json={"name": "Nordlicht Steuerberatung",
                                                       "domain": "nordlicht-steuer.de"})).json()
        await anreicherung.hintergrund_abwarten()
        laeufe = (await k.get(f"/api/anreicherungen?entity=companies&entity_id={firma['id']}")).json()
        assert len(laeufe) == 1
        assert laeufe[0]["uebernommen"]["street"] == "Alsterufer 12"
        f = (await k.get(f"/api/companies/{firma['id']}")).json()
        assert f["postal_code"] == "20354"


async def test_abgeschaltet_laeuft_nichts_von_selbst(datenbank, welt):
    async with klient_fuer("anreich-aus") as k:
        await k.put("/api/settings", json={"llm_base_url": "http://modell.local/v1",
                                            "anreicherung_automatisch": False})
        firma = (await k.post("/api/companies", json={"name": "Nordlicht", "domain": "nordlicht-steuer.de"})).json()
        await anreicherung.hintergrund_abwarten()
        assert (await k.get(f"/api/anreicherungen?entity=companies&entity_id={firma['id']}")).json() == []


async def test_laeufe_bleiben_in_der_organisation(datenbank, welt):
    async with klient_fuer("anreich-a") as a, klient_fuer("anreich-b") as b:
        await a.put("/api/settings", json={"llm_base_url": "http://modell.local/v1",
                                            "anreicherung_automatisch": False})
        firma = (await a.post("/api/companies", json={"name": "Nordlicht", "domain": "nordlicht-steuer.de"})).json()
        lauf = (await a.post(f"/api/companies/{firma['id']}/anreichern")).json()
        assert (await b.get(f"/api/anreicherungen?entity=companies&entity_id={firma['id']}")).json() == []
        assert (await b.post(f"/api/anreicherungen/{lauf['id']}/verwerfen")).status_code == 404


# ---------------------------------------------------------------------------
# Welcher Dienst am anderen Ende hängt
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "adresse,art",
    [
        ("https://api.search.brave.com/res/v1/web/search", "brave"),
        ("https://api.tavily.com/search", "tavily"),
        ("http://searxngv2.searxngv2server-shared.svc.cluster.local:8080", "searxng"),
        ("https://suche.example.olares.com/search", "searxng"),
    ],
)
def test_die_adresse_sagt_welcher_dienst_es_ist(adresse, art):
    """Es gibt kein Auswahlfeld — ein Feld mehr wäre ein Feld, das falsch steht."""
    assert anreicherung.Suchdienst(endpoint_url=adresse, api_key="x").art == art


async def test_tavily_wird_per_post_mit_bearer_gefragt():
    """Der einzige der drei, der POST spricht. Region geht als Ländername mit."""
    gesehen: dict[str, object] = {}

    def antworten(request: httpx.Request) -> httpx.Response:
        gesehen["methode"] = request.method
        gesehen["kopf"] = request.headers.get("authorization")
        gesehen["koerper"] = orjson.loads(request.content)
        return httpx.Response(200, json={"results": [
            {"url": "https://brinkmann-baustoffe.de/impressum",
             "title": "Impressum — Brinkmann Baustoffe",
             "content": "Brinkmann Baustoffe GmbH, Tecklenburg"},
        ]})

    dienst = anreicherung.Suchdienst(
        endpoint_url="https://api.tavily.com/search", api_key="tvly-test", region="DE"
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(antworten)) as klient:
        quellen = await anreicherung.suchen(klient, dienst, "Brinkmann Baustoffe Impressum")

    assert gesehen["methode"] == "POST"
    assert gesehen["kopf"] == "Bearer tvly-test"
    # Tavily nimmt kein Kürzel: „DE" würde stillschweigend ignoriert.
    assert gesehen["koerper"]["country"] == "germany"
    assert gesehen["koerper"]["language"] == "de"
    assert [q.url for q in quellen] == ["https://brinkmann-baustoffe.de/impressum"]
    assert "Tecklenburg" in quellen[0].text


async def test_ohne_region_nennt_tavily_kein_land():
    gesehen: dict[str, object] = {}

    def antworten(request: httpx.Request) -> httpx.Response:
        gesehen["koerper"] = orjson.loads(request.content)
        return httpx.Response(200, json={"results": []})

    dienst = anreicherung.Suchdienst(
        endpoint_url="https://api.tavily.com/search", api_key="tvly-test", region=""
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(antworten)) as klient:
        await anreicherung.suchen(klient, dienst, "irgendwas")

    assert "country" not in gesehen["koerper"]
    assert "language" not in gesehen["koerper"]
