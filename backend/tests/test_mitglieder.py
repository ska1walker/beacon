"""Zwei Menschen, ein Olares-Zugang.

Der Sitzplatz ist Zuschreibung, keine Anmeldung. Diese Tests halten
beides nach: dass die Zuschreibung wirkt — und dass sie **keine** Tür in
fremde Mandanten ist. Das Zweite ist der Punkt, an dem ein Fehler hier
teuer würde.
"""

from httpx import ASGITransport, AsyncClient

from app.main import app
from tests.conftest import klient_fuer


def mit_sitzplatz(login: str, sitzplatz: str) -> AsyncClient:
    return AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        headers={"X-Bfl-User": login, "X-Beacon-Sitzplatz": sitzplatz},
    )


async def test_person_ohne_olares_zugang_anlegen(datenbank):
    async with klient_fuer("team-a") as klient:
        marc = (await klient.post("/api/mitglieder", json={"display_name": "Marc Bayer"})).json()

    assert marc["zugang"] == "sitzplatz"
    assert marc["olares_username"] == "marc-bayer"
    assert marc["role"] == "member"


async def test_umlaute_werden_zur_kennung(datenbank):
    async with klient_fuer("team-umlaut") as klient:
        person = (await klient.post("/api/mitglieder", json={"display_name": "Jörg Müller"})).json()
    assert person["olares_username"] == "joerg-mueller"


async def test_dieselbe_person_nicht_zweimal(datenbank):
    async with klient_fuer("team-b") as klient:
        await klient.post("/api/mitglieder", json={"display_name": "Marc Bayer"})
        zweimal = await klient.post("/api/mitglieder", json={"display_name": "Marc Bayer"})
    assert zweimal.status_code == 409


async def test_liste_zeigt_beide_sorten(datenbank):
    async with klient_fuer("team-c") as klient:
        await klient.post("/api/mitglieder", json={"display_name": "Marc Bayer"})
        liste = (await klient.get("/api/mitglieder")).json()

    arten = {m["olares_username"]: m["zugang"] for m in liste}
    assert arten["team-c"] == "olares"
    assert arten["marc-bayer"] == "sitzplatz"


async def test_arbeit_wird_dem_sitzplatz_zugeschrieben(datenbank):
    """Der eigentliche Zweck: Marc legt an, und es gehört Marc."""
    async with klient_fuer("team-d") as kai:
        marc = (await kai.post("/api/mitglieder", json={"display_name": "Marc Bayer"})).json()
        eigene = (await kai.post("/api/companies", json={"name": "Kais Firma"})).json()

        async with mit_sitzplatz("team-d", marc["id"]) as als_marc:
            wer = (await als_marc.get("/api/mitglieder/wer")).json()
            marcs = (await als_marc.post("/api/companies", json={"name": "Marcs Firma"})).json()

    assert wer["user_id"] == marc["id"]
    assert wer["display_name"] == "Marc Bayer"
    # Der Zugang bleibt derselbe — das ist der ehrliche Teil.
    assert wer["login_username"] == "team-d"
    assert wer["sitzplatz_gewaehlt"] is True

    assert marcs["owner_id"] == marc["id"]
    assert eigene["owner_id"] != marc["id"]


async def test_beide_sehen_alles(datenbank):
    """Zwei Gesellschafter, ein Vertrieb — Besitz ist Arbeitsteilung."""
    async with klient_fuer("team-e") as kai:
        marc = (await kai.post("/api/mitglieder", json={"display_name": "Marc Bayer"})).json()
        await kai.post("/api/companies", json={"name": "Von Kai"})

        async with mit_sitzplatz("team-e", marc["id"]) as als_marc:
            await als_marc.post("/api/companies", json={"name": "Von Marc"})
            marcs_sicht = [f["name"] for f in (await als_marc.get("/api/companies")).json()]

        kais_sicht = [f["name"] for f in (await kai.get("/api/companies")).json()]

    assert {"Von Kai", "Von Marc"} <= set(kais_sicht)
    assert {"Von Kai", "Von Marc"} <= set(marcs_sicht)


async def test_protokoll_haelt_person_und_zugang_fest(datenbank):
    """Sonst sähe es aus, als hätte Marc sich selbst angemeldet."""
    from app.db import acquire_as

    async with klient_fuer("team-f") as kai:
        marc = (await kai.post("/api/mitglieder", json={"display_name": "Marc Bayer"})).json()

        async with mit_sitzplatz("team-f", marc["id"]) as als_marc:
            firma = (await als_marc.post("/api/companies", json={"name": "Protokollfirma"})).json()

        async with acquire_as(marc["id"]) as conn:
            eintrag = await conn.fetchrow(
                "select actor_id, actor_login from public.audit_log "
                "where entity = 'companies' and entity_id = $1",
                firma["id"],
            )

    assert str(eintrag["actor_id"]) == marc["id"]
    assert eintrag["actor_login"] == "team-f"


