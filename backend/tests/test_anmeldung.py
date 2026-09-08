"""Die eigene Anmeldung — geprüft wird, was ein Angreifer versuchen würde.

Nicht „kann man sich anmelden", sondern: Verrät die Maske, wer im Haus
arbeitet? Bleibt eine abgemeldete Sitzung wirklich tot? Kommt jemand mit
einem erfundenen Kopf herein, wenn der Eingang offen ist? Gilt ein
Einladungslink zweimal? Bremst die Bremse?

Zur Einrichtung: `olares_username` ist **global** eindeutig, und der Name
entsteht aus dem Anzeigenamen. Zwei Tests mit derselben „Marc Bayer"
teilten sich dieselbe Zeile und damit dasselbe Passwort — deshalb bekommt
jeder Test seinen eigenen Namen.
"""

import hashlib

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app import anmeldung, auth
from app.config import settings
from app.db import acquire
from app.main import app

GUT = "ein langes gutes Passwort"


def klient_fuer(name: str) -> AsyncClient:
    """Wie `conftest.klient_fuer`, nur über **https**.

    Der Sitzungskeks trägt `Secure`, sobald der Modus `eigen` läuft — über
    `http://test` würde ihn kein Browser und auch httpx nicht zurücksenden.
    Das ist kein Testtrick, sondern genau die Bedingung auf der Box.
    """
    return AsyncClient(
        transport=ASGITransport(app=app),
        base_url="https://test",
        headers={"X-Bfl-User": name},
    )


@pytest_asyncio.fixture(autouse=True, loop_scope="session")
async def _bremse_leeren(datenbank):
    """Die Bremse zählt auch je Adresse — und alle Tests kommen von
    derselben. Ohne Leeren spränge sie mitten in einem fremden Test an."""
    async with acquire() as conn:
        await conn.execute("delete from public.anmeldeversuche")
    yield
    async with acquire() as conn:
        await conn.execute("delete from public.anmeldeversuche")


def eigen_an(monkeypatch) -> None:
    """Schaltet auf den Modus mit offenem Eingang: Der Olares-Kopf zählt
    nicht mehr. Erst **nach** der Einrichtung aufrufen — die läuft noch
    über den Kopf."""
    monkeypatch.setattr(settings, "anmeldung_modus", "eigen")


async def _pinnen(conn, token: str) -> None:
    """Nennt der Verbindung den Hash — sonst versteckt die Zeilensicherheit
    die Zeile auch vor dem Test (Policies `sitzungen_token`,
    `einladungen_token` aus Migration 0026)."""
    await conn.execute(
        "select set_config('app.anmelde_token', $1, true)", anmeldung.token_hash(token)
    )


async def _sitzplatz(k, anzeigename: str):
    """Legt über die Oberfläche einen Sitzplatz an und lädt ihn ein."""
    m = (await k.post("/api/mitglieder", json={"display_name": anzeigename})).json()
    ein = (await k.post(f"/api/mitglieder/{m['id']}/einladung")).json()
    return m, ein["pfad"].rsplit("/", 1)[-1]


async def _konto(k, anzeigename: str, passwort: str = GUT):
    """Sitzplatz anlegen, einladen, Passwort setzen. Gibt Kennung und Token."""
    m, token = await _sitzplatz(k, anzeigename)
    r = await k.post(f"/api/einladung/{token}", json={"passwort": passwort})
    assert r.status_code == 200, r.text
    return m["olares_username"], token


# ── Passwörter und Hashes ────────────────────────────────────────────────


def test_vom_passwort_bleibt_nur_ein_hash():
    h = anmeldung.hash_passwort(GUT)
    assert GUT not in h and h.startswith("$argon2id$")
    assert anmeldung.passwort_stimmt(h, GUT)
    assert not anmeldung.passwort_stimmt(h, GUT + "x")
    # Zwei gleiche Passwörter ergeben verschiedene Hashes (Salz).
    assert anmeldung.hash_passwort(GUT) != h
    # Ohne hinterlegten Hash ist die Antwort falsch, nicht ein Absturz.
    assert not anmeldung.passwort_stimmt(None, GUT)


