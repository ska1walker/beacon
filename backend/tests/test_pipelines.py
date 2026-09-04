"""Pipelines und Stufen — anlegen, ändern, löschen, mehrere nebeneinander."""

from tests.conftest import klient_fuer


async def _pipelines(k):
    return (await k.get("/api/pipelines")).json()


async def test_zweite_pipeline_mit_eigenen_stufen(datenbank):
    async with klient_fuer("pl-a") as k:
        neu = (await k.post("/api/pipelines", json={
            "name": "Bestandskunden",
            "stages": [{"name": "Anfrage", "probability": 0.3}, {"name": "Erweitert", "kind": "won", "probability": 1}],
        })).json()
        alle = await _pipelines(k)
    assert len(alle) == 2
    bestand = next(p for p in alle if p["id"] == neu["id"])
    assert [s["name"] for s in bestand["stages"]] == ["Anfrage", "Erweitert"]
    assert bestand["is_default"] is False, "die erste bleibt Standard"
    assert sum(p["is_default"] for p in alle) == 1


async def test_ohne_stufen_kommen_die_standardstufen(datenbank):
    async with klient_fuer("pl-b") as k:
        neu = (await k.post("/api/pipelines", json={"name": "Leer angelegt"})).json()
        pl = next(p for p in await _pipelines(k) if p["id"] == neu["id"])
    assert len(pl["stages"]) >= 3
    assert {s["kind"] for s in pl["stages"]} == {"open", "won", "lost"}


async def test_genau_eine_standardpipeline(datenbank):
    async with klient_fuer("pl-c") as k:
        neu = (await k.post("/api/pipelines", json={"name": "Zweite"})).json()
        await k.patch(f"/api/pipelines/{neu['id']}", json={"is_default": True})
        alle = await _pipelines(k)
        assert [p["is_default"] for p in alle].count(True) == 1
        assert next(p for p in alle if p["is_default"])["name"] == "Zweite"
        # Standard abschalten ohne Ersatz geht nicht
        assert (await k.patch(f"/api/pipelines/{neu['id']}", json={"is_default": False})).status_code == 400
        # Neue Geschäfte landen in der Standard-Pipeline
        deal = (await k.post("/api/deals", json={"name": "Neu"})).json()
    assert deal["pipeline_id"] == neu["id"]


async def test_board_je_pipeline(datenbank):
    async with klient_fuer("pl-d") as k:
        erste = (await _pipelines(k))[0]
        zweite = (await k.post("/api/pipelines", json={"name": "Zweite"})).json()
        await k.post("/api/deals", json={"name": "In der ersten", "pipeline_id": erste["id"]})
        await k.post("/api/deals", json={"name": "In der zweiten", "pipeline_id": zweite["id"]})
        b1 = (await k.get(f"/api/board?pipeline_id={erste['id']}")).json()
        b2 = (await k.get(f"/api/board?pipeline_id={zweite['id']}")).json()
    namen = lambda b: [d["name"] for c in b["columns"] for d in c["deals"]]  # noqa: E731
    assert namen(b1) == ["In der ersten"]
    assert namen(b2) == ["In der zweiten"]


async def test_pipeline_mit_geschaeften_bleibt(datenbank):
    async with klient_fuer("pl-e") as k:
        zweite = (await k.post("/api/pipelines", json={"name": "Zweite"})).json()
        await k.post("/api/deals", json={"name": "Liegt hier", "pipeline_id": zweite["id"]})
        antwort = await k.delete(f"/api/pipelines/{zweite['id']}")
    assert antwort.status_code == 409
    assert "1 Lead." in antwort.json()["detail"]


async def test_letzte_pipeline_bleibt(datenbank):
    async with klient_fuer("pl-f") as k:
        einzige = (await _pipelines(k))[0]
        assert (await k.delete(f"/api/pipelines/{einzige['id']}")).status_code == 409


async def test_standard_loeschen_gibt_den_standard_weiter(datenbank):
    async with klient_fuer("pl-g") as k:
        erste = (await _pipelines(k))[0]
        zweite = (await k.post("/api/pipelines", json={"name": "Zweite"})).json()
        # Die erste hat noch kein Geschäft und ist Standard
        assert (await k.delete(f"/api/pipelines/{erste['id']}")).status_code == 204
        alle = await _pipelines(k)
    assert [p["id"] for p in alle] == [zweite["id"]]
    assert alle[0]["is_default"] is True