async def test_fremder_sitzplatz_wird_abgewiesen(datenbank):
    """Der Test, an dem die Sicherheit dieser Funktion hängt.

    Ein Sitzplatz greift nur innerhalb derselben Organisation. Ohne diese
    Bedingung wäre er ein Weg in fremde Mandanten und damit die Umgehung
    von allem, was die Zeilensicherheit schützt.
    """
    # Organisation eins: hat eine Person und Daten.
    async with klient_fuer("team-fremd") as fremd:
        fremde_person = (
            await fremd.post("/api/mitglieder", json={"display_name": "Fremder Kollege"})
        ).json()
        await fremd.post("/api/companies", json={"name": "Streng geheim"})

    # Organisation zwei: entsteht mit dem ersten Aufruf.
    async with klient_fuer("team-eigen") as eigen:
        await eigen.get("/api/companies")

    # Und versucht nun, sich auf den fremden Sitzplatz zu setzen.
    async with mit_sitzplatz("team-eigen", fremde_person["id"]) as versuch:
        antwort = await versuch.get("/api/companies")

    assert antwort.status_code == 403
    assert "nicht zu Ihrer Organisation" in antwort.json()["detail"]


async def test_unsinniger_sitzplatz_wird_abgewiesen(datenbank):
    async with klient_fuer("team-i") as klient:
        await klient.get("/api/companies")

    async with mit_sitzplatz("team-i", "kein-uuid") as versuch:
        antwort = await versuch.get("/api/companies")
    assert antwort.status_code == 400


async def test_eigener_zugang_wird_nicht_entfernt(datenbank):
    async with klient_fuer("team-j") as klient:
        wer = (await klient.get("/api/mitglieder/wer")).json()
        antwort = await klient.delete(f"/api/mitglieder/{wer['user_id']}")
    assert antwort.status_code == 400


async def test_sitzplatz_entfernen_laesst_besitz_stehen(datenbank):
    """Besitz umzuschreiben wäre eine Geschichtsfälschung."""
    async with klient_fuer("team-k") as kai:
        marc = (await kai.post("/api/mitglieder", json={"display_name": "Marc Bayer"})).json()
        async with mit_sitzplatz("team-k", marc["id"]) as als_marc:
            firma = (await als_marc.post("/api/companies", json={"name": "Marcs Erbe"})).json()

        weg = await kai.delete(f"/api/mitglieder/{marc['id']}")
        assert weg.status_code == 204

        nachher = (await kai.get(f"/api/companies/{firma['id']}")).json()
        assert nachher["owner_id"] == marc["id"]

        # Und der Sitzplatz greift nicht mehr.
        async with mit_sitzplatz("team-k", marc["id"]) as nicht_mehr:
            assert (await nicht_mehr.get("/api/companies")).status_code == 403


async def test_boxinhaber_bekommt_einen_namen(datenbank):
    """Der Olares-Zugang bringt nur die Kennung mit. Der Name kommt von Hand."""
    async with klient_fuer("team-name") as klient:
        wer = (await klient.get("/api/mitglieder/wer")).json()
        assert wer["display_name"] == "team-name"

        neu = (
            await klient.patch(f"/api/mitglieder/{wer['user_id']}", json={"display_name": "  Kai Böhm "})
        ).json()
        assert neu["display_name"] == "Kai Böhm"
        assert neu["olares_username"] == "team-name"  # die Kennung bleibt
        assert neu["zugang"] == "olares"

        # Die Liste und „wer" zeigen den Namen; ein weiterer Aufruf setzt ihn nicht zurück.
        liste = (await klient.get("/api/mitglieder")).json()
        assert [m["display_name"] for m in liste if m["id"] == wer["user_id"]] == ["Kai Böhm"]
        assert (await klient.get("/api/mitglieder/wer")).json()["display_name"] == "Kai Böhm"

        leer = await klient.patch(f"/api/mitglieder/{wer['user_id']}", json={})
        assert leer.status_code == 400
        kurz = await klient.patch(f"/api/mitglieder/{wer['user_id']}", json={"display_name": "K"})
        assert kurz.status_code == 422


async def test_fremde_person_bleibt_unbenannt(datenbank):
    """Der Name einer Person aus einer anderen Organisation ist nicht erreichbar."""
    async with klient_fuer("team-x") as x, klient_fuer("team-y") as y:
        marc = (await x.post("/api/mitglieder", json={"display_name": "Marc Bayer"})).json()
        antwort = await y.patch(f"/api/mitglieder/{marc['id']}", json={"display_name": "Jemand"})
        assert antwort.status_code == 404
        liste = (await x.get("/api/mitglieder")).json()
        assert [m["display_name"] for m in liste if m["id"] == marc["id"]] == ["Marc Bayer"]