def test_vom_token_bleibt_nur_ein_hash():
    t = anmeldung.token_neu()
    assert len(t) >= 40
    assert anmeldung.token_hash(t) == hashlib.sha256(t.encode()).hexdigest()
    assert anmeldung.token_neu() != t


def test_zu_kurze_passwoerter_werden_abgewiesen():
    with pytest.raises(ValueError):
        anmeldung.passwort_pruefen("kurz")
    with pytest.raises(ValueError):
        anmeldung.passwort_pruefen("x" * 201)
    anmeldung.passwort_pruefen(GUT)


# ── Anmelden ─────────────────────────────────────────────────────────────


async def test_anmelden_setzt_einen_keks_den_javascript_nicht_sieht(datenbank):
    async with klient_fuer("anm-keks") as k:
        name, _ = await _konto(k, "Keks Traegerin")
        r = await k.post("/api/anmeldung", json={"name": name, "passwort": GUT})
        assert r.status_code == 200, r.text
        keks = r.headers["set-cookie"]
        assert "beacon_sitzung=" in keks
        assert "HttpOnly" in keks and "SameSite=lax" in keks and "Path=/" in keks
        # `Secure` hängt an der Verbindung, nicht am Modus: Der Testklient
        # spricht https, also muss es dastehen.
        assert "Secure" in keks
        assert r.json()["angemeldet"] is True
        # Vom Token steht nichts im Klartext in der Datenbank — und die
        # Zeile ist nur zu sehen, wenn die Verbindung ihren Hash nennt
        # (Policy `sitzungen_token`, Migration 0026).
        wert = keks.split("beacon_sitzung=")[1].split(";")[0]
        h = anmeldung.token_hash(wert)
        async with acquire() as conn:
            blind = await conn.fetchval("select count(*) from public.sitzungen")
            async with conn.transaction():
                await conn.execute("select set_config('app.anmelde_token', $1, true)", h)
                treffer = await conn.fetchval(
                    "select count(*) from public.sitzungen where token_hash = $1", h
                )
        assert blind == 0, "Ohne genannten Hash darf keine Sitzung sichtbar sein"
        assert treffer == 1


async def test_falsches_passwort_und_unbekannter_name_antworten_gleich(datenbank):
    async with klient_fuer("anm-gleich") as k:
        name, _ = await _konto(k, "Gleiche Antwort")
        falsch = await k.post("/api/anmeldung", json={"name": name, "passwort": "falsch aber lang"})
        fremd = await k.post("/api/anmeldung", json={"name": "gibtesnicht", "passwort": "falsch aber lang"})
        assert falsch.status_code == fremd.status_code == 401
        # Wortgleich: Die Maske ist keine Auskunft darüber, wer hier arbeitet.
        assert falsch.json()["detail"] == fremd.json()["detail"] == "Name oder Passwort stimmt nicht."


async def test_ohne_passwort_kommt_niemand_herein(datenbank):
    """Ein Sitzplatz, der nie eingeladen wurde, hat keinen Hash — und darf
    trotzdem nicht mit irgendeinem Passwort hereinkommen."""
    async with klient_fuer("anm-ohne") as k:
        m = (await k.post("/api/mitglieder", json={"display_name": "Nie Eingeladen"})).json()
        r = await k.post("/api/anmeldung", json={"name": m["olares_username"], "passwort": GUT})
        assert r.status_code == 401


