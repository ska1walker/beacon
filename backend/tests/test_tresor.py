"""Der Tresor — was er kann und was er ausdrücklich nicht kann.

Geprüft wird nicht „verschlüsselt es", sondern: Kommt derselbe Klartext
zurück? Sieht ein Datenbankabzug noch etwas? Funktioniert eine Datenbank
aus der Zeit davor weiter? Und wird ein Wert, dessen Schlüssel fehlt,
ehrlich zu `None` statt zu Buchstabensalat?
"""

import base64
import pathlib
from uuid import UUID

import pytest

from app import tresor
from app.db import acquire


@pytest.fixture(autouse=True)
def eigener_schluessel(tmp_path, monkeypatch):
    """Jeder Test bekommt seinen eigenen Schlüssel, in einem eigenen Ordner."""
    monkeypatch.setattr(tresor.settings, "app_data_dir", str(tmp_path))
    monkeypatch.setattr(tresor, "_schluessel", None)
    return tmp_path


def test_derselbe_klartext_kommt_zurueck():
    for wert in ("geheim", "ein sehr langes Passwort mit Umlauten: äöüß", "sk-1234567890"):
        assert tresor.entschluesseln(tresor.verschluesseln(wert)) == wert


def test_im_abzug_steht_das_geheimnis_nicht_mehr():
    verschluesselt = tresor.verschluesseln("streng geheim")
    assert "streng geheim" not in verschluesselt
    assert verschluesselt.startswith(tresor.MARKE)


def test_zweimal_verschluesselt_sieht_verschieden_aus():
    """Sonst verriete ein Abzug, dass zwei Konten dasselbe Passwort haben."""
    a = tresor.verschluesseln("gleiches Passwort")
    b = tresor.verschluesseln("gleiches Passwort")
    assert a != b
    assert tresor.entschluesseln(a) == tresor.entschluesseln(b) == "gleiches Passwort"


def test_leeres_bleibt_leer():
    """`None` heißt „nicht hinterlegt". Daraus einen Kryptotext zu machen
    verlöre genau diese Aussage."""
    assert tresor.verschluesseln(None) is None
    assert tresor.verschluesseln("") == ""
    assert tresor.entschluesseln(None) is None
    assert tresor.entschluesseln("") == ""


def test_klartext_aus_der_zeit_davor_funktioniert_weiter():
    """Die Nachsicht ist der ganze Grund, warum die Umstellung ohne
    Ausfall geht: Eine Datenbank ohne Tresor bleibt lesbar."""
    assert tresor.entschluesseln("altes-klartext-passwort") == "altes-klartext-passwort"


def test_schon_verschluesseltes_wird_nicht_doppelt_verpackt():
    einmal = tresor.verschluesseln("geheim")
    assert tresor.verschluesseln(einmal) == einmal


def test_ohne_passenden_schluessel_gibt_es_nichts_halbes(eigener_schluessel, monkeypatch):
    """Ein falscher Schlüssel darf keinen Buchstabensalat liefern, sondern
    muss `None` sagen — sonst versuchte der Versand eine Anmeldung mit
    Müll und der Fehler zeigte in die falsche Richtung."""
    verschluesselt = tresor.verschluesseln("geheim")
    monkeypatch.setattr(tresor, "_schluessel", None)
    (eigener_schluessel / tresor.DATEI).write_text(
        base64.urlsafe_b64encode(b"x" * 32).decode()
    )
    assert tresor.entschluesseln(verschluesselt) is None


def test_der_schluessel_liegt_mit_0600_neben_den_daten(eigener_schluessel):
    tresor.verschluesseln("irgendwas")
    datei = eigener_schluessel / tresor.DATEI
    assert datei.exists()
    assert oct(datei.stat().st_mode)[-3:] == "600"
    # Und er bleibt derselbe — sonst wäre alles Gespeicherte beim nächsten
    # Start unlesbar.
    erst = tresor.schluessel()
    tresor._schluessel = None
    assert tresor.schluessel() == erst


def test_jede_geheimnisspalte_steht_im_vertrag():
    """Wer eine Spalte mit einem Geheimnis ergänzt und sie hier vergisst,
    speichert weiter im Klartext — und niemand merkt es."""
    alle = {s for _, spalten in tresor.SPALTEN.values() for s in spalten}
    assert {"smtp_passwort", "imap_passwort", "llm_api_key", "suche_api_key",
            "tts_api_key", "brevo_api_key", "mail_endpoint_secret"} <= alle


