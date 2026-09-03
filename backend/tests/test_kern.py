"""Die Pfade, deren stiller Bruch teuer wäre."""



async def test_gesundheit(kai):
    antwort = await kai.get("/health")
    assert antwort.status_code == 200
    assert antwort.json()["status"] == "ok"


async def test_ohne_kopfzeile_kein_zugriff(datenbank):
    """Fehlt die Identität, wird abgewiesen — nicht geraten.

    Auf der Box setzt Envoy den Kopf. Fehlt er trotzdem, ist die Kette
    kaputt, und dann ist Verweigern die einzige richtige Antwort.
    """
    from httpx import ASGITransport, AsyncClient

    from app.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        antwort = await c.get("/api/companies")
    assert antwort.status_code == 401


async def test_erstanlage_legt_pipeline_an(kai):
    antwort = await kai.get("/api/pipelines")
    assert antwort.status_code == 200
    pipelines = antwort.json()
    assert len(pipelines) == 1
    stufen = pipelines[0]["stages"]
    assert [s["name"] for s in stufen][:2] == ["Erstkontakt", "Qualifiziert"]
    assert [s["kind"] for s in stufen][-2:] == ["won", "lost"]


async def test_firma_anlegen_lesen_aendern_loeschen(kai):
    angelegt = await kai.post("/api/companies", json={"name": "Testfirma", "city": "Lüneburg"})
    assert angelegt.status_code == 201
    firma_id = angelegt.json()["id"]

    gelesen = await kai.get(f"/api/companies/{firma_id}")
    assert gelesen.json()["name"] == "Testfirma"

    geaendert = await kai.patch(
        f"/api/companies/{firma_id}", json={"lifecycle_stage": "customer"}
    )
    assert geaendert.json()["lifecycle_stage"] == "customer"

    geloescht = await kai.delete(f"/api/companies/{firma_id}")
    assert geloescht.status_code == 204

    # Weiches Löschen: weg aus der Sicht, nicht weg aus der Datenbank.
    assert (await kai.get(f"/api/companies/{firma_id}")).status_code == 404


async def test_mandanten_sehen_einander_nicht(kai, marc):
    """Der Test, der die Zeilensicherheit trägt.

    Ohne FORCE ROW LEVEL SECURITY in 0002 fällt genau dieser durch — und
    zwar erst dann, wenn zwei Organisationen auf derselben Box liegen.
    """
    await kai.post("/api/companies", json={"name": "Nur für Kai"})
    await marc.post("/api/companies", json={"name": "Nur für Marc"})

    kais = [f["name"] for f in (await kai.get("/api/companies")).json()]
    marcs = [f["name"] for f in (await marc.get("/api/companies")).json()]

    assert "Nur für Kai" in kais
    assert "Nur für Marc" not in kais
    assert "Nur für Marc" in marcs
    assert "Nur für Kai" not in marcs


async def test_fremden_datensatz_nicht_erreichbar(kai, marc):
    fremd = (await marc.post("/api/companies", json={"name": "Marcs Firma"})).json()["id"]
    assert (await kai.get(f"/api/companies/{fremd}")).status_code == 404
    assert (await kai.patch(f"/api/companies/{fremd}", json={"city": "X"})).status_code == 404


async def test_stufenwechsel_schreibt_verlauf_und_schliesst(kai):
    stufen = (await kai.get("/api/pipelines")).json()[0]["stages"]
    gewonnen = next(s for s in stufen if s["kind"] == "won")

    deal_id = (
        await kai.post("/api/deals", json={"name": "Testgeschäft", "amount_cents": 990000})
    ).json()["id"]

    verschoben = (
        await kai.post(f"/api/deals/{deal_id}/stage", json={"stage_id": gewonnen["id"]})
    ).json()

    assert verschoben["stage_name"] == "Gewonnen"
    assert verschoben["closed_at"] is not None

    verlauf = (await kai.get(f"/api/activities?deal_id={deal_id}")).json()
    wechsel = [a for a in verlauf if a["kind"] == "stage_change"]
    assert len(wechsel) == 1
    assert wechsel[0]["payload"]["nach"] == "Gewonnen"


async def test_stufe_nur_ueber_eigenen_weg(kai):
    """PATCH darf die Stufe nicht ändern — sonst fehlt der Verlaufseintrag."""
    stufen = (await kai.get("/api/pipelines")).json()[0]["stages"]
    deal_id = (await kai.post("/api/deals", json={"name": "Zweitgeschäft"})).json()["id"]

    antwort = await kai.patch(f"/api/deals/{deal_id}", json={"stage_id": stufen[2]["id"]})
    assert antwort.status_code == 400


async def test_board_rechnet_gewichtet(kai):
    stufen = (await kai.get("/api/pipelines")).json()[0]["stages"]
    angebot = next(s for s in stufen if s["name"] == "Angebot")

    deal_id = (
        await kai.post("/api/deals", json={"name": "Gewichtungstest", "amount_cents": 1000000})
    ).json()["id"]
    await kai.post(f"/api/deals/{deal_id}/stage", json={"stage_id": angebot["id"]})

    board = (await kai.get("/api/board")).json()
    spalte = next(s for s in board["columns"] if s["stage"]["name"] == "Angebot")

    summe = spalte["sum_amount_cents"]
    assert spalte["weighted_amount_cents"] == round(summe * spalte["stage"]["probability"])


async def test_aktivitaet_braucht_bezug(kai):
    antwort = await kai.post("/api/activities", json={"kind": "note", "body": "ohne Bezug"})
    assert antwort.status_code == 400


async def test_ki_ohne_endpunkt_sagt_das(kai):
    """Nicht eingerichtet ist kein Serverfehler und kein Verbindungsfehler."""
    status = (await kai.get("/api/ki/status")).json()
    assert status["ready"] is False
    assert "Einstellungen" in status["hint"]

    firma_id = (await kai.post("/api/companies", json={"name": "Ohne Modell"})).json()["id"]
    antwort = await kai.post(f"/api/ki/companies/{firma_id}/zusammenfassung")
    assert antwort.status_code == 409


async def test_schluessel_kommt_nie_zurueck(kai):
    await kai.put(
        "/api/settings",
        json={"llm_base_url": "http://beispiel.test/v1", "llm_api_key": "geheim-123"},
    )
    gelesen = (await kai.get("/api/settings")).json()

    assert gelesen["llm_api_key_set"] is True
    assert "geheim-123" not in str(gelesen)

    # Leer gesendet heißt „nicht angefasst" — sonst wäre der Schlüssel nach
    # dem ersten Speichern eines anderen Feldes weg.
    await kai.put("/api/settings", json={"llm_model": "anderes", "llm_api_key": ""})
    assert (await kai.get("/api/settings")).json()["llm_api_key_set"] is True


async def test_aufgabe_erledigen_setzt_zeitpunkt(kai):
    aufgabe = (await kai.post("/api/tasks", json={"title": "Etwas tun"})).json()
    assert aufgabe["completed_at"] is None

    erledigt = (await kai.patch(f"/api/tasks/{aufgabe['id']}", json={"status": "done"})).json()
    assert erledigt["status"] == "done"
    assert erledigt["completed_at"] is not None