async def test_nach_zehn_fehlversuchen_ist_schluss(datenbank):
    async with klient_fuer("anm-bremse") as k:
        name, _ = await _konto(k, "Gebremste Person")
        codes = [
            (await k.post("/api/anmeldung", json={"name": name, "passwort": "immer falsch hier"})).status_code
            for _ in range(11)
        ]
        assert codes[:10] == [401] * 10
        assert codes[10] == 429
        letzte = await k.post("/api/anmeldung", json={"name": name, "passwort": "immer falsch hier"})
        assert letzte.headers.get("retry-after") == "900"
        # Auch das richtige Passwort kommt jetzt nicht mehr durch.
        assert (await k.post("/api/anmeldung", json={"name": name, "passwort": GUT})).status_code == 429


async def test_gelungene_anmeldung_loescht_die_zaehlung(datenbank):
    async with klient_fuer("anm-zaehlung") as k:
        name, _ = await _konto(k, "Zaehlung Weg")
        for _ in range(3):
            await k.post("/api/anmeldung", json={"name": name, "passwort": "danebengegriffen"})
        assert (await k.post("/api/anmeldung", json={"name": name, "passwort": GUT})).status_code == 200
        async with acquire() as conn:
            offen = await conn.fetchval(
                "select count(*) from public.anmeldeversuche where kennung = $1", f"name:{name}"
            )
        assert offen == 0


# ── Sitzungen ────────────────────────────────────────────────────────────


async def test_abmelden_macht_die_sitzung_auf_dem_server_wertlos(datenbank, monkeypatch):
    async with klient_fuer("anm-abmelden") as k:
        name, _ = await _konto(k, "Abmelde Person")
        eigen_an(monkeypatch)
        assert (await k.post("/api/anmeldung", json={"name": name, "passwort": GUT})).status_code == 200
        gestohlen = k.cookies.get("beacon_sitzung")
        # Mit Sitzung geht es — der Olares-Kopf des Klienten zählt hier nicht mehr.
        assert (await k.get("/api/companies")).status_code == 200
        assert (await k.post("/api/abmeldung")).status_code == 204
        # Danach nicht mehr, auch wenn jemand den Kekswert noch hat.
        k.cookies.set("beacon_sitzung", gestohlen)
        assert (await k.get("/api/companies")).status_code == 401


async def test_abgelaufene_sitzung_gilt_nicht(datenbank, monkeypatch):
    async with klient_fuer("anm-ablauf") as k:
        name, _ = await _konto(k, "Ablauf Person")
        eigen_an(monkeypatch)
        await k.post("/api/anmeldung", json={"name": name, "passwort": GUT})
        async with acquire() as conn, conn.transaction():
            await _pinnen(conn, k.cookies.get("beacon_sitzung"))
            await conn.execute("update public.sitzungen set laeuft_ab = now() - interval '1 hour'")
        assert (await k.get("/api/companies")).status_code == 401


async def test_zu_lange_stille_beendet_die_sitzung(datenbank, monkeypatch):
    async with klient_fuer("anm-stille") as k:
        name, _ = await _konto(k, "Stille Person")
        eigen_an(monkeypatch)
        await k.post("/api/anmeldung", json={"name": name, "passwort": GUT})
        async with acquire() as conn, conn.transaction():
            await _pinnen(conn, k.cookies.get("beacon_sitzung"))
            await conn.execute("update public.sitzungen set zuletzt_am = now() - interval '30 days'")
        assert (await k.get("/api/companies")).status_code == 401


async def test_aufraeumen_nimmt_nur_das_laengst_abgelaufene(datenbank):
    async with klient_fuer("anm-aufraeumen") as k:
        name, _ = await _konto(k, "Aufraeum Person")
        await k.post("/api/anmeldung", json={"name": name, "passwort": GUT})
        keks = k.cookies.get("beacon_sitzung")
        async with acquire() as conn:
            # Eine frische Sitzung rührt die Schleife nicht an.
            assert await anmeldung.sitzungen_aufraeumen(conn) == 0
            assert await anmeldung.sitzung_lesen(conn, keks) is not None
            async with conn.transaction():
                await _pinnen(conn, keks)
                await conn.execute("update public.sitzungen set laeuft_ab = now() - interval '30 days'")
            assert await anmeldung.sitzungen_aufraeumen(conn) >= 1
            assert await anmeldung.sitzung_lesen(conn, keks) is None


