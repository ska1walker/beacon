"""Fragen an den eigenen Bestand."""

from app.routers.fragen import suchbegriffe
from tests.conftest import klient_fuer

# ---- Suchbegriffe -------------------------------------------------------

def test_fuellwoerter_fliegen_raus():
    """Ohne diese Liste sucht „Welche Firma …" nach „welche" und findet alles."""
    assert suchbegriffe("Welche Firma hat das größte Geschäft?") == ["firma", "größte", "geschäft"]


def test_kurze_woerter_fliegen_raus():
    assert "am" not in suchbegriffe("Wer ist am Zug?")


def test_satzzeichen_stoeren_nicht():
    assert suchbegriffe("Nordlicht-Steuerberatung: Stand?") == ["nordlicht", "steuerberatung", "stand"]


def test_frage_ohne_inhalt_ergibt_nichts():
    assert suchbegriffe("Was ist mit uns?") == []


# ---- Über die API -------------------------------------------------------

async def _bestand(klient):
    firma = (
        await klient.post(
            "/api/companies",
            json={
                "name": "Nordlicht Steuerberatung",
                "industry": "Steuerberatung",
                "city": "Lüneburg",
                "description": "Kammerauflage zum Verbleib der Mandantendaten.",
            },
        )
    ).json()
    deal = (
        await klient.post(
            "/api/deals",
            json={
                "name": "Analyst — Jahresabschluss",
                "company_id": firma["id"],
                "amount_cents": 1450000,
                "next_step": "Datenweg beschreiben",
            },
        )
    ).json()
    await klient.post(
        "/api/activities",
        json={
            "kind": "call",
            "subject": "Telefonat Vosskamp",
            "body": "Die Kammer verlangt, dass die Mandantendaten im Haus bleiben.",
            "deal_id": deal["id"],
        },
    )
    return firma, deal


async def test_ohne_fund_wird_kein_modell_gefragt(datenbank, monkeypatch):
    """Eine Antwort ohne Fundstelle wäre aus dem Gedächtnis geraten."""
    from app.routers import fragen as modul

    async def darf_nicht(*args, **kwargs):
        raise AssertionError("es wurde ein Modell gefragt, obwohl nichts gefunden wurde")

    monkeypatch.setattr(modul, "chat", darf_nicht)

    async with klient_fuer("frage-leer") as klient:
        await klient.put("/api/settings", json={"llm_base_url": "http://test/v1"})
        antwort = (
            await klient.post("/api/fragen", json={"frage": "Was ist mit Zeppelinbau?"})
        ).json()

    assert antwort["antwort"] == ""
    assert antwort["fundstellen"] == []
    assert "steht nichts im Bestand" in antwort["hinweis"]


async def test_findet_ueber_alle_arten(datenbank, monkeypatch):
    from app.routers import fragen as modul

    gesehen = {}

    async def antwort(cfg, system, user, **kwargs):
        gesehen["prompt"] = user
        return "Die Kammerauflage ist der Auslöser [1]."

    monkeypatch.setattr(modul, "chat", antwort)

    async with klient_fuer("frage-voll") as klient:
        await klient.put("/api/settings", json={"llm_base_url": "http://test/v1"})
        await _bestand(klient)
        ergebnis = (
            await klient.post("/api/fragen", json={"frage": "Was sagt Nordlicht zur Kammerauflage?"})
        ).json()

    arten = {f["art"] for f in ergebnis["fundstellen"]}
    assert "Firma" in arten
    assert "Verlauf" in arten
    assert ergebnis["antwort"].startswith("Die Kammerauflage")

    # Die Fundstellen müssen wirklich im Prompt gestanden haben — sonst
    # hat das Modell aus dem Nichts geantwortet.
    assert "Kammerauflage" in gesehen["prompt"]
    assert "ausschließlich aus den Fundstellen" in gesehen["prompt"]


async def test_ohne_modell_bleiben_die_fundstellen(datenbank):
    """Auch ohne Sprachmodell ist die Suche etwas wert."""
    async with klient_fuer("frage-ohne-modell") as klient:
        await _bestand(klient)
        ergebnis = (
            await klient.post("/api/fragen", json={"frage": "Nordlicht Kammerauflage"})
        ).json()

    assert ergebnis["antwort"] == ""
    assert len(ergebnis["fundstellen"]) > 0
    assert "Kein Sprachmodell" in ergebnis["hinweis"]


async def test_fremder_bestand_bleibt_unsichtbar(datenbank, monkeypatch):
    from app.routers import fragen as modul

    async def antwort(cfg, system, user, **kwargs):
        return "irgendetwas"

    monkeypatch.setattr(modul, "chat", antwort)

    async with klient_fuer("frage-a") as a, klient_fuer("frage-b") as b:
        await _bestand(a)
        await b.put("/api/settings", json={"llm_base_url": "http://test/v1"})
        ergebnis = (await b.post("/api/fragen", json={"frage": "Nordlicht Kammerauflage"})).json()

    assert ergebnis["fundstellen"] == []


def test_komposita_werden_mit_dem_wortanfang_gesucht():
    """Deutsch setzt Wörter zusammen — die Substring-Suche tut das nicht.

    Eine Notiz mit „die Kammer verlangt" ist genau die gesuchte Stelle,
    wird von `%kammerauflage%` aber nicht gefunden.
    """
    from app.routers.fragen import suchmuster

    muster = suchmuster(["kammerauflage"])
    assert "%kammerauflage%" in muster
    assert "%kammer%" in muster

    # Kurze Wörter bleiben, wie sie sind — sonst fände „Preis" alles mit „prei".
    assert suchmuster(["preis"]) == ["%preis%"]
