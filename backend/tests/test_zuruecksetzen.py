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
    assert zuruecksetzen.DATEI in antwort.json()["ordner"]
    assert antwort.json()["minuten"] == zuruecksetzen.GUELTIG_MINUTEN


async def test_die_datei_ist_nur_fuer_den_eigentuemer_lesbar(datenbank):
    await _zugang_mit_passwort("zur-rechte", "ein-langes-passwort-2")
    async with klient_fuer("zur-rechte") as k:
        await k.post("/api/anmeldung/vergessen", json={"name": "zur-rechte"})
    assert oct(_datei().stat().st_mode)[-3:] == "600"


async def test_ein_unbekannter_name_antwortet_gleich_und_gibt_keinen_code(datenbank):
    """Über das Netz ist nicht zu erfahren, ob es den Namen gibt."""
    await _zugang_mit_passwort("zur-echt", "ein-langes-passwort-3")
    async with klient_fuer("zur-echt") as k:
        echt = await k.post("/api/anmeldung/vergessen", json={"name": "zur-echt"})
        erfunden = await k.post("/api/anmeldung/vergessen", json={"name": "gibt-es-nicht-xyz"})
    assert echt.status_code == erfunden.status_code == 200
    assert echt.json() == erfunden.json()
    # Die Datei liegt trotzdem — aber ohne Code.
    text = _datei().read_text(encoding="utf-8")
    assert "Code:" not in text
    assert "gibt-es-nicht-xyz" in text


async def test_bei_falschem_namen_nennt_die_datei_die_zugaenge(datenbank):
    """Auf einer fremden Box weiß der Mensch oft nicht, wie sein Zugang heißt.

    Die Seite darf es nicht sagen, sie ist öffentlich. Die Datei darf es:
    Wer sie öffnen kann, kommt ohnehin an alles auf dieser Box.
    """
    await _zugang_mit_passwort("zur-liste-a", "ein-langes-passwort-12")
    await _zugang_mit_passwort("zur-liste-b", "ein-langes-passwort-13")
    async with klient_fuer("zur-liste-a") as k:
        antwort = await k.post("/api/anmeldung/vergessen", json={"name": "keine-ahnung"})
    assert antwort.status_code == 200
    text = _datei().read_text(encoding="utf-8")
    assert "zur-liste-a" in text
    assert "zur-liste-b" in text
    # Und die Antwort an den Browser verrät davon nichts.
    assert "zur-liste-a" not in antwort.text


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
    erster = zuruecksetzen.anfordern("jemand", ["jemand"], bekannt=True)
    zweiter = zuruecksetzen.anfordern("jemand", ["jemand"], bekannt=True)
    assert erster != zweiter
    assert zuruecksetzen.stimmt("jemand", zweiter)
    assert not zuruecksetzen.stimmt("jemand", erster)


def test_der_code_ist_gegen_gross_klein_und_striche_gutmuetig():
    """Er wird abgetippt. Ein Bindestrich zu wenig darf nicht scheitern."""
    code = zuruecksetzen.anfordern("jemand", ["jemand"], bekannt=True)
    assert zuruecksetzen.stimmt("JEMAND", code.replace("-", "").lower())


def test_leerzeichen_statt_bindestriche_gehen_auch():
    """Abgetippt wird selten genau so, wie es dasteht."""
    code = zuruecksetzen.anfordern("jemand", ["jemand"], bekannt=True)
    assert zuruecksetzen.stimmt("jemand", code.replace("-", " ").lower())
    assert zuruecksetzen.stimmt("jemand", f"  {code}  ")


def test_der_ort_ist_der_klickweg_in_der_dateien_app():
    """`/app/data` gibt es in der Dateien-App nicht — dort heißt es Data › beacon."""
    ort = zuruecksetzen.wo_liegt_die_datei()
    assert ort == f"Data › beacon › {zuruecksetzen.DATEI}"
    assert "/app/data" not in ort
    # Für die Kommandozeile bleibt der Pfad im Container erreichbar.
    assert zuruecksetzen.wo_liegt_die_datei_im_container().endswith(zuruecksetzen.DATEI)


def test_ohne_ein_einziges_passwort_erklaert_die_datei_den_anderen_weg():
    """Eine frische Box lässt die Olares-Sitzung noch durch — das gehört gesagt."""
    assert zuruecksetzen.anfordern("wer-auch-immer", [], bekannt=False) is None
    text = _datei().read_text(encoding="utf-8")
    assert "noch niemand ein Passwort gesetzt" in text
    assert "Einstellungen" in text


def test_die_datei_nennt_keine_absolute_uhrzeit():
    """Der Container läuft auf UTC, die Box steht in Deutschland.

    „Gültig bis 11:09" las sich um 13:20 wie längst abgelaufen, obwohl der
    Code frisch war. Maßgeblich ist ohnehin die Schreibzeit der Datei.
    """
    zuruecksetzen.anfordern("jemand", ["jemand"], bekannt=True)
    text = _datei().read_text(encoding="utf-8")
    assert "Gültig bis" not in text
    assert "UTC" not in text
    assert f"Gültig {zuruecksetzen.GUELTIG_MINUTEN} Minuten" in text


def test_zugaenge_ohne_organisation_bekommen_keine_sackgasse():
    """Passwörter da, aber keiner gehört zu einer Organisation.

    Dann kommt niemand mehr herein — auch nicht über die Olares-Sitzung,
    denn die Tür gilt als geschlossen, sobald irgendwo ein Passwort steht.
    „Öffnen Sie Beacon einfach von der Olares-Oberfläche" wäre hier ein
    Wegweiser in eine Sackgasse.
    """
    assert zuruecksetzen.anfordern(
        "wer-auch-immer", [], bekannt=False, passwoerter_ueberhaupt=True
    ) is None
    text = _datei().read_text(encoding="utf-8")
    assert "keiner davon" in text
    assert "an der Box selbst" in text
    assert "Olares-Oberfläche dieser Box aus, dann sind Sie drin" not in text


async def test_wer_aus_der_organisation_genommen_wurde_steht_nicht_in_der_liste(datenbank):
    """Sonst nennte die Datei einen Namen, dessen Code später abgewiesen wird."""
    await _zugang_mit_passwort("zur-raus", "ein-langes-passwort-14")
    await _zugang_mit_passwort("zur-drin", "ein-langes-passwort-15")
    async with acquire() as conn:
        await conn.execute(
            "delete from public.user_org_roles where user_id in "
            "(select id from public.users where olares_username = $1)",
            "zur-raus",
        )
    async with klient_fuer("zur-drin") as k:
        await k.post("/api/anmeldung/vergessen", json={"name": "keine-ahnung"})
    text = _datei().read_text(encoding="utf-8")
    assert "zur-drin" in text
    assert "zur-raus" not in text