# ── Der entscheidende Fall: offener Eingang ──────────────────────────────


async def test_im_modus_eigen_traegt_der_olares_kopf_nichts_mehr(datenbank, monkeypatch):
    """Der Kern der ganzen Änderung.

    Bei offenem Entrance darf `X-Bfl-User` nichts mehr bewirken — sonst
    genügte ein `curl -H 'X-Bfl-User: kaivostudio'`, um Eigentümer zu sein.
    Und er darf auch niemanden mehr **anlegen**.
    """
    eigen_an(monkeypatch)
    async with klient_fuer("erfundener-name") as k:
        assert (await k.get("/api/companies")).status_code == 401
        assert (await k.get("/api/settings")).status_code == 401
        assert (await k.get("/api/mitglieder")).status_code == 401
    async with acquire() as conn:
        angelegt = await conn.fetchval(
            "select count(*) from public.users where olares_username = $1", "erfundener-name"
        )
    assert angelegt == 0, "Ein erfundener Kopf hat einen Nutzer angelegt"


async def test_eine_sitzung_sieht_nur_die_eigene_organisation(datenbank, monkeypatch):
    """Die Anmeldung öffnet keine Tür zwischen Mandanten."""
    async with klient_fuer("anm-fremd-a") as a, klient_fuer("anm-fremd-b") as b:
        assert (await a.post("/api/companies", json={"name": "Nur fuer A"})).status_code in (200, 201)
        name, _ = await _konto(b, "Fremde Person")
        eigen_an(monkeypatch)
        assert (await b.post("/api/anmeldung", json={"name": name, "passwort": GUT})).status_code == 200
        antwort = (await b.get("/api/companies")).json()
        firmen = antwort["items"] if isinstance(antwort, dict) else antwort
        assert "Nur fuer A" not in [f["name"] for f in firmen]


# ── Erstinstallation ─────────────────────────────────────────────────────


@pytest.fixture
def eigene_ablage(tmp_path_factory, monkeypatch):
    """Ein eigener Sicherungsordner. Ohne ihn stellte sich die erste
    Organisation einer leeren Datenbank aus einem fremden Abzug wieder her
    — der Wiederanlauf funktionierte zu gut und machte den Test unsauber."""
    from app import sicherung

    monkeypatch.setattr(sicherung.settings, "app_data_dir", str(tmp_path_factory.mktemp("anm")))


async def _leerraeumen():
    """Eine Datenbank wie nach einer Installation aus dem Markt."""
    async with acquire() as conn, conn.transaction():
        await conn.execute("set local app.current_user_id = ''")
        for tab in ("sitzungen", "einladungen", "anmeldeversuche", "user_org_roles",
                    "org_settings", "orgs", "users"):
            await conn.execute(f"alter table public.{tab} disable row level security")
            await conn.execute(f"delete from public.{tab}")
            await conn.execute(f"alter table public.{tab} enable row level security")
    auth._bewohnt = False


async def test_eine_frische_installation_laesst_den_ersten_herein(datenbank, monkeypatch, eigene_ablage):
    """Der Fehler, der Marcs eigene Box unbenutzbar machte.

    Aus dem Markt installiert steht `ANMELDUNG_MODUS=eigen` von Anfang an.
    Die Datenbank ist leer: kein Nutzer, kein Passwort, keine Einladung —
    und ohne Ausnahme auch kein Weg, das zu ändern. Es gab 401 auf alles.
    """
    await _leerraeumen()
    eigen_an(monkeypatch)
    async with klient_fuer("ersterbewohner") as k:
        wer = await k.get("/api/mitglieder/wer")
        assert wer.status_code == 200, "Die Erstinstallation war eine Sackgasse"
        assert wer.json()["rolle"] == "owner"
        # Und der Bestand steht bereit, nicht nur die Kennung.
        assert (await k.get("/api/companies")).status_code == 200