async def test_nachziehen_holt_bestehenden_klartext_nach(datenbank, eigener_schluessel):
    from tests.conftest import klient_fuer

    async with klient_fuer("tresor-nach") as k:
        await k.put("/api/settings", json={"smtp_passwort": "im Klartext gespeichert"})

    async with acquire() as conn, conn.transaction():
        # Von Hand zurück auf Klartext, als käme die Zeile aus der Zeit davor.
        await conn.execute("alter table public.org_settings disable row level security")
        await conn.execute(
            "update public.org_settings set smtp_passwort = 'im Klartext gespeichert' "
            "where smtp_passwort is not null"
        )
        await conn.execute("alter table public.org_settings enable row level security")

    async with acquire() as conn:
        assert await tresor.nachziehen(conn) >= 1
        async with conn.transaction():
            await conn.execute("alter table public.org_settings disable row level security")
            offen = await conn.fetchval(
                "select count(*) from public.org_settings "
                "where smtp_passwort = 'im Klartext gespeichert'"
            )
            verpackt = await conn.fetchval(
                f"select smtp_passwort from public.org_settings "
                f"where smtp_passwort like '{tresor.MARKE}%' limit 1"
            )
            await conn.execute("alter table public.org_settings enable row level security")
    assert offen == 0, "Klartext ist liegengeblieben"
    assert tresor.entschluesseln(verpackt) == "im Klartext gespeichert"


def test_der_schluessel_ist_keine_datei_die_woanders_landet(eigener_schluessel):
    """Er gehört unter `/app/data` — den einzigen Pfad, den Olares als
    dauerhaft zusichert und der eine Deinstallation überlebt."""
    tresor.verschluesseln("x")
    assert pathlib.Path(tresor._pfad()).parent == pathlib.Path(str(eigener_schluessel))


# ---------------------------------------------------------------------------
# Drei Zustände, nicht zwei
# ---------------------------------------------------------------------------

def test_lesbar_unterscheidet_die_drei_faelle(eigener_schluessel, monkeypatch):
    """„Hinterlegt" ist keine Aussage darüber, ob sich etwas öffnen lässt.

    Genau daran hing Marcs 401 am 10.9.2026: In der Spalte stand ein
    Kryptotext, die Maske meldete „hinterlegt", der Tresorschlüssel war
    aber weg. Tavily bekam einen leeren Bearer und lehnte ab.
    """
    geheim = tresor.verschluesseln("tvly-echt")
    assert tresor.lesbar(geheim) is True
    assert tresor.verloren(geheim) is False

    assert tresor.lesbar(None) is False
    assert tresor.verloren(None) is False
    assert tresor.lesbar("") is False

    # Klartext aus der Zeit vor dem Tresor bleibt lesbar und ist nicht verloren.
    assert tresor.lesbar("sk-alt-im-klartext") is True
    assert tresor.verloren("sk-alt-im-klartext") is False

    # Und jetzt der Fall, der zählt: Der Schlüssel ist weg, der Wert bleibt.
    (eigener_schluessel / tresor.DATEI).unlink()
    monkeypatch.setattr(tresor, "_schluessel", None)
    assert tresor.entschluesseln(geheim) is None
    assert tresor.lesbar(geheim) is False
    assert tresor.verloren(geheim) is True


async def test_die_maske_sagt_nicht_hinterlegt_wenn_der_schluessel_weg_ist(
    datenbank, eigener_schluessel, monkeypatch
):
    """Der Fehler, der Marc zwei Tage gekostet hat.

    `suche_api_key_set` fragte nur, ob in der Spalte etwas steht. Nach dem
    Verlust des Tresorschlüssels stand dort weiter ein Kryptotext, die
    Maske zeigte „hinterlegt", der Suchdienst bekam einen leeren Bearer
    und Tavily antwortete mit 401.
    """
    from tests.conftest import klient_fuer

    async with klient_fuer("tresor-verloren") as k:
        await k.put("/api/settings", json={
            "suche_endpoint_url": "https://api.tavily.com/search",
            "suche_api_key": "tvly-echt",
        })
        vorher = (await k.get("/api/settings")).json()
        assert vorher["suche_api_key_set"] is True
        assert vorher["zugangsdaten_verloren"] == []

        # Der Schlüssel unter /app/data verschwindet, die Datenbank bleibt.
        (eigener_schluessel / tresor.DATEI).unlink()
        monkeypatch.setattr(tresor, "_schluessel", None)

        nachher = (await k.get("/api/settings")).json()

    assert nachher["suche_api_key_set"] is False
    assert nachher["zugangsdaten_verloren"] == ["Schlüssel des Suchdienstes"]


# ---------------------------------------------------------------------------
# Ein Schlüssel gehört zu seiner Adresse
# ---------------------------------------------------------------------------

