"""Aufgaben: der Ort, an dem der Tag geplant wird.

Drei Fragen muss die Liste beantworten — was ist heute fällig, was ist
liegengeblieben, was steht an. Die Tagesgrenzen sind dabei die heikle
Stelle: In UTC gerechnet wäre „heute" für den, der davorsitzt, das
falsche Fenster.
"""

from datetime import datetime, timedelta

import orjson

from tests.conftest import klient_fuer


def _in(stunden: float) -> str:
    return (datetime.now().astimezone() + timedelta(hours=stunden)).isoformat()


async def test_art_phase_und_dringlichkeit(datenbank):
    async with klient_fuer("aufg-art") as k:
        a = (await k.post("/api/tasks", json={
            "title": "Rückruf Frau Krüger", "art": "anruf", "prioritaet": "hoch",
        })).json()
        assert a["art"] == "anruf"
        assert a["prioritaet"] == "hoch"
        assert a["phase"] == "nicht_gestartet"   # nichts gilt als angefangen
        assert a["status"] == "open"
        assert a["zustaendig_name"]              # zugewiesen an den Anlegenden

        # Angefangen ist weder offen noch erledigt.
        arbeit = (await k.patch(f"/api/tasks/{a['id']}", json={"phase": "in_arbeit"})).json()
        assert arbeit["phase"] == "in_arbeit"
        assert arbeit["status"] == "open"

        fertig = (await k.patch(f"/api/tasks/{a['id']}", json={"status": "done"})).json()
        assert fertig["completed_at"] is not None


async def test_die_drei_fragen_einer_aufgabenliste(datenbank):
    async with klient_fuer("aufg-fristen") as k:
        await k.post("/api/tasks", json={"title": "Heute", "due_at": _in(2)})
        await k.post("/api/tasks", json={"title": "Gestern", "due_at": _in(-30)})
        await k.post("/api/tasks", json={"title": "Nächste Woche", "due_at": _in(24 * 7)})
        await k.post("/api/tasks", json={"title": "Irgendwann"})

        def titel(daten):
            return [t["title"] for t in daten]

        assert titel((await k.get("/api/tasks?faellig=heute")).json()) == ["Heute"]
        assert titel((await k.get("/api/tasks?faellig=ueberfaellig")).json()) == ["Gestern"]
        assert titel((await k.get("/api/tasks?faellig=bevorstehend")).json()) == ["Nächste Woche"]
        assert titel((await k.get("/api/tasks?faellig=ohne")).json()) == ["Irgendwann"]

        # Die Übersicht zählt dieselben Fenster — in einer Abfrage.
        z = (await k.get("/api/tasks/uebersicht")).json()
        assert z["offen"] == 4
        assert (z["heute"], z["ueberfaellig"], z["bevorstehend"]) == (1, 1, 1)
        assert z["meine"] == 4


async def test_undatiertes_steht_zuletzt(datenbank):
    """NULLS FIRST setzte das Unverbindliche über das, was heute ansteht."""
    async with klient_fuer("aufg-sort") as k:
        await k.post("/api/tasks", json={"title": "Ohne Frist"})
        await k.post("/api/tasks", json={"title": "Morgen", "due_at": _in(24)})
        await k.post("/api/tasks", json={"title": "Gleich", "due_at": _in(1)})
        assert [t["title"] for t in (await k.get("/api/tasks")).json()] == [
            "Gleich", "Morgen", "Ohne Frist",
        ]


async def test_filter_sortierung_und_ansicht(datenbank):
    async with klient_fuer("aufg-segment") as k:
        await k.post("/api/tasks", json={"title": "Anrufen", "art": "anruf", "prioritaet": "dringend"})
        await k.post("/api/tasks", json={"title": "Mailen", "art": "email"})

        f = orjson.dumps([{"feld": "art", "operator": "ist", "wert": "anruf"}]).decode()
        assert [t["title"] for t in (await k.get(f"/api/tasks?filter={f}")).json()] == ["Anrufen"]
        assert (await k.get(f"/api/tasks/anzahl?filter={f}")).json()["anzahl"] == 1

        auf = (await k.get("/api/tasks?sort=title&richtung=asc")).json()
        assert [t["title"] for t in auf] == ["Anrufen", "Mailen"]

        felder = (await k.get("/api/ansichten/felder?entity=tasks")).json()
        schluessel = {x["schluessel"] for x in felder["felder"]}
        assert {"title", "art", "phase", "prioritaet", "due_at", "assigned_to"} <= schluessel
        # Aufgaben kennen keine eigenen Eigenschaften — die Liste bietet
        # deshalb auch keine an, statt beim Filtern zu scheitern.
        assert not [x for x in felder["felder"] if x["eigen"]]

        a = (await k.post("/api/ansichten", json={
            "entity": "tasks", "name": "Meine Anrufe",
            "filter": [{"feld": "art", "operator": "ist", "wert": "anruf"}],
        })).json()
        assert a["entity"] == "tasks"


async def test_bezug_auf_ticket_kontakt_und_firma(datenbank):
    async with klient_fuer("aufg-bezug") as k:
        firma = (await k.post("/api/companies", json={"name": "Werft"})).json()
        kontakt = (await k.post("/api/contacts", json={
            "first_name": "Bernd", "last_name": "Meyer", "company_id": firma["id"],
        })).json()
        ticket = (await k.post("/api/tickets", json={"betreff": "Kran hakt"})).json()

        a = (await k.post("/api/tasks", json={
            "title": "Techniker schicken", "company_id": firma["id"],
            "contact_id": kontakt["id"], "ticket_id": ticket["id"],
        })).json()
        assert a["company_name"] == "Werft"
        assert a["kontakt_name"].strip() == "Bernd Meyer"
        assert a["ticket_betreff"] == "Kran hakt"


async def test_stapel_erledigen_und_loeschen(datenbank):
    async with klient_fuer("aufg-stapel") as k:
        ids = [
            (await k.post("/api/tasks", json={"title": f"Sammel {i}"})).json()["id"]
            for i in range(3)
        ]
        bilanz = (await k.post("/api/tasks/mehrere", json={
            "ids": ids, "status": "done",
        })).json()
        assert bilanz["geaendert"] == 3
        erledigt = (await k.get("/api/tasks?status=done")).json()
        assert len(erledigt) == 3
        assert all(t["completed_at"] for t in erledigt)

        assert (await k.post("/api/tasks/mehrere/loeschen", json={"ids": ids[:2]})).json()["geloescht"] == 2
        assert len((await k.get("/api/tasks?status=done")).json()) == 1


async def test_aufgaben_bleiben_in_der_organisation(datenbank):
    async with klient_fuer("aufg-org-a") as a, klient_fuer("aufg-org-b") as b:
        fremd = (await a.post("/api/tasks", json={"title": "Vertraulich"})).json()["id"]
        assert (await b.get("/api/tasks")).json() == []
        assert (await b.delete(f"/api/tasks/{fremd}")).status_code == 404
        assert (await b.post("/api/tasks/mehrere", json={
            "ids": [fremd], "status": "done"
        })).json()["geaendert"] == 0
        # Und sie steht bei ihrem Eigentümer unverändert da.
        assert (await a.get("/api/tasks")).json()[0]["status"] == "open"