async def test_mit_dem_ersten_passwort_ist_der_kopf_endgueltig_tot(datenbank, monkeypatch, eigene_ablage):
    """Die Tür schließt sich selbst — und bleibt zu."""
    await _leerraeumen()
    eigen_an(monkeypatch)
    async with klient_fuer("hausherr") as k:
        assert (await k.get("/api/companies")).status_code == 200
        await _konto(k, "Erste Person")
    # Ein frischer Klient: derselbe Kopf, aber ohne den Sitzungskeks, den
    # das Einlösen der Einladung gesetzt hat. Sobald irgendwer ein Passwort
    # hat, trägt der Kopf nichts mehr — auch nicht der des Eigentümers,
    # der eben noch hereinkam.
    async with klient_fuer("hausherr") as k:
        assert (await k.get("/api/companies")).status_code == 401
        assert (await k.get("/api/settings")).status_code == 401
    # Ein fremder Kopf legt jetzt auch niemanden mehr an.
    async with klient_fuer("spaeter-gast") as k:
        assert (await k.get("/api/companies")).status_code == 401
    async with acquire() as conn:
        assert await conn.fetchval(
            "select count(*) from public.users where olares_username = $1", "spaeter-gast"
        ) == 0


async def test_auf_einer_bewohnten_box_gilt_die_ausnahme_nie(datenbank, monkeypatch):
    """Kais Box: Dort steht ein Passwort, also greift die Ausnahme nicht —
    weder für ihn noch für einen erfundenen Namen."""
    await _leerraeumen()
    async with klient_fuer("bewohner") as k:
        await _konto(k, "Wohnt Hier")
    eigen_an(monkeypatch)
    auth._bewohnt = False  # als hätte die Anwendung gerade neu gestartet
    async with klient_fuer("bewohner") as k:
        assert (await k.get("/api/companies")).status_code == 401
    async with klient_fuer("frei-erfunden") as k:
        assert (await k.get("/api/companies")).status_code == 401


# ── Einladungen ──────────────────────────────────────────────────────────


async def test_einladung_gilt_genau_einmal(datenbank):
    async with klient_fuer("anm-einmal") as k:
        name, token = await _konto(k, "Einmal Gueltig")
        # Der Link ist mit dem ersten Einlösen tot.
        assert (await k.get(f"/api/einladung/{token}")).status_code == 404
        zweit = await k.post(f"/api/einladung/{token}", json={"passwort": "ein anderes langes"})
        assert zweit.status_code == 404
        # Das erste Passwort gilt weiter.
        assert (await k.post("/api/anmeldung", json={"name": name, "passwort": GUT})).status_code == 200


async def test_abgelaufene_einladung_gilt_nicht(datenbank):
    async with klient_fuer("anm-spaet") as k:
        _, token = await _sitzplatz(k, "Spaet Dran")
        async with acquire() as conn, conn.transaction():
            await _pinnen(conn, token)
            await conn.execute(
                "update public.einladungen set laeuft_ab = now() - interval '1 day' "
                "where token_hash = $1", anmeldung.token_hash(token),
            )
        assert (await k.get(f"/api/einladung/{token}")).status_code == 404
        assert (await k.post(f"/api/einladung/{token}", json={"passwort": GUT})).status_code == 404


async def test_eine_neue_einladung_entwertet_die_alte(datenbank):
    async with klient_fuer("anm-zweilinks") as k:
        m, alt = await _sitzplatz(k, "Zwei Links")
        neu = (await k.post(f"/api/mitglieder/{m['id']}/einladung")).json()["pfad"].rsplit("/", 1)[-1]
        assert (await k.get(f"/api/einladung/{alt}")).status_code == 404
        assert (await k.get(f"/api/einladung/{neu}")).status_code == 200


