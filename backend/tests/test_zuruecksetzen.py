"""Der Weg zurück, wenn das Passwort weg ist.

Die Hürde ist nicht ein Postfach und nicht eine Frage nach dem
Mädchennamen der Mutter, sondern der **Zugang zur Box**: Der Code steht
in einer Datei unter `/app/data`. Geprüft wird deshalb vor allem, dass
über das Netz nichts davon zu erfahren ist — weder der Code noch, welche
Zugänge es überhaupt gibt.
"""

import pathlib
import time

import pytest

from app import anmeldung as kern
from app import zuruecksetzen
from app.config import settings
from app.db import acquire
from tests.conftest import klient_fuer


def _datei() -> pathlib.Path:
    return pathlib.Path(settings.app_data_dir) / zuruecksetzen.DATEI


def _code_aus_der_datei() -> str:
    for zeile in _datei().read_text(encoding="utf-8").splitlines():
        if zeile.startswith("Code:"):
            return zeile.split(":", 1)[1].strip()
    raise AssertionError("kein Code in der Datei")


async def _zugang_mit_passwort(name: str, passwort: str) -> None:
    """Legt den Nutzer an (erster Aufruf) und setzt sein Passwort."""
    async with klient_fuer(name) as k:
        assert (await k.get("/api/mitglieder/wer")).status_code == 200
        antwort = await k.post("/api/anmeldung/passwort", json={"alt": "x", "neu": passwort})
        assert antwort.status_code == 204, antwort.text


@pytest.fixture(autouse=True)
def keine_alte_datei():
    _datei().unlink(missing_ok=True)
    yield
    _datei().unlink(missing_ok=True)


async def test_der_code_steht_in_der_datei_und_nie_in_der_antwort(datenbank):
    await _zugang_mit_passwort("zur-eins", "ein-langes-passwort-1")
    async with klient_fuer("zur-eins") as k:
        antwort = await k.post("/api/anmeldung/vergessen", json={"name": "zur-eins"})
    assert antwort.status_code == 200
    code = _code_aus_der_datei()
    assert code not in antwort.text
    # Die Antwort sagt nur, wo zu schauen ist.
    assert zuruecksetzen.DATEI in antwort.json()["pfad"]
    assert antwort.json()["minuten"] == zuruecksetzen.GUELTIG_MINUTEN


async def test_die_datei_ist_nur_fuer_den_eigentuemer_lesbar(datenbank):
    await _zugang_mit_passwort("zur-rechte", "ein-langes-passwort-2")
    async with klient_fuer("zur-rechte") as k:
        await k.post("/api/anmeldung/vergessen", json={"name": "zur-rechte"})
    assert oct(_datei().stat().st_mode)[-3:] == "600"


async def test_ein_unbekannter_name_antwortet_gleich_und_schreibt_nichts(datenbank):
    """Sonst wäre dieser Endpunkt das Namensverzeichnis der Box."""
    await _zugang_mit_passwort("zur-echt", "ein-langes-passwort-3")
    async with klient_fuer("zur-echt") as k:
        echt = await k.post("/api/anmeldung/vergessen", json={"name": "zur-echt"})
        _datei().unlink(missing_ok=True)
        erfunden = await k.post("/api/anmeldung/vergessen", json={"name": "gibt-es-nicht-xyz"})
    assert echt.status_code == erfunden.status_code == 200
    assert echt.json() == erfunden.json()
    assert not _datei().exists()


async def test_mit_dem_code_gelingt_ein_neues_passwort(datenbank):
    await _zugang_mit_passwort("zur-neu", "ein-langes-passwort-4")
    async with klient_fuer("zur-neu") as k:
        await k.post("/api/anmeldung/vergessen", json={"name": "zur-neu"})
        code = _code_aus_der_datei()
        antwort = await k.post(
            "/api/anmeldung/zuruecksetzen",
            json={"name": "zur-neu", "code": code, "passwort": "ein-ganz-neues-passwort"},
        )
    assert antwort.status_code == 200, antwort.text
    assert antwort.json()["angemeldet"] is True
    # Eingelöst heißt weg: Ein zweites Mal geht derselbe Code nicht.
    assert not _datei().exists()

    async with klient_fuer("zur-neu") as k:
        alt = await k.post("/api/anmeldung", json={"name": "zur-neu", "passwort": "ein-langes-passwort-4"})
        neu = await k.post("/api/anmeldung", json={"name": "zur-neu", "passwort": "ein-ganz-neues-passwort"})
    assert alt.status_code == 401
    assert neu.status_code == 200


async def test_der_code_gilt_nur_fuer_seinen_zugang(datenbank):
    await _zugang_mit_passwort("zur-a", "ein-langes-passwort-5")
    await _zugang_mit_passwort("zur-b", "ein-langes-passwort-6")
    async with klient_fuer("zur-a") as k:
        await k.post("/api/anmeldung/vergessen", json={"name": "zur-a"})
        code = _code_aus_der_datei()
        fremd = await k.post(
            "/api/anmeldung/zuruecksetzen",
            json={"name": "zur-b", "code": code, "passwort": "fremdes-neues-passwort"},
        )
    assert fremd.status_code == 403


