"""Tickets: Anliegen aufnehmen, zuweisen, beantworten, schließen.

Der Schwerpunkt liegt auf der Uhr. Eine falsche Frist ist schlimmer als
gar keine: Sie sieht aus wie eine Zusage, und danach richtet sich, wen
man morgens zuerst anruft.
"""

from datetime import datetime, timedelta

import orjson

from app.routers.tickets import kennung_aus
from tests.conftest import klient_fuer


def test_kennung_ist_lesbar_und_sortierbar():
    assert kennung_aus(42, datetime(2026, 9, 4)) == "T-2026-0042"
    assert kennung_aus(7, datetime(2026, 1, 1)) == "T-2026-0007"


async def test_pipeline_und_kategorien_werden_ausgesaet(datenbank):
    async with klient_fuer("ticket-saat") as k:
        pipelines = (await k.get("/api/tickets/pipelines")).json()
        assert len(pipelines) == 1
        assert pipelines[0]["name"] == "Anliegen"
        arten = [s["art"] for s in pipelines[0]["stufen"]]
        assert arten == ["neu", "wartet_auf_kontakt", "offen", "abgeschlossen"]

        kategorien = [c["name"] for c in (await k.get("/api/tickets/kategorien")).json()]
        assert "Störung" in kategorien and "Rechnung" in kategorien


async def test_ticket_anlegen_setzt_nummer_und_frist(datenbank):
    async with klient_fuer("ticket-neu") as k:
        t = (await k.post("/api/tickets", json={
            "betreff": "Drucker meldet Fehler", "prioritaet": "hoch", "kategorie": "Störung",
        })).json()

        assert t["nummer"] == 1
        assert t["kennung"].startswith("T-") and t["kennung"].endswith("0001")
        assert t["stufe_art"] == "neu"          # landet in der ersten Stufe
        assert t["offen"] is True
        assert t["ueberfaellig"] is False

        # Acht Stunden für „hoch", aus den Einstellungen.
        faellig = datetime.fromisoformat(t["faellig_am"])
        angelegt = datetime.fromisoformat(t["created_at"])
        assert timedelta(hours=7, minutes=55) < faellig - angelegt < timedelta(hours=8, minutes=5)

        # Die zweite bekommt die nächste Nummer.
        zwei = (await k.post("/api/tickets", json={"betreff": "Noch eins"})).json()
        assert zwei["nummer"] == 2


async def test_frist_folgt_der_dringlichkeit(datenbank):
    """Wer hochstuft, verkürzt damit die Zusage — sonst wäre sie gelogen."""
    async with klient_fuer("ticket-frist") as k:
        t = (await k.post("/api/tickets", json={"betreff": "Erst harmlos", "prioritaet": "niedrig"})).json()
        weit = datetime.fromisoformat(t["faellig_am"])

        eilig = (await k.patch(f"/api/tickets/{t['id']}", json={"prioritaet": "dringend"})).json()
        nah = datetime.fromisoformat(eilig["faellig_am"])
        assert nah < weit
        # Vier Stunden ab dem Eingang, nicht ab der Umstufung: Die Uhr des
        # Kunden läuft seit seiner Meldung.
        angelegt = datetime.fromisoformat(t["created_at"])
        assert timedelta(hours=3, minutes=55) < nah - angelegt < timedelta(hours=4, minutes=5)


async def test_eigene_frist_bleibt_stehen(datenbank):
    async with klient_fuer("ticket-eigenfrist") as k:
        eigen = (datetime.now().astimezone() + timedelta(days=10)).isoformat()
        t = (await k.post("/api/tickets", json={
            "betreff": "Mit Absprache", "prioritaet": "niedrig", "faellig_am": eigen,
        })).json()
        assert datetime.fromisoformat(t["faellig_am"]).date() == datetime.fromisoformat(eigen).date()


async def test_ueberfaellig_nur_wenn_es_an_uns_liegt(datenbank):
    """Wartet das Ticket auf den Kunden, ist es nicht unsere Verspätung."""
    async with klient_fuer("ticket-ueber") as k:
        gestern = (datetime.now().astimezone() - timedelta(days=1)).isoformat()
        t = (await k.post("/api/tickets", json={"betreff": "Längst fällig", "faellig_am": gestern})).json()
        assert t["ueberfaellig"] is True

        stufen = (await k.get("/api/tickets/pipelines")).json()[0]["stufen"]
        warten = next(s for s in stufen if s["art"] == "wartet_auf_kontakt")
        nach = (await k.post(f"/api/tickets/{t['id']}/stufe", json={"stage_id": warten["id"]})).json()
        assert nach["ueberfaellig"] is False
        assert nach["offen"] is True