async def test_einladung_verraet_nur_den_namen(datenbank):
    async with klient_fuer("anm-auskunft") as k:
        _, token = await _sitzplatz(k, "Auskunft Knapp")
        daten = (await k.get(f"/api/einladung/{token}")).json()
        assert daten["name"] == "Auskunft Knapp"
        assert daten["kennung"] == "auskunft-knapp"
        assert daten["uebernahme"] is False
        assert set(daten) == {"name", "kennung", "uebernahme"}
        # Ein erfundener Token sagt nichts anderes als „gilt nicht".
        assert (await k.get("/api/einladung/erfunden")).status_code == 404


async def test_eine_einladung_auf_ein_konto_mit_passwort_meldet_die_uebernahme(datenbank):
    """Der Fall, der Marc fast seine eigene Box gekostet hätte.

    Wer eine Einladung für jemanden erzeugt, der schon ein Passwort hat,
    **setzt dessen Zugang zurück** — er richtet keinen ein. Für den
    Eigentümer ist das der Rettungsweg; wer den Link versehentlich bekommt,
    sperrt damit den bisherigen Inhaber aus. Die Seite muss das sagen
    können, bevor jemand ein Passwort eintippt.
    """
    async with klient_fuer("anm-uebernahme") as k:
        await _konto(k, "Hat Schon Eins")

    # Frischer Klient: Das Einlösen oben hat `k` zum Mitglied gemacht, und
    # ein Mitglied darf nicht einladen.
    async with klient_fuer("anm-uebernahme") as eigner:
        person = next(
            x for x in (await eigner.get("/api/mitglieder")).json()
            if x["olares_username"] == "hat-schon-eins"
        )
        antwort = await eigner.post(f"/api/mitglieder/{person['id']}/einladung")
        assert antwort.status_code == 201, antwort.text
        token = antwort.json()["pfad"].rsplit("/", 1)[-1]
        daten = (await eigner.get(f"/api/einladung/{token}")).json()
        assert daten["uebernahme"] is True, "Die Übernahme eines Kontos muss erkennbar sein"
        assert daten["kennung"] == "hat-schon-eins"


async def test_kurzes_passwort_wird_beim_einloesen_abgewiesen(datenbank):
    async with klient_fuer("anm-kurz") as k:
        _, token = await _sitzplatz(k, "Kurz Angebunden")
        assert (await k.post(f"/api/einladung/{token}", json={"passwort": "kurz"})).status_code == 422
        # Die Einladung ist dadurch nicht verbraucht.
        assert (await k.get(f"/api/einladung/{token}")).status_code == 200


# ── Rechte ───────────────────────────────────────────────────────────────


async def test_ein_mitglied_darf_keine_schluessel_aendern(datenbank, monkeypatch):
    async with klient_fuer("anm-rechte") as k:
        name, _ = await _konto(k, "Nur Mitglied")  # wird als 'member' angelegt
        eigen_an(monkeypatch)
        assert (await k.post("/api/anmeldung", json={"name": name, "passwort": GUT})).status_code == 200
        # Lesen darf ein Mitglied.
        assert (await k.get("/api/settings")).status_code == 200
        # Ändern nicht — und die Sicherung schon gar nicht.
        assert (await k.put("/api/settings", json={"llm_model": "x"})).status_code == 403
        assert (await k.post("/api/sicherung/wiederherstellen", json={"name": "x.json"})).status_code == 403
        assert (await k.post("/api/mitglieder", json={"display_name": "Noch Einer"})).status_code == 403


async def test_der_eigentuemer_darf_es(datenbank):
    async with klient_fuer("anm-owner") as k:
        assert (await k.put("/api/settings", json={"locale": "de"})).status_code == 200
        assert (await k.post("/api/mitglieder", json={"display_name": "Neue Person"})).status_code == 201