async def test_wechsel_des_dienstes_nimmt_den_alten_schluessel_mit(datenbank, eigener_schluessel):
    """Marcs zweiter Befund, und vermutlich die Ursache seines 401.

    „Musste nur aufpassen wenn du wechselst, weil der dann die Secret Keys
    durcheinander bringt." Das Schlüsselfeld zeigt „hinterlegt" und lädt
    dazu ein, es leer zu lassen. Bis 0.9.6 blieb dann der Schlüssel des
    **vorherigen** Dienstes stehen und ging als Bearer an den neuen.
    """
    from tests.conftest import klient_fuer

    async with klient_fuer("schluessel-wechsel") as k:
        await k.put("/api/settings", json={
            "suche_endpoint_url": "https://api.search.brave.com/res/v1/web/search",
            "suche_api_key": "brave-schluessel",
        })
        assert (await k.get("/api/settings")).json()["suche_api_key_set"] is True

        # Umstellen auf Tavily, Schlüsselfeld leer gelassen.
        await k.put("/api/settings", json={
            "suche_endpoint_url": "https://api.tavily.com/search",
            "suche_api_key": "",
        })
        nachher = (await k.get("/api/settings")).json()

    assert nachher["suche_endpoint_url"] == "https://api.tavily.com/search"
    assert nachher["suche_api_key_set"] is False, "Der Brave-Schlüssel wäre an Tavily gegangen"


async def test_neuer_schluessel_beim_wechsel_bleibt_stehen(datenbank, eigener_schluessel):
    """Wer beim Umstellen gleich den richtigen einträgt, behält ihn."""
    from tests.conftest import klient_fuer

    async with klient_fuer("schluessel-mit") as k:
        await k.put("/api/settings", json={
            "suche_endpoint_url": "https://api.search.brave.com/res/v1/web/search",
            "suche_api_key": "brave-schluessel",
        })
        await k.put("/api/settings", json={
            "suche_endpoint_url": "https://api.tavily.com/search",
            "suche_api_key": "tavily-schluessel",
        })
        assert (await k.get("/api/settings")).json()["suche_api_key_set"] is True
        wer = (await k.get("/api/mitglieder/wer")).json()

    # An die eigene Organisation gebunden: Die Tabelle trägt die Zeilen
    # aller Tests, und eine fremde ist mit einem anderen Tresorschlüssel
    # verschlüsselt — sie käme als None zurück und sähe aus wie ein Fehler.
    async with acquire() as conn, conn.transaction():
        await conn.execute("alter table public.org_settings disable row level security")
        roh = await conn.fetchval(
            "select suche_api_key from public.org_settings where org_id = $1",
            UUID(wer["org_id"]),
        )
        await conn.execute("alter table public.org_settings enable row level security")
    assert tresor.entschluesseln(roh) == "tavily-schluessel"


async def test_derselbe_dienst_behaelt_seinen_schluessel(datenbank, eigener_schluessel):
    """Ein Tippfehler im Pfad ist kein Dienstwechsel."""
    from tests.conftest import klient_fuer

    async with klient_fuer("schluessel-pfad") as k:
        await k.put("/api/settings", json={
            "suche_endpoint_url": "https://api.tavily.com/serch",
            "suche_api_key": "tavily-schluessel",
        })
        await k.put("/api/settings", json={
            "suche_endpoint_url": "https://api.tavily.com/search",
            "suche_api_key": "",
        })
        assert (await k.get("/api/settings")).json()["suche_api_key_set"] is True


async def test_die_regel_gilt_fuer_alle_vier_adressen(datenbank, eigener_schluessel):
    """Sprachmodell, Sprachausgabe und Mail-Endpunkt haben dasselbe Muster."""
    from tests.conftest import klient_fuer

    async with klient_fuer("schluessel-alle") as k:
        await k.put("/api/settings", json={
            "llm_base_url": "https://alt.example.com/v1", "llm_api_key": "alt",
            "tts_endpoint_url": "http://alt.svc.cluster.local:8000", "tts_api_key": "alt",
            "mail_endpoint_url": "https://alt.example.com/hook", "mail_endpoint_secret": "alt",
        })
        vorher = (await k.get("/api/settings")).json()
        assert (vorher["llm_api_key_set"], vorher["tts_api_key_set"], vorher["mail_endpoint_secret_set"]) == (True, True, True)

        await k.put("/api/settings", json={
            "llm_base_url": "https://neu.example.com/v1", "llm_api_key": "",
            "tts_endpoint_url": "http://neu.svc.cluster.local:8000", "tts_api_key": "",
            "mail_endpoint_url": "https://neu.example.com/hook", "mail_endpoint_secret": "",
        })
        nachher = (await k.get("/api/settings")).json()

    assert (nachher["llm_api_key_set"], nachher["tts_api_key_set"], nachher["mail_endpoint_secret_set"]) == (False, False, False)