async def test_ein_falscher_code_wird_abgewiesen(datenbank):
    await _zugang_mit_passwort("zur-falsch", "ein-langes-passwort-7")
    async with klient_fuer("zur-falsch") as k:
        await k.post("/api/anmeldung/vergessen", json={"name": "zur-falsch"})
        antwort = await k.post(
            "/api/anmeldung/zuruecksetzen",
            json={"name": "zur-falsch", "code": "AAAA-BBBB-CCCC", "passwort": "irgendein-passwort"},
        )
    assert antwort.status_code == 403
    # Die Datei bleibt: Ein Vertipper darf den echten Code nicht entwerten.
    assert _datei().exists()


async def test_ohne_datei_geht_gar_nichts(datenbank):
    await _zugang_mit_passwort("zur-ohne", "ein-langes-passwort-8")
    async with klient_fuer("zur-ohne") as k:
        antwort = await k.post(
            "/api/anmeldung/zuruecksetzen",
            json={"name": "zur-ohne", "code": "AAAA-BBBB-CCCC", "passwort": "irgendein-passwort"},
        )
    assert antwort.status_code == 403


async def test_ein_abgelaufener_code_gilt_nicht_mehr(datenbank, monkeypatch):
    """Maßgeblich ist, wann die Datei geschrieben wurde — nicht, was in ihr steht."""
    await _zugang_mit_passwort("zur-alt", "ein-langes-passwort-9")
    async with klient_fuer("zur-alt") as k:
        await k.post("/api/anmeldung/vergessen", json={"name": "zur-alt"})
        code = _code_aus_der_datei()
        alt = time.time() - (zuruecksetzen.GUELTIG_MINUTEN + 1) * 60
        import os
        os.utime(_datei(), (alt, alt))
        antwort = await k.post(
            "/api/anmeldung/zuruecksetzen",
            json={"name": "zur-alt", "code": code, "passwort": "zu-spaet-passwort"},
        )
    assert antwort.status_code == 403


async def test_zuruecksetzen_beendet_alle_offenen_sitzungen(datenbank):
    """Wer zurücksetzt, tut es oft, weil etwas nicht stimmt."""
    await _zugang_mit_passwort("zur-sitz", "ein-langes-passwort-10")
    async with klient_fuer("zur-sitz") as k:
        angemeldet = await k.post("/api/anmeldung", json={"name": "zur-sitz", "passwort": "ein-langes-passwort-10"})
        assert angemeldet.status_code == 200
        alter_keks = k.cookies.get(kern.KEKS)

        await k.post("/api/anmeldung/vergessen", json={"name": "zur-sitz"})
        code = _code_aus_der_datei()
        await k.post(
            "/api/anmeldung/zuruecksetzen",
            json={"name": "zur-sitz", "code": code, "passwort": "wieder-ein-neues-passwort"},
        )

    async with acquire() as conn:
        offen = await conn.fetchval(
            "select count(*) from public.sitzungen where token_hash = $1 and beendet_am is null",
            kern.token_hash(alter_keks),
        )
    assert offen == 0


async def test_ein_zu_kurzes_passwort_wird_abgelehnt(datenbank):
    await _zugang_mit_passwort("zur-kurz", "ein-langes-passwort-11")
    async with klient_fuer("zur-kurz") as k:
        await k.post("/api/anmeldung/vergessen", json={"name": "zur-kurz"})
        code = _code_aus_der_datei()
        antwort = await k.post(
            "/api/anmeldung/zuruecksetzen",
            json={"name": "zur-kurz", "code": code, "passwort": "kurz"},
        )
    assert antwort.status_code == 422


def test_ein_neuer_code_ueberschreibt_den_alten():
    """Sonst sammelten sich Codes an, von denen jeder gültig bliebe."""
    erster = zuruecksetzen.anfordern("jemand")
    zweiter = zuruecksetzen.anfordern("jemand")
    assert erster != zweiter
    assert zuruecksetzen.stimmt("jemand", zweiter)
    assert not zuruecksetzen.stimmt("jemand", erster)


def test_der_code_ist_gegen_gross_klein_und_striche_gutmuetig():
    """Er wird abgetippt. Ein Bindestrich zu wenig darf nicht scheitern."""
    code = zuruecksetzen.anfordern("jemand")
    assert zuruecksetzen.stimmt("JEMAND", code.replace("-", "").lower())


def test_leerzeichen_statt_bindestriche_gehen_auch():
    """Abgetippt wird selten genau so, wie es dasteht."""
    code = zuruecksetzen.anfordern("jemand")
    assert zuruecksetzen.stimmt("jemand", code.replace("-", " ").lower())
    assert zuruecksetzen.stimmt("jemand", f"  {code}  ")