async def test_ein_mitglied_kann_sich_nicht_auf_den_platz_des_eigentuemers_setzen(
    datenbank, monkeypatch
):
    """Der Fund aus dem Browser — und er wäre teuer geworden.

    Der Sitzplatz war für **einen** geteilten Olares-Zugang gedacht: Er
    schreibt Arbeit der richtigen Person zu. Wer sich selbst anmeldet,
    braucht ihn nicht — und mit ihm nähme ein `member` den Platz des
    Eigentümers ein und erbte über `verwaltet` dessen Rechte. Genau das
    darf nicht gehen, sobald der Eingang offen steht.
    """
    async with klient_fuer("anm-platz") as k:
        eigner = (await k.get("/api/mitglieder/wer")).json()["user_id"]
        name, _ = await _konto(k, "Ehrgeiziges Mitglied")
        eigen_an(monkeypatch)
        assert (await k.post("/api/anmeldung", json={"name": name, "passwort": GUT})).status_code == 200

        kopf = {"X-Beacon-Sitzplatz": eigner}
        # Der Kopf wird still übergangen — nicht befolgt, aber auch nicht
        # zum Fehler gemacht: Ein altes Feld im Browser soll nichts kaputt machen.
        wer = (await k.get("/api/mitglieder/wer", headers=kopf)).json()
        assert wer["display_name"] == "Ehrgeiziges Mitglied"
        assert wer["user_id"] != eigner
        # Und die Rechte des Eigentümers kommen damit erst recht nicht mit.
        assert (await k.put("/api/settings", json={"llm_model": "x"}, headers=kopf)).status_code == 403


async def test_der_sitzplatz_nimmt_dem_eigentuemer_seine_rechte_nicht(datenbank):
    """Beim geteilten Zugang ist der Platz Zuschreibung, keine Anmeldung.

    Prüfte `verwaltet` die Rolle des Platzes, verlöre der Eigentümer den
    Zugriff auf die Einstellungen, sobald er den Platz eines Mitglieds
    einnimmt — obwohl er sich mit einem Klick zurückholen könnte. Rechte
    hängen an der angemeldeten Person.
    """
    async with klient_fuer("anm-platzrechte") as k:
        m = (await k.post("/api/mitglieder", json={"display_name": "Zugeschriebene Person"})).json()
        kopf = {"X-Beacon-Sitzplatz": m["id"]}
        # Die Arbeit wird der Person zugeschrieben …
        wer = (await k.get("/api/mitglieder/wer", headers=kopf)).json()
        assert wer["display_name"] == "Zugeschriebene Person"
        assert wer["sitzplatz_gewaehlt"] is True
        # … die Rechte bleiben aber beim Eigentümer.
        assert (await k.put("/api/settings", json={"locale": "de"}, headers=kopf)).status_code == 200


# ── Passwort ändern ──────────────────────────────────────────────────────


async def test_passwortwechsel_verlangt_das_alte_und_beendet_andere_geraete(datenbank, monkeypatch):
    neu = "noch ein langes Passwort"
    async with klient_fuer("anm-wechsel") as k, klient_fuer("anm-wechsel") as zweitgeraet:
        name, _ = await _konto(k, "Wechsel Person")
        eigen_an(monkeypatch)
        assert (await zweitgeraet.post("/api/anmeldung", json={"name": name, "passwort": GUT})).status_code == 200
        assert (await k.post("/api/anmeldung", json={"name": name, "passwort": GUT})).status_code == 200

        falsch = await k.post("/api/anmeldung/passwort", json={"alt": "stimmt nicht hier", "neu": neu})
        assert falsch.status_code == 403
        assert (await k.post("/api/anmeldung/passwort", json={"alt": GUT, "neu": neu})).status_code == 204

        # Die eigene Sitzung lebt weiter, die des anderen Geräts nicht.
        assert (await k.get("/api/companies")).status_code == 200
        assert (await zweitgeraet.get("/api/companies")).status_code == 401

        async with acquire() as conn:
            await conn.execute("delete from public.anmeldeversuche")
        assert (await k.post("/api/anmeldung", json={"name": name, "passwort": GUT})).status_code == 401
        assert (await k.post("/api/anmeldung", json={"name": name, "passwort": neu})).status_code == 200


