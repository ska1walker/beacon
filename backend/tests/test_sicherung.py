"""Sicherung und Wiederherstellung.

Das ist der Test, an dem die Existenz der Anwendung auf einer Box hängt:
Eine Deinstallation legt die Datenbank neu an. Wenn der Abzug den Bestand
nicht vollständig zurückbringt, ist er wertlos — und das merkt man sonst
genau einmal, nämlich zu spät.
"""

import pathlib

import pytest

from app import sicherung
from app.db import acquire_as


def klient_fuer(name: str):
    """Ein eigener Nutzer für Tests, die Daten zerstören.

    Wer die Pipeline einer Organisation löscht, macht sie für jeden
    folgenden Test unbrauchbar — die Tests teilen sich eine Datenbank.
    Deshalb bekommt jeder zerstörende Test seine eigene Organisation.
    """
    from httpx import ASGITransport, AsyncClient

    from app.main import app

    return AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        headers={"X-Bfl-User": name},
    )


@pytest.fixture(autouse=True)
def eigene_ablage(tmp_path_factory, monkeypatch):
    """Jeder Lauf sichert in ein eigenes Verzeichnis, nicht in ./daten."""
    ordner = tmp_path_factory.mktemp("sicherungen")
    monkeypatch.setattr(sicherung.settings, "app_data_dir", str(ordner))
    return ordner


async def _bestand_anlegen(klient, marke: str) -> dict:
    """Ein kleiner, vollständiger Bestand. `marke` hält die Tests
    auseinander — sie teilen sich eine Datenbank, und eine E-Mail-Adresse
    darf je Organisation nur einmal vorkommen."""
    firma = (
        await klient.post(
            "/api/companies",
            json={
                "name": f"Sicherungsfirma {marke}",
                "city": "Lüneburg",
                "lifecycle_stage": "opportunity",
            },
        )
    ).json()
    kontakt = (
        await klient.post(
            "/api/contacts",
            json={
                "first_name": "Anna",
                "last_name": "Beispiel",
                "email": f"anna-{marke}@sicherungsfirma.de",
                "company_id": firma["id"],
                "buying_role": "Entscheiderin",
            },
        )
    ).json()
    deal = (
        await klient.post(
            "/api/deals",
            json={
                "name": f"Analyst — Sicherungstest {marke}",
                "company_id": firma["id"],
                "product": "analyst",
                "amount_cents": 1450000,
                "close_date": "2026-12-01",
            },
        )
    ).json()
    await klient.post(
        "/api/activities",
        json={"kind": "call", "subject": "Erstgespräch", "body": "Lief gut.", "deal_id": deal["id"]},
    )
    await klient.post("/api/tasks", json={"title": "Angebot schicken", "deal_id": deal["id"]})
    return {"firma": firma, "kontakt": kontakt, "deal": deal}


async def test_abzug_enthaelt_alles(kai, eigene_ablage):
    await _bestand_anlegen(kai, "A")

    antwort = await kai.post("/api/sicherung")
    assert antwort.status_code == 201
    bilanz = antwort.json()

    assert bilanz["zeilen"]["companies"] >= 1
    assert bilanz["zeilen"]["contacts"] >= 1
    assert bilanz["zeilen"]["deals"] >= 1
    assert bilanz["zeilen"]["activities"] >= 1
    assert bilanz["zeilen"]["tasks"] >= 1
    assert bilanz["zeilen"]["pipeline_stages"] == 7

    dateien = list(pathlib.Path(eigene_ablage).glob("sicherungen/*.json"))
    assert len(dateien) == 1
    # Der Abzug trägt den Schlüssel zum Sprachmodell — er darf nicht
    # für jeden auf der Box lesbar sein.
    assert oct(dateien[0].stat().st_mode)[-3:] == "600"


