"""Ein Lead entsteht vor allem anderen.

Der Anruf kommt, bevor jemand weiß, welche Firma dahintersteht. Wer an
dieser Stelle eine Firma erzwingt, bekommt „Firma unbekannt GmbH" im
Bestand — und die bleibt dort für immer. Also: leer anlegen dürfen und
später zuordnen. Das prüfen diese Tests, samt der Ansprechpartner, die
sich unterwegs herausstellen.
"""

from tests.conftest import klient_fuer


async def test_lead_ohne_firma_und_ohne_kontakt(datenbank):
    async with klient_fuer("lead-leer") as k:
        lead = (await k.post("/api/deals", json={"name": "Anruf Messe Halle 4"})).json()
        assert lead["company_id"] is None
        assert lead["company_name"] is None
        assert lead["kontakt_anzahl"] == 0
        # Er steht trotzdem auf dem Board, auf der ersten Stufe.
        assert lead["stage_name"]
        assert [d["name"] for d in (await k.get("/api/deals")).json()] == ["Anruf Messe Halle 4"]


async def test_firma_laesst_sich_nachtragen_und_wieder_loesen(datenbank):
    async with klient_fuer("lead-nachtragen") as k:
        lead = (await k.post("/api/deals", json={"name": "Rückruf"})).json()
        firma = (await k.post("/api/companies", json={"name": "Werft Nord"})).json()

        zugeordnet = (await k.patch(f"/api/deals/{lead['id']}", json={
            "company_id": firma["id"],
        })).json()
        assert zugeordnet["company_id"] == firma["id"]
        assert zugeordnet["company_name"] == "Werft Nord"

        # Und wieder ab — eine Fehlzuordnung muss sich lösen lassen.
        geloest = (await k.patch(f"/api/deals/{lead['id']}", json={"company_id": None})).json()
        assert geloest["company_id"] is None


async def test_beteiligte_hinzufuegen_und_entfernen(datenbank):
    async with klient_fuer("lead-beteiligte") as k:
        lead = (await k.post("/api/deals", json={"name": "Ausschreibung Kran"})).json()
        a = (await k.post("/api/contacts", json={"first_name": "Bernd", "last_name": "Meyer"})).json()
        b = (await k.post("/api/contacts", json={"first_name": "Ina", "last_name": "Krüger"})).json()

        assert (await k.get(f"/api/deals/{lead['id']}/beteiligte")).json() == []

        liste = (await k.post(f"/api/deals/{lead['id']}/beteiligte", json={
            "contact_id": a["id"], "role": "Entscheider",
        })).json()
        assert [x["name"] for x in liste] == ["Bernd Meyer"]
        assert liste[0]["role"] == "Entscheider"

        liste = (await k.post(f"/api/deals/{lead['id']}/beteiligte", json={
            "contact_id": b["id"],
        })).json()
        assert sorted(x["name"] for x in liste) == ["Bernd Meyer", "Ina Krüger"]
        assert (await k.get(f"/api/deals/{lead['id']}")).json()["kontakt_anzahl"] == 2

        assert (await k.delete(f"/api/deals/{lead['id']}/beteiligte/{a['id']}")).status_code == 204
        assert [x["name"] for x in (await k.get(f"/api/deals/{lead['id']}/beteiligte")).json()] == [
            "Ina Krüger"
        ]
        # Der Kontakt selbst bleibt — gelöst ist nicht gelöscht.
        assert (await k.get(f"/api/contacts/{a['id']}")).status_code == 200


async def test_derselbe_kontakt_zweimal_aendert_die_rolle(datenbank):
    """Wer jemanden nochmal hinzufügt, meint eine Korrektur, keinen Fehler."""
    async with klient_fuer("lead-rolle") as k:
        lead = (await k.post("/api/deals", json={"name": "Wartung"})).json()
        p = (await k.post("/api/contacts", json={"first_name": "Ute", "last_name": "Lohse"})).json()

        await k.post(f"/api/deals/{lead['id']}/beteiligte", json={
            "contact_id": p["id"], "role": "Anwenderin",
        })
        liste = (await k.post(f"/api/deals/{lead['id']}/beteiligte", json={
            "contact_id": p["id"], "role": "Entscheiderin",
        })).json()
        assert len(liste) == 1
        assert liste[0]["role"] == "Entscheiderin"


async def test_erster_beteiligter_bringt_seine_firma_mit(datenbank):
    """Fast immer gemeint — und nur eine Vorbelegung, kein Zwang."""
    async with klient_fuer("lead-erbt") as k:
        firma = (await k.post("/api/companies", json={"name": "Nordlicht"})).json()
        p = (await k.post("/api/contacts", json={
            "first_name": "Tim", "last_name": "Reinhardt", "company_id": firma["id"],
        })).json()
        lead = (await k.post("/api/deals", json={"name": "Anfrage"})).json()
        assert lead["company_id"] is None

        await k.post(f"/api/deals/{lead['id']}/beteiligte", json={"contact_id": p["id"]})
        assert (await k.get(f"/api/deals/{lead['id']}")).json()["company_name"] == "Nordlicht"


async def test_gesetzte_firma_wird_nicht_ueberschrieben(datenbank):
    """Die Vorbelegung gilt nur, solange nichts dasteht."""
    async with klient_fuer("lead-erbt-nicht") as k:
        gewaehlt = (await k.post("/api/companies", json={"name": "Gewählt"})).json()
        andere = (await k.post("/api/companies", json={"name": "Andere"})).json()
        p = (await k.post("/api/contacts", json={
            "first_name": "Ann", "last_name": "Voss", "company_id": andere["id"],
        })).json()
        lead = (await k.post("/api/deals", json={
            "name": "Projekt", "company_id": gewaehlt["id"],
        })).json()

        await k.post(f"/api/deals/{lead['id']}/beteiligte", json={"contact_id": p["id"]})
        assert (await k.get(f"/api/deals/{lead['id']}")).json()["company_name"] == "Gewählt"


async def test_beteiligte_bleiben_in_der_organisation(datenbank):
    async with klient_fuer("lead-org-a") as a, klient_fuer("lead-org-b") as b:
        lead = (await a.post("/api/deals", json={"name": "Vertraulich"})).json()
        fremder = (await b.post("/api/contacts", json={"last_name": "Fremd"})).json()

        assert (await b.get(f"/api/deals/{lead['id']}/beteiligte")).status_code == 404
        assert (await b.post(f"/api/deals/{lead['id']}/beteiligte", json={
            "contact_id": fremder["id"],
        })).status_code == 404
        # Und ein fremder Kontakt lässt sich auch vom Eigentümer nicht anhängen.
        assert (await a.post(f"/api/deals/{lead['id']}/beteiligte", json={
            "contact_id": fremder["id"],
        })).status_code == 404