async def test_zu_kurzes_neues_passwort_wird_abgewiesen(datenbank, monkeypatch):
    async with klient_fuer("anm-kurzneu") as k:
        name, _ = await _konto(k, "Kurz Neu")
        eigen_an(monkeypatch)
        await k.post("/api/anmeldung", json={"name": name, "passwort": GUT})
        assert (await k.post("/api/anmeldung/passwort", json={"alt": GUT, "neu": "kurz"})).status_code == 422
        # Das alte gilt weiter.
        async with acquire() as conn:
            await conn.execute("delete from public.anmeldeversuche")
        assert (await k.post("/api/anmeldung", json={"name": name, "passwort": GUT})).status_code == 200


async def test_ohne_tls_kein_secure_sonst_immer(datenbank):
    """Ein `Secure`-Keks über http wird vom Browser verworfen — das sähe
    aus wie ein kaputtes Anmelden. Über https muss er dagegen stehen,
    auch im Modus `olares`: Auf der Box läuft dort alles über TLS."""
    async with klient_fuer("anm-tls") as k:
        name, _ = await _konto(k, "Tls Person")
        ohne = await k.post(
            "/api/anmeldung",
            json={"name": name, "passwort": GUT},
            headers={"X-Forwarded-Proto": "http", "X-Forwarded-Host": "test"},
        )
        assert "Secure" not in ohne.headers["set-cookie"]
        mit = await k.post(
            "/api/anmeldung",
            json={"name": name, "passwort": GUT},
            headers={"X-Forwarded-Proto": "https", "X-Forwarded-Host": "test"},
        )
        assert "Secure" in mit.headers["set-cookie"]


async def test_lage_verraet_nichts_ohne_keks(datenbank):
    async with klient_fuer("anm-lage") as k:
        r = await k.get("/api/anmeldung/lage")
        assert r.status_code == 200
        assert r.json()["angemeldet"] is False and r.json()["name"] is None


async def test_eine_fremde_seite_darf_nicht_anmelden(datenbank):
    """`SameSite=Lax` hält das meiste ab; die Herkunftsprüfung den Rest."""
    async with klient_fuer("anm-herkunft") as k:
        name, _ = await _konto(k, "Herkunft Geprueft")
        r = await k.post(
            "/api/anmeldung",
            json={"name": name, "passwort": GUT},
            headers={"Origin": "https://boese.example.com"},
        )
        assert r.status_code == 403


async def test_die_eigene_seite_darf_es_auch_hinter_dem_proxy(datenbank):
    """Der Fall, der im Browser aufflog und in keinem Test stand.

    Der Mensch spricht mit dem Frontend, das Frontend leitet ans Backend
    weiter. Im `Host` steht deshalb der interne Dienst, nicht die Adresse,
    die im Browser stand — ein Vergleich gegen `Host` allein wies **jede
    echte Anmeldung** ab. Was der Browser sah, steht in `X-Forwarded-Host`.
    """
    async with klient_fuer("anm-proxy") as k:
        name, _ = await _konto(k, "Proxy Person")
        durch = await k.post(
            "/api/anmeldung",
            json={"name": name, "passwort": GUT},
            headers={
                "Origin": "https://41b89d100.kaivostudio.olares.de",
                "Host": "beacon-backend.beacon-kaivostudio.svc.cluster.local:8000",
                "X-Forwarded-Host": "41b89d100.kaivostudio.olares.de",
            },
        )
        assert durch.status_code == 200, durch.text
        # Ein gefälschter Weiterleitungskopf hilft einer fremden Seite nicht:
        # Ihre Herkunft passt zu keinem der beiden Ziele.
        fremd = await k.post(
            "/api/anmeldung",
            json={"name": name, "passwort": GUT},
            headers={
                "Origin": "https://boese.example",
                "X-Forwarded-Host": "41b89d100.kaivostudio.olares.de",
            },
        )
        assert fremd.status_code == 403