async def test_wiederherstellung_in_frische_organisation(datenbank, eigene_ablage):
    """Der Ernstfall, nachgestellt.

    Die Quelle sichert. Dann wird ihr Bestand hart entfernt — das ist, was
    eine Deinstallation tut. Das Ziel spielt die Organisation nach der
    Neuinstallation: Sie liest den Abzug ein und muss danach denselben
    Bestand haben, unter ihrer eigenen Org-Kennung.
    """
    async with klient_fuer("quelle-b") as quelle, klient_fuer("ziel-b") as ziel:
        # Die Zielorganisation zuerst entstehen lassen: Sonst entstünde sie
        # erst nach dem Abzug, und der Wiederanlauf-Pfad aus _einrichten()
        # spielte ihn von sich aus ein. Dann prüfte dieser Test nicht mehr
        # die ausdrückliche Wiederherstellung, sondern eine andere Funktion.
        await ziel.get("/api/companies")

        original = await _bestand_anlegen(quelle, "B")
        await quelle.post("/api/sicherung")
        await _bestand_loeschen(quelle)

        stand = sicherung.staende()[0]["name"]
        daten = sicherung.abzug_lesen(stand)

        async with acquire_as(await _kennung(ziel)) as conn:
            org_id, user_id = await _org_und_nutzer(conn)
            ergebnis = await sicherung.zurueckspielen(conn, daten, org_id, user_id)

        assert ergebnis["geschrieben"]["companies"] >= 1
        assert ergebnis["geschrieben"]["deals"] >= 1

        firmen = (await ziel.get("/api/companies")).json()
        assert "Sicherungsfirma B" in [f["name"] for f in firmen]

        wieder = next(f for f in firmen if f["name"] == "Sicherungsfirma B")
        assert wieder["city"] == "Lüneburg"
        assert wieder["lifecycle_stage"] == "opportunity"
        # Die Verknüpfungen müssen mitkommen, nicht nur die Zeilen.
        assert wieder["contact_count"] >= 1
        assert wieder["open_deal_count"] >= 1

        deals = (await ziel.get(f"/api/deals?company_id={wieder['id']}")).json()
        zurueck = next(d for d in deals if d["name"] == "Analyst — Sicherungstest B")
        assert zurueck["amount_cents"] == original["deal"]["amount_cents"]
        assert zurueck["close_date"] == "2026-12-01"
        # Die Stufe hängt an einer Stufen-Kennung, die ebenfalls aus dem
        # Abzug kommt — sie muss dieselbe sein.
        assert zurueck["stage_name"] == original["deal"]["stage_name"]

        verlauf = (await ziel.get(f"/api/activities?deal_id={zurueck['id']}")).json()
        assert any(a["subject"] == "Erstgespräch" for a in verlauf)

        aufgaben = (await ziel.get(f"/api/tasks?deal_id={zurueck['id']}")).json()
        assert any(a["title"] == "Angebot schicken" for a in aufgaben)

        kontakte = (await ziel.get(f"/api/contacts?company_id={wieder['id']}")).json()
        assert any(k["email"] == "anna-B@sicherungsfirma.de" for k in kontakte)
        assert kontakte[0]["company_name"] == "Sicherungsfirma B"


async def test_wiederherstellung_ueberschreibt_nichts(kai, eigene_ablage):
    """Zweimal einlesen darf nichts doppeln und nichts zerstören."""
    await _bestand_anlegen(kai, "C")
    await kai.post("/api/sicherung")
    stand = sicherung.staende()[0]["name"]

    vorher = (await kai.get("/api/companies")).json()
    firma_id = next(f["id"] for f in vorher if f["name"] == "Sicherungsfirma C")
    await kai.patch(f"/api/companies/{firma_id}", json={"city": "Hamburg"})

    antwort = await kai.post(f"/api/sicherung/wiederherstellen?name={stand}")
    assert antwort.status_code == 200
    # Nichts geschrieben, alles schon da — und genau das muss die Antwort
    # sagen, statt eine Rettung zu behaupten.
    assert antwort.json()["geschrieben"]["companies"] == 0
    assert antwort.json()["uebersprungen"]["companies"] >= 1

    nachher = (await kai.get("/api/companies")).json()
    treffer = [f for f in nachher if f["name"] == "Sicherungsfirma C"]
    assert len(treffer) == 1, "die Wiederherstellung hat gedoppelt"
    assert treffer[0]["city"] == "Hamburg", "die Wiederherstellung hat Neueres überschrieben"


async def test_ausfuhr_traegt_keinen_schluessel(kai, eigene_ablage):
    await kai.put(
        "/api/settings",
        json={"llm_base_url": "http://beispiel.test/v1", "llm_api_key": "streng-geheim"},
    )
    antwort = await kai.get("/api/sicherung/ausfuhr")
    assert antwort.status_code == 200
    assert "streng-geheim" not in antwort.text
    assert "attachment" in antwort.headers["content-disposition"]


async def test_unbekanntes_format_wird_abgelehnt(kai, eigene_ablage):
    async with acquire_as((await _kennung(kai))) as conn:
        org_id, user_id = await _org_und_nutzer(conn)
        with pytest.raises(ValueError, match="Unbekanntes Format"):
            await sicherung.zurueckspielen(conn, {"format": 99}, org_id, user_id)


# ---- Hilfen ------------------------------------------------------------

async def _bestand_loeschen(klient) -> None:
    """Entfernt die Fachdaten dieser Organisation hart — wie es eine
    Deinstallation tut.

    Mit Nutzerkontext, und das ist keine Förmlichkeit: Ohne ihn löscht
    diese Funktion nichts. Die Policies aus 0002 gelten unter FORCE auch
    für das Löschen, und ohne gesetzten Kontext trifft die Bedingung
    keine einzige Zeile — der Test hatte hier zuerst schweigend nichts
    getan und trotzdem bestanden.
    """
    async with acquire_as(await _kennung(klient)) as conn:
        for tabelle in (
            "activities", "tasks", "deal_contacts", "deals",
            "contacts", "pipeline_stages", "pipelines", "companies",
        ):
            await conn.execute(f"delete from public.{tabelle}")


