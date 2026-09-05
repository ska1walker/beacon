"""Der öffentliche Pfad — ohne Anmeldung, also ohne Fehlertoleranz.

Drei Regeln, jede an einem Fall erkennbar: Ein Abmeldelink funktioniert
immer. Ein Bestätigungslink gilt einmal. Ein Klick leitet weiter, auch
wenn das Zählen scheitert. Und die Selbstauskunft-Policy gibt genau eine
Zeile frei — sonst wäre dieser Pfad ein Datenleck mit Token.
"""

from httpx import ASGITransport, AsyncClient

from app import links
from app.db import acquire, acquire_als_link, acquire_as
from app.oeffentlich import app as oeffentlich
from tests.conftest import klient_fuer


async def nutzer_id(klient):
    """Die Nutzer-ID hinter dem Kopf X-Bfl-User — der Eigner der Organisation."""
    async with acquire() as conn:
        return await conn.fetchval(
            "select id from public.users where olares_username = $1",
            klient.headers["X-Bfl-User"],
        )


async def _draussen():
    """Ein Aufrufer ohne jede Identität — der Empfänger einer Mail."""
    return AsyncClient(transport=ASGITransport(app=oeffentlich), base_url="http://links.test")


async def _kontakt_und_link(klient, art, **extra):
    from uuid import uuid4

    # Eine Adresse je Aufruf: Die E-Mail ist je Organisation eindeutig, und
    # ein Test, der denselben Kontakt zweimal anlegt, bekäme 409.
    antwort = await klient.post("/api/contacts", json={
        "first_name": "Ann", "last_name": "Peters",
        "email": f"peters-{uuid4().hex[:8]}@fremd.de",
    })
    assert antwort.status_code == 201, antwort.text
    k = antwort.json()
    # Der Link entsteht im Kontext der Organisation — wie später aus dem Versand.
    async with acquire_as(await nutzer_id(klient)) as conn:
        org = await conn.fetchval("select org_id from public.contacts where id = $1", k["id"])
        token = await links.anlegen(conn, org, art, contact_id=k["id"], **extra)
    return k, token


async def test_bestaetigen_setzt_einwilligung_mit_nachweis(datenbank):
    async with klient_fuer("oeff-doi") as klient:
        k, token = await _kontakt_und_link(klient, "bestaetigen")
        async with await _draussen() as d:
            antwort = await d.get(f"/o/bestaetigen/{token}",
                                  headers={"user-agent": "Mailprogramm/1.0"})
        assert antwort.status_code == 200
        assert "bestätigt" in antwort.text

        kontakt = (await klient.get(f"/api/contacts/{k['id']}")).json()
        assert kontakt["marketing_einwilligung"] == "bestaetigt"
        assert kontakt["einwilligung_am"]
        beleg = kontakt["einwilligung_nachweis"]
        assert beleg["programm"] == "Mailprogramm/1.0"
        assert beleg["zeitpunkt"]
        # Das Token steht nur angerissen im Beleg — der Beleg ist kein zweiter Link.
        assert token not in str(beleg)


async def test_bestaetigen_gilt_einmal(datenbank):
    async with klient_fuer("oeff-einmal") as klient:
        _, token = await _kontakt_und_link(klient, "bestaetigen")
        async with await _draussen() as d:
            erste = await d.get(f"/o/bestaetigen/{token}")
            zweite = await d.get(f"/o/bestaetigen/{token}")
        assert erste.status_code == 200
        assert zweite.status_code == 200
        assert "bereits" in zweite.text


async def test_abmelden_funktioniert_immer(datenbank):
    """Nie „abgelaufen“, nie „schon benutzt“. Eine verweigerte Abmeldung
    ist ein Rechtsverstoß — wegen eines Tokens, das der Empfänger nicht
    gewählt hat."""
    async with klient_fuer("oeff-abmelden") as klient:
        k, token = await _kontakt_und_link(klient, "abmelden")
        async with await _draussen() as d:
            for _ in range(3):
                antwort = await d.get(f"/o/abmelden/{token}")
                assert antwort.status_code == 200
                assert "keine weiteren" in antwort.text

        kontakt = (await klient.get(f"/api/contacts/{k['id']}")).json()
        assert kontakt["marketing_einwilligung"] == "abgemeldet"
        assert kontakt["abgemeldet_am"]