async def test_schliessen_und_wieder_oeffnen(datenbank):
    async with klient_fuer("ticket-schliessen") as k:
        t = (await k.post("/api/tickets", json={"betreff": "Wird erledigt"})).json()
        stufen = (await k.get("/api/tickets/pipelines")).json()[0]["stufen"]
        fertig = next(s for s in stufen if s["art"] == "abgeschlossen")
        neu = next(s for s in stufen if s["art"] == "neu")

        zu = (await k.post(f"/api/tickets/{t['id']}/stufe", json={"stage_id": fertig["id"]})).json()
        assert zu["offen"] is False
        assert zu["geschlossen_am"] is not None
        assert zu["ueberfaellig"] is False

        # Der Wechsel steht im Verlauf — sonst ist später nicht mehr
        # erkennbar, wann und von wem geschlossen wurde.
        verlauf = (await k.get(f"/api/activities?ticket_id={t['id']}")).json()
        assert any(a["kind"] == "stage_change" and "Abgeschlossen" in (a["subject"] or "") for a in verlauf)

        auf = (await k.post(f"/api/tickets/{t['id']}/stufe", json={"stage_id": neu["id"]})).json()
        assert auf["offen"] is True
        assert auf["geschlossen_am"] is None


async def test_stufe_aus_fremder_pipeline_wird_abgelehnt(datenbank):
    async with klient_fuer("ticket-fremd-a") as a, klient_fuer("ticket-fremd-b") as b:
        t = (await a.post("/api/tickets", json={"betreff": "Meins"})).json()
        fremde_stufe = (await b.get("/api/tickets/pipelines")).json()[0]["stufen"][0]["id"]
        antwort = await a.post(f"/api/tickets/{t['id']}/stufe", json={"stage_id": fremde_stufe})
        assert antwort.status_code == 404


async def test_brett_zaehlt_je_stufe(datenbank):
    async with klient_fuer("ticket-brett") as k:
        stufen = (await k.get("/api/tickets/pipelines")).json()[0]["stufen"]
        fertig = next(s for s in stufen if s["art"] == "abgeschlossen")
        for i in range(3):
            (await k.post("/api/tickets", json={"betreff": f"Offen {i}"})).json()
        zu = (await k.post("/api/tickets", json={"betreff": "Erledigt"})).json()
        await k.post(f"/api/tickets/{zu['id']}/stufe", json={"stage_id": fertig["id"]})

        brett = (await k.get("/api/tickets/brett")).json()
        nach_art = {s["stufe"]["art"]: s["anzahl"] for s in brett["spalten"]}
        assert nach_art["neu"] == 3
        assert nach_art["abgeschlossen"] == 1
        assert nach_art["offen"] == 0
        assert len(brett["spalten"]) == 4


async def test_warteschlange_und_meine(datenbank):
    """Ohne Zuständigen ist ein Ticket eine Warteschlange, keine Arbeit."""
    async with klient_fuer("ticket-queue") as k:
        wer = (await k.get("/api/mitglieder/wer")).json()
        await k.post("/api/tickets", json={"betreff": "Niemand da"})
        meins = (await k.post("/api/tickets", json={"betreff": "Gehört mir", "owner_id": wer["user_id"]})).json()

        offen_ohne = (await k.get("/api/tickets?ohne_besitzer=true")).json()
        assert [t["betreff"] for t in offen_ohne] == ["Niemand da"]

        meine = (await k.get("/api/tickets?mein=true")).json()
        assert [t["betreff"] for t in meine] == ["Gehört mir"]
        assert meine[0]["besitzer_name"]

        assert (await k.get("/api/tickets/anzahl?ohne_besitzer=true")).json()["anzahl"] == 1
        assert (await k.get(f"/api/tickets/{meins['id']}")).json()["kennung"].endswith("0002")


async def test_filter_und_sortierung_ueber_die_segmente(datenbank):
    async with klient_fuer("ticket-segment") as k:
        await k.post("/api/tickets", json={"betreff": "Alarm", "prioritaet": "dringend", "kategorie": "Störung"})
        await k.post("/api/tickets", json={"betreff": "Kleinigkeit", "prioritaet": "niedrig"})

        f = orjson.dumps([{"feld": "prioritaet", "operator": "ist", "wert": "dringend"}]).decode()
        treffer = (await k.get(f"/api/tickets?filter={f}")).json()
        assert [t["betreff"] for t in treffer] == ["Alarm"]
        assert (await k.get(f"/api/tickets/anzahl?filter={f}")).json()["anzahl"] == 1

        auf = (await k.get("/api/tickets?sort=betreff&richtung=asc")).json()
        assert [t["betreff"] for t in auf] == ["Alarm", "Kleinigkeit"]

        # Die Feldliste trägt die Ticket-Felder, damit die Oberfläche sie
        # ohne eigene Aufzählung anbieten kann.
        felder = (await k.get("/api/ansichten/felder?entity=tickets")).json()
        schluessel = {f["schluessel"] for f in felder["felder"]}
        assert {"betreff", "prioritaet", "faellig_am", "owner_id"} <= schluessel

        # Und eine Ansicht lässt sich darauf speichern.
        a = (await k.post("/api/ansichten", json={
            "entity": "tickets", "name": "Dringend offen",
            "filter": [{"feld": "prioritaet", "operator": "ist", "wert": "dringend"}],
        })).json()
        assert a["entity"] == "tickets"


