"""Der Assistent — Werkzeuge aus dem Skript, Karten statt Schreibzugriff.

Das Modell antwortet aus dem Skript. Geprüft wird, was uns gehört: Lesen
läuft sofort, Schreiben wird zur Karte mit fertiger Anfrage, Namen werden
im Bestand aufgelöst, Mehrdeutiges wird zur Nachfrage, und nichts wird
ohne Bestätigung geschrieben.
"""

import json

import pytest

from app import assistent
from tests.conftest import klient_fuer


def _aufruf(name, **args):
    return {"id": f"c-{name}", "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}


@pytest.fixture
def modell(monkeypatch):
    skript = {"runden": []}

    async def chat_werkzeuge(cfg, nachrichten, werkzeuge, **kw):
        skript["gesehen"] = nachrichten
        runde = skript["runden"].pop(0) if skript["runden"] else {"content": "Fertig."}
        return {"role": "assistant", "content": runde.get("content", ""), "tool_calls": runde.get("tool_calls", [])}

    monkeypatch.setattr(assistent, "chat_werkzeuge", chat_werkzeuge)
    return skript


async def _bestand(k):
    a = (await k.post("/api/companies", json={"name": "Brinkmann Baustoffe GmbH", "city": "Tecklenburg"})).json()
    b = (await k.post("/api/companies", json={"name": "Brinkmann Bau AG"})).json()
    d = (await k.post("/api/deals", json={"name": "Insilo für Brinkmann", "company_id": a["id"], "amount_cents": 500000})).json()
    return a, b, d


async def test_aufgabe_wird_zur_karte_und_nicht_geschrieben(datenbank, modell):
    async with klient_fuer("assi-a") as k:
        await k.put("/api/settings", json={"llm_base_url": "http://modell.local/v1", "llm_model": "t", "anreicherung_automatisch": False})
        a, _, _ = await _bestand(k)
        modell["runden"] = [
            {"tool_calls": [_aufruf("aufgabe_anlegen", titel="Angebot nachfassen", faellig="2026-09-11", firma="Brinkmann Baustoffe GmbH")]},
            {"content": "Die Aufgabe liegt als Karte bereit."},
        ]
        r = await k.post("/api/assistent", json={"nachricht": "Leg für Brinkmann Baustoffe eine Aufgabe an: Angebot nachfassen, Freitag"})
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["antwort"] == "Die Aufgabe liegt als Karte bereit." and d["schritte"] == ["aufgabe_anlegen"]
        [karte] = d["karten"]
        assert karte["art"] == "aufgabe" and karte["anfrage"]["pfad"] == "/api/tasks"
        assert karte["anfrage"]["koerper"]["company_id"] == a["id"]
        assert karte["anfrage"]["koerper"]["due_at"].startswith("2026-09-11")
        assert ["Firma", "Brinkmann Baustoffe GmbH"] in karte["zeilen"]
        # Nichts geschrieben — die Karte ist ein Vorschlag.
        assert (await k.get("/api/tasks")).json() == []
        # Erst die Bestätigung schreibt, mit genau der Anfrage der Karte.
        t = await k.post(karte["anfrage"]["pfad"], json=karte["anfrage"]["koerper"])
        assert t.status_code == 201 and t.json()["title"] == "Angebot nachfassen"


async def test_mehrdeutiger_name_wird_zur_nachfrage(datenbank, modell):
    async with klient_fuer("assi-b") as k:
        await k.put("/api/settings", json={"llm_base_url": "http://modell.local/v1", "llm_model": "t", "anreicherung_automatisch": False})
        await _bestand(k)
        modell["runden"] = [
            {"tool_calls": [_aufruf("aufgabe_anlegen", titel="Anrufen", firma="Brinkmann")]},
            {"content": "Meinen Sie Brinkmann Baustoffe GmbH oder Brinkmann Bau AG?"},
        ]
        d = (await k.post("/api/assistent", json={"nachricht": "Leg für Brinkmann eine Aufgabe an: Anrufen"})).json()
        assert d["karten"] == []
        werkzeug = [n for n in modell["gesehen"] if n["role"] == "tool"][0]
        assert "Mehrere Treffer" in werkzeug["content"] and "Brinkmann Bau AG" in werkzeug["content"]
        assert d["antwort"].startswith("Meinen Sie")


async def test_suchen_und_oeffnen_laufen_sofort(datenbank, modell):
    async with klient_fuer("assi-c") as k:
        await k.put("/api/settings", json={"llm_base_url": "http://modell.local/v1", "llm_model": "t", "anreicherung_automatisch": False})
        a, _, d = await _bestand(k)
        modell["runden"] = [
            {"tool_calls": [_aufruf("suchen", text="Brinkmann Baustoffe")]},
            {"tool_calls": [_aufruf("seite_oeffnen", pfad=f"/firmen/{a['id']}")]},
            {"content": "Ich öffne Brinkmann Baustoffe GmbH."},
        ]
        r = (await k.post("/api/assistent", json={"nachricht": "öffne Brinkmann Baustoffe"})).json()
        assert r["navigation"] == f"/firmen/{a['id']}" and r["schritte"] == ["suchen", "seite_oeffnen"]
        gesehen = [json.loads(n["content"]) for n in modell["gesehen"] if n["role"] == "tool"]
        assert any(t["art"] == "geschaeft" and t["name"] == "Insilo für Brinkmann" for t in gesehen[0]["treffer"])


async def test_lead_verschieben_kennt_die_stufen(datenbank, modell):
    async with klient_fuer("assi-d") as k:
        await k.put("/api/settings", json={"llm_base_url": "http://modell.local/v1", "llm_model": "t", "anreicherung_automatisch": False})
        _, _, d = await _bestand(k)
        modell["runden"] = [
            {"tool_calls": [_aufruf("lead_verschieben", lead="Insilo für Brinkmann", stufe="Nirgendwo")]},
            {"tool_calls": [_aufruf("lead_verschieben", lead="Insilo für Brinkmann", stufe="Angebot")]},
            {"content": "Karte liegt bereit."},
        ]
        r = (await k.post("/api/assistent", json={"nachricht": "Setz den Lead Insilo für Brinkmann auf Angebot"})).json()
        [karte] = r["karten"]
        assert karte["art"] == "lead_stufe" and karte["anfrage"]["pfad"] == f"/api/deals/{d['id']}/stage"
        nachfrage = [json.loads(n["content"]) for n in modell["gesehen"] if n["role"] == "tool"][0]
        assert "Die Stufen dieser Pipeline heißen" in nachfrage["nachfrage"]
        # Ausführen über die Karte wechselt die Stufe wirklich.
        s = await k.post(karte["anfrage"]["pfad"], json=karte["anfrage"]["koerper"])
        assert s.status_code == 200 and s.json()["stage_name"] == "Angebot"


async def test_ohne_modell_409(datenbank, modell):
    async with klient_fuer("assi-e") as k:
        await k.put("/api/settings", json={"llm_base_url": None})
        assert (await k.post("/api/assistent", json={"nachricht": "Hallo"})).status_code == 409
