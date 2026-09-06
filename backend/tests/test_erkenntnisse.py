"""Erkenntnisse — aus Notizen werden Aussagen, aus Aussagen Themen.

Das Modell antwortet aus dem Skript. Geprüft wird, was uns gehört: Nur
Aussagen mit Zitat aus der Notiz, jede Notiz genau einmal gelesen, Themen
nur mit zugeordneten Aussagen, und der Lauf mit Fortschritt und Ergebnis.
"""

import pytest

from app import erkenntnisse
from tests.conftest import klient_fuer

NOTIZ_A = "Gespräch mit Herrn Berg: Insilo gefällt, aber die Sprechererkennung verwechselt bei drei Leuten die Stimmen. Er wünscht sich die Zusammenfassung auch auf Englisch. Termin nächste Woche."
NOTIZ_B = "Frau Kolb sagt, die Sprechererkennung ordnet Sprecher falsch zu, sonst läuft Insilo gut. Preis für drei Nutzer sei zu hoch."
NOTIZ_C = "Nur Terminabsprache, Rückruf am Montag um zehn Uhr wegen der Unterlagen."

AUSSAGEN = {
    1: [
        {"art": "kritik", "produkt": "Insilo", "text": "Die Sprechererkennung verwechselt bei drei Personen die Stimmen.", "zitat": "die Sprechererkennung verwechselt bei drei Leuten die Stimmen"},
        {"art": "wunsch", "produkt": "Insilo", "text": "Die Zusammenfassung soll es auch auf Englisch geben.", "zitat": "Zusammenfassung auch auf Englisch"},
        {"art": "lob", "produkt": "Insilo", "text": "Erfunden ohne Zitat.", "zitat": "das steht nirgends"},
    ],
    2: [
        {"art": "kritik", "produkt": "Insilo", "text": "Die Sprechererkennung ordnet Sprecher falsch zu.", "zitat": "die Sprechererkennung ordnet Sprecher falsch zu"},
        {"art": "einwand", "produkt": "Insilo", "text": "Der Preis für drei Nutzer ist zu hoch.", "zitat": "Preis für drei Nutzer sei zu hoch"},
    ],
}


@pytest.fixture
def modell(monkeypatch):
    aufrufe = {"notizen": 0, "themen": 0}

    async def chat(cfg, system, user, **kwargs):
        import json
        if user.startswith("Welche Aussagen"):
            aufrufe["notizen"] += 1
            # Nummern der Notizen im Stapel: Notiz A und B tragen Aussagen, C nicht.
            aus = []
            for i in range(1, len([z for z in user.split("\n") if z.startswith("[")]) + 1):
                teil = user.split(f"[{i}]")[1].split(f"[{i + 1}]")[0]
                if "Sprechererkennung verwechselt" in teil:
                    aus += [{**a, "notiz": i} for a in AUSSAGEN[1]]
                elif "ordnet Sprecher falsch" in teil:
                    aus += [{**a, "notiz": i} for a in AUSSAGEN[2]]
            return json.dumps({"aussagen": aus})
        aufrufe["themen"] += 1
        zeilen = [z for z in user.split("\n") if z.startswith("[")]
        kritik = [i + 1 for i, z in enumerate(zeilen) if "(kritik" in z]
        rest = [i + 1 for i, z in enumerate(zeilen) if "(kritik" not in z]
        return json.dumps({"themen": [
            {"titel": "Sprechererkennung verwechselt Stimmen", "produkt": "Insilo", "art": "kritik", "aussagen": kritik,
             "bedeutung": "Die Diarisierung ist bei mehreren Sprechern nicht verlässlich.", "vorschlag": "Diarisierung mit drei und mehr Sprechern gezielt prüfen."},
            {"titel": "Sonstiges", "produkt": None, "art": "wunsch", "aussagen": rest + [99], "bedeutung": "", "vorschlag": None},
            {"titel": "Leer", "produkt": None, "art": "lob", "aussagen": [], "bedeutung": "", "vorschlag": None},
        ]})

    monkeypatch.setattr(erkenntnisse, "chat", chat)
    return aufrufe


async def _bestand(k):
    a = (await k.post("/api/companies", json={"name": "Nordlicht Steuerberatung"})).json()
    b = (await k.post("/api/companies", json={"name": "Hanseatic Legal"})).json()
    for firma, text in ((a, NOTIZ_A), (b, NOTIZ_B), (a, NOTIZ_C)):
        r = await k.post("/api/activities", json={"kind": "note", "body": text, "company_id": firma["id"]})
        assert r.status_code in (200, 201), r.text
    return a, b


async def test_lauf_zieht_aussagen_und_bildet_themen(datenbank, modell):
    async with klient_fuer("erkenntnisse-1") as k:
        await k.put("/api/settings", json={"llm_base_url": "http://modell.local/v1", "llm_model": "t", "anreicherung_automatisch": False})
        a, b = await _bestand(k)
        vor = (await k.get("/api/erkenntnisse?tage=90")).json()
        assert vor["lauf"] is None and vor["offene_notizen"] == 3 and vor["aussagen"] == []

        r = await k.post("/api/erkenntnisse/auswerten", json={"tage": 90})
        assert r.status_code == 202, r.text
        await erkenntnisse.hintergrund_abwarten()

        d = (await k.get("/api/erkenntnisse?tage=90")).json()
        lauf = d["lauf"]
        assert lauf["status"] == "fertig", lauf
        assert lauf["fortschritt"] == {"gelesen": 3, "gesamt": 3, "schritt": "fertig"}
        # Vier Aussagen mit Zitat — die erfundene fiel weg; Notiz C gab nichts her.
        assert len(d["aussagen"]) == 4 and lauf["aussagen_anzahl"] == 4
        assert d["nach_art"] == {"lob": 0, "kritik": 2, "wunsch": 1, "einwand": 1, "frage": 0}
        assert d["offene_notizen"] == 0
        # Zwei Themen: das dritte hatte keine Aussage. Die 99 ist verschwunden.
        assert [t["titel"] for t in lauf["themen"]] == ["Sprechererkennung verwechselt Stimmen", "Sonstiges"]
        kritik = lauf["themen"][0]
        assert len(kritik["aussagen"]) == 2 and set(kritik["firmen"]) == {"Nordlicht Steuerberatung", "Hanseatic Legal"}
        assert kritik["vorschlag"].startswith("Diarisierung")
        ids = {x["id"] for x in d["aussagen"]}
        assert set(kritik["aussagen"]) <= ids and len(lauf["themen"][1]["aussagen"]) == 2

        # Ein zweiter Lauf liest keine Notiz noch einmal.
        await k.post("/api/erkenntnisse/auswerten", json={"tage": 90})
        await erkenntnisse.hintergrund_abwarten()
        d2 = (await k.get("/api/erkenntnisse?tage=90")).json()
        assert d2["lauf"]["fortschritt"]["gesamt"] == 0 and len(d2["aussagen"]) == 4
        assert modell["notizen"] == 1 and modell["themen"] == 2


async def test_ohne_modell_409(datenbank, modell):
    async with klient_fuer("erkenntnisse-2") as k:
        await k.put("/api/settings", json={"llm_base_url": None})
        assert (await k.post("/api/erkenntnisse/auswerten", json={"tage": 90})).status_code == 409