async def test_verlauf_und_aufgabe_haengen_am_ticket(datenbank):
    async with klient_fuer("ticket-verlauf") as k:
        t = (await k.post("/api/tickets", json={"betreff": "Mit Verlauf"})).json()

        await k.post("/api/activities", json={
            "kind": "call", "subject": "Rückruf", "body": "Kunde erreicht", "ticket_id": t["id"],
        })
        verlauf = (await k.get(f"/api/activities?ticket_id={t['id']}")).json()
        assert [a["subject"] for a in verlauf if a["kind"] == "call"] == ["Rückruf"]

        await k.post("/api/tasks", json={"title": "Ersatzteil bestellen", "ticket_id": t["id"]})
        aufgaben = (await k.get(f"/api/tasks?ticket_id={t['id']}")).json()
        assert [a["title"] for a in aufgaben] == ["Ersatzteil bestellen"]


async def test_stapel_und_loeschen(datenbank):
    async with klient_fuer("ticket-stapel") as k:
        wer = (await k.get("/api/mitglieder/wer")).json()
        ids = [
            (await k.post("/api/tickets", json={"betreff": f"Sammel {i}"})).json()["id"]
            for i in range(3)
        ]
        bilanz = (await k.post("/api/tickets/mehrere", json={
            "ids": ids, "prioritaet": "hoch", "owner_id": wer["user_id"],
        })).json()
        assert bilanz["geaendert"] == 3
        assert all(t["prioritaet"] == "hoch" for t in (await k.get("/api/tickets?q=Sammel")).json())

        assert (await k.post("/api/tickets/mehrere/loeschen", json={"ids": ids[:2]})).json()["geloescht"] == 2
        assert len((await k.get("/api/tickets?q=Sammel")).json()) == 1


async def test_stapel_schliessen_stoppt_die_uhr(datenbank):
    async with klient_fuer("ticket-stapel-zu") as k:
        stufen = (await k.get("/api/tickets/pipelines")).json()[0]["stufen"]
        fertig = next(s for s in stufen if s["art"] == "abgeschlossen")
        ids = [(await k.post("/api/tickets", json={"betreff": f"Weg {i}"})).json()["id"] for i in range(2)]

        await k.post("/api/tickets/mehrere", json={"ids": ids, "stage_id": fertig["id"]})
        for t in (await k.get("/api/tickets?q=Weg")).json():
            assert t["offen"] is False
            assert t["geschlossen_am"] is not None


async def test_tickets_bleiben_in_der_organisation(datenbank):
    async with klient_fuer("ticket-org-a") as a, klient_fuer("ticket-org-b") as b:
        t = (await a.post("/api/tickets", json={"betreff": "Vertraulich"})).json()
        assert (await b.get(f"/api/tickets/{t['id']}")).status_code == 404
        assert (await b.get("/api/tickets")).json() == []
        assert (await b.delete(f"/api/tickets/{t['id']}")).status_code == 404
        # Auch der Stapel greift nicht hinüber.
        assert (await b.post("/api/tickets/mehrere", json={
            "ids": [t["id"]], "prioritaet": "dringend"
        })).json()["geaendert"] == 0


async def test_kategorien_pflegen(datenbank):
    async with klient_fuer("ticket-kat") as k:
        neu = (await k.post("/api/tickets/kategorien", json={"name": "Datenschutz"})).json()
        namen = [c["name"] for c in (await k.get("/api/tickets/kategorien")).json()]
        assert "Datenschutz" in namen

        # Abschalten statt löschen: bestehende Tickets behalten die Angabe.
        t = (await k.post("/api/tickets", json={"betreff": "Mit Kategorie", "kategorie": "Datenschutz"})).json()
        await k.delete(f"/api/tickets/kategorien/{neu['id']}")
        assert "Datenschutz" not in [c["name"] for c in (await k.get("/api/tickets/kategorien")).json()]
        assert (await k.get(f"/api/tickets/{t['id']}")).json()["kategorie"] == "Datenschutz"