async def test_stufe_anlegen_landet_vor_dem_abschluss(datenbank):
    async with klient_fuer("pl-h") as k:
        pl = (await _pipelines(k))[0]
        await k.post(f"/api/pipelines/{pl['id']}/stages", json={"name": "Vorführung 2", "probability": 0.5})
        stufen = next(p for p in await _pipelines(k) if p["id"] == pl["id"])["stages"]
    namen = [s["name"] for s in stufen]
    assert namen.index("Vorführung 2") < namen.index("Gewonnen")
    assert [s["position"] for s in stufen] == list(range(len(stufen)))


async def test_stufe_umbenennen_und_gewichten(datenbank):
    async with klient_fuer("pl-i") as k:
        pl = (await _pipelines(k))[0]
        angebot = next(s for s in pl["stages"] if s["name"] == "Angebot")
        await k.patch(f"/api/pipelines/stages/{angebot['id']}", json={"name": "Angebot raus", "probability": 0.65})
        stufe = next(s for s in (await _pipelines(k))[0]["stages"] if s["id"] == angebot["id"])
    assert stufe["name"] == "Angebot raus"
    assert abs(stufe["probability"] - 0.65) < 1e-9


async def test_art_mit_geschaeften_ist_fest(datenbank):
    """Die Art entscheidet über offen/abgeschlossen — rückwirkend ändert
    sich sonst die Prognose."""
    async with klient_fuer("pl-j") as k:
        pl = (await _pipelines(k))[0]
        erste = pl["stages"][0]
        await k.post("/api/deals", json={"name": "Liegt auf Erstkontakt"})
        antwort = await k.patch(f"/api/pipelines/stages/{erste['id']}", json={"kind": "won"})
    assert antwort.status_code == 409


async def test_reihenfolge(datenbank):
    async with klient_fuer("pl-k") as k:
        pl = (await _pipelines(k))[0]
        ids = [s["id"] for s in pl["stages"]]
        gedreht = list(reversed(ids))
        assert (await k.put(f"/api/pipelines/{pl['id']}/stages/reihenfolge", json={"stage_ids": gedreht})).status_code == 200
        neu = [s["id"] for s in (await _pipelines(k))[0]["stages"]]
        assert neu == gedreht
        # unvollständig wird abgelehnt
        assert (await k.put(f"/api/pipelines/{pl['id']}/stages/reihenfolge", json={"stage_ids": ids[:2]})).status_code == 400


async def test_stufe_loeschen_verschiebt_geschaefte_mit_verlauf(datenbank):
    async with klient_fuer("pl-l") as k:
        pl = (await _pipelines(k))[0]
        erst, quali = pl["stages"][0], pl["stages"][1]
        deal = (await k.post("/api/deals", json={"name": "Wandert"})).json()
        assert deal["stage_id"] == erst["id"]

        ohne_ziel = await k.post(f"/api/pipelines/stages/{erst['id']}/loeschen", json={})
        assert ohne_ziel.status_code == 409

        mit_ziel = await k.post(f"/api/pipelines/stages/{erst['id']}/loeschen", json={"ziel_stage_id": quali["id"]})
        assert mit_ziel.status_code == 204

        danach = (await k.get(f"/api/deals/{deal['id']}")).json()
        verlauf = (await k.get(f"/api/activities?deal_id={deal['id']}")).json()
    assert danach["stage_id"] == quali["id"]
    assert any("Stufe gelöscht" in (a["subject"] or "") for a in verlauf)


async def test_letzte_stufe_bleibt(datenbank):
    async with klient_fuer("pl-m") as k:
        zweite = (await k.post("/api/pipelines", json={"name": "Z", "stages": [{"name": "Einzige"}]})).json()
        stufe = next(p for p in await _pipelines(k) if p["id"] == zweite["id"])["stages"][0]
        assert (await k.post(f"/api/pipelines/stages/{stufe['id']}/loeschen", json={})).status_code == 409


async def test_fremde_pipeline_unerreichbar(datenbank):
    async with klient_fuer("pl-n") as a, klient_fuer("pl-o") as b:
        pl = (await _pipelines(a))[0]
        assert (await b.patch(f"/api/pipelines/{pl['id']}", json={"name": "Hack"})).status_code == 404
        assert (await b.post(f"/api/pipelines/{pl['id']}/stages", json={"name": "Hack"})).status_code == 404