async def _kennung(klient):
    """Die interne Nutzer-Kennung hinter dem X-Bfl-User des Klienten."""
    from app.auth import _ensure_user_and_org

    return (await _ensure_user_and_org(klient.headers["X-Bfl-User"])).user_id


async def _org_und_nutzer(conn):
    zeile = await conn.fetchrow(
        "select r.org_id, r.user_id from public.user_org_roles r "
        "where r.user_id = public.current_user_id() limit 1"
    )
    return zeile["org_id"], zeile["user_id"]


async def test_zweiter_nutzer_bekommt_keine_fremden_daten(datenbank, eigene_ablage):
    """Der Schutz vor dem eigenen Rettungsmechanismus.

    Liegt ein Abzug neben den Daten, spielt ihn eine frisch angelegte
    Organisation zurück — das ist der Wiederanlauf nach einer
    Deinstallation. Meldet sich aber schlicht ein zweiter Mensch auf
    derselben Box an, ist das kein Wiederanlauf: Er bekommt eine leere
    Organisation, nicht den Vertrieb des ersten.

    Der Bestand der Quelle wird vorher gelöscht, und das ist der Kern des
    Tests: Solange die Zeilen noch da sind, verhindert schon der
    Schlüsselkonflikt jedes Einfügen — der Schutz sähe wirksam aus, ohne
    es zu sein. Erst ohne die Originalzeilen zeigt sich, ob er trägt.
    """
    async with klient_fuer("quelle-d") as quelle:
        await _bestand_anlegen(quelle, "D")
        await quelle.post("/api/sicherung")
        await _bestand_loeschen(quelle)

    assert sicherung.staende(), "ohne Abzug prüft dieser Test nichts"

    async with klient_fuer("zweiter-d") as zweiter:
        firmen = (await zweiter.get("/api/companies")).json()
        pipelines = (await zweiter.get("/api/pipelines")).json()

    assert firmen == [], "die zweite Organisation hat fremde Firmen bekommen"
    # Eine eigene, leere Pipeline bekommt sie sehr wohl — sonst könnte sie
    # kein Geschäft anlegen.
    assert len(pipelines) == 1
    assert [st["name"] for st in pipelines[0]["stages"]][0] == "Erstkontakt"


async def test_wiederanlauf_nach_deinstallation(eigene_ablage):
    """Die Datenbank ist weg, die Ablage nicht — und alles kommt zurück.

    Dieser Test steht bewusst am Ende der Datei: Er räumt die Datenbank
    vollständig leer, samt Nutzern und Organisationen, weil genau das eine
    Deinstallation über den Olares-Markt tut. Danach klopft ein Nutzer an,
    und die Anwendung muss den Bestand von allein wiederhaben.
    """
    from httpx import ASGITransport, AsyncClient

    from app.db import acquire
    from app.main import app

    async def klient(name: str) -> AsyncClient:
        return AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
            headers={"X-Bfl-User": name},
        )

    async with await klient("wiederanlauf") as c:
        await _bestand_anlegen(c, "E")
        await c.post("/api/sicherung")
        vorher = (await c.get("/api/companies")).json()
        deals_vorher = (await c.get("/api/deals")).json()

    assert vorher, "ohne Bestand prüft dieser Test nichts"

    # Die Datenbank leeren, wie Olares es tut. Ohne Nutzerkontext, aber
    # als Eigentümerin der Tabellen: Die Identitätstabellen stehen
    # ausdrücklich nicht unter FORCE (siehe 0002), damit die Erstanlage
    # überhaupt möglich ist — und hier hilft genau das beim Aufräumen.
    async with acquire() as conn:
        async with conn.transaction():
            await conn.execute("set local app.current_user_id = ''")
            for tabelle in ("activities", "tasks", "deal_contacts", "deals", "contacts",
                            "pipeline_stages", "pipelines", "companies", "audit_log",
                            "org_settings", "user_org_roles", "orgs", "users"):
                await conn.execute(f"alter table public.{tabelle} disable row level security")
                await conn.execute(f"delete from public.{tabelle}")
                await conn.execute(f"alter table public.{tabelle} enable row level security")

    async with await klient("wiederanlauf") as c:
        nachher = (await c.get("/api/companies")).json()
        deals_nachher = (await c.get("/api/deals")).json()

    assert [f["name"] for f in nachher] == [f["name"] for f in vorher]
    assert [d["name"] for d in deals_nachher] == [d["name"] for d in deals_vorher]
    assert nachher[0]["contact_count"] == vorher[0]["contact_count"]
    # Und die Stufe des Geschäfts steht wieder da, wo sie stand.
    assert deals_nachher[0]["stage_name"] == deals_vorher[0]["stage_name"]