async def test_abmelden_schlaegt_bestaetigen(datenbank):
    """Wer sich abmeldet und danach einen alten Bestätigungslink klickt,
    ist wieder eingewilligt — das ist die bewusste Handlung, die zählt."""
    async with klient_fuer("oeff-reihenfolge") as klient:
        k, ab = await _kontakt_und_link(klient, "abmelden")
        async with acquire_as(await nutzer_id(klient)) as conn:
            org = await conn.fetchval("select org_id from public.contacts where id = $1", k["id"])
            doi = await links.anlegen(conn, org, "bestaetigen", contact_id=k["id"])
        async with await _draussen() as d:
            await d.get(f"/o/abmelden/{ab}")
            await d.get(f"/o/bestaetigen/{doi}")
        kontakt = (await klient.get(f"/api/contacts/{k['id']}")).json()
        assert kontakt["marketing_einwilligung"] == "bestaetigt"
        assert kontakt["abgemeldet_am"] is None


async def test_klick_zaehlt_und_leitet_weiter(datenbank):
    async with klient_fuer("oeff-klick") as klient:
        k, token = await _kontakt_und_link(klient, "klick", ziel_url="https://aimighty.de/angebot")
        async with await _draussen() as d:
            antwort = await d.get(f"/o/k/{token}", follow_redirects=False)
        assert antwort.status_code == 302
        assert antwort.headers["location"] == "https://aimighty.de/angebot"

        async with acquire_as(await nutzer_id(klient)) as conn:
            z = await conn.fetchrow(
                "select benutzt_anzahl, benutzt_am from public.oeffentliche_links where token = $1",
                token,
            )
        assert z["benutzt_anzahl"] == 1 and z["benutzt_am"]


async def test_unbekanntes_token_sagt_nichts_verraeterisches(datenbank):
    async with await _draussen() as d:
        for pfad in ("/o/bestaetigen/gibtsnicht", "/o/abmelden/gibtsnicht", "/o/k/gibtsnicht"):
            antwort = await d.get(pfad, follow_redirects=False)
            assert antwort.status_code == 404
            assert "nicht mehr gültig" in antwort.text


async def test_falsche_art_wird_nicht_eingeloest(datenbank):
    """Ein Abmelde-Token darf nichts bestätigen und umgekehrt."""
    async with klient_fuer("oeff-art") as klient:
        k, token = await _kontakt_und_link(klient, "abmelden")
        async with await _draussen() as d:
            assert (await d.get(f"/o/bestaetigen/{token}")).status_code == 404
        kontakt = (await klient.get(f"/api/contacts/{k['id']}")).json()
        assert kontakt["marketing_einwilligung"] == "keine"


async def test_selbstauskunft_gibt_genau_eine_zeile_frei(datenbank):
    """Die Policy ist die einzige Sicherung dieses Pfades."""
    async with klient_fuer("oeff-policy") as klient:
        _, a = await _kontakt_und_link(klient, "abmelden")
        _, b = await _kontakt_und_link(klient, "abmelden")
    async with acquire_als_link(a) as conn:
        sichtbar = await conn.fetch("select token from public.oeffentliche_links")
        assert [z["token"] for z in sichtbar] == [a]
        # Schreiben geht über diese Verbindung nicht.
        import asyncpg
        try:
            await conn.execute("update public.oeffentliche_links set benutzt_anzahl = 99")
            geaendert = await conn.fetchval(
                "select benutzt_anzahl from public.oeffentliche_links where token = $1", a
            )
            assert geaendert != 99
        except asyncpg.PostgresError:
            pass
    assert b != a
