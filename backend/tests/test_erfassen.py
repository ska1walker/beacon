"""Aus Hingeworfenem wird ein Datensatz.

Geprüft wird der Teil, der uns gehört: dass nur bekannte Felder
durchkommen, dass Erfundenes hängenbleibt, dass eine Dublette auffällt,
bevor der dritte „Meyer Präzisionstechnik" im Bestand steht.
"""

import io

import httpx
import pytest

from app.routers import erfassen
from tests.conftest import klient_fuer

SIGNATUR = """
Mit freundlichen Grüßen
Dr. Julia Ahrend
Partnerin | Hanseatic Legal Partner mbB
Alsterufer 12, 20354 Hamburg
T +49 40 555 0199 · M +49 170 1234567
ahrend@hanseatic-legal.de
"""

ANTWORT_KONTAKT = (
    '{"felder": {'
    '"first_name": "Julia", "last_name": "Ahrend", "email": "ahrend@hanseatic-legal.de",'
    '"phone": "+49 40 555 0199", "mobile": "+49 170 1234567", "job_title": "Partnerin",'
    '"firma_name": "Hanseatic Legal Partner mbB", "firma_ort": "Hamburg",'
    '"firma_strasse": "Alsterufer 12", "firma_plz": "20354",'
    '"lieblingsfarbe": "blau", "email_geraten": "j.ahrend@example.com"},'
    ' "rest": "Titel: Dr."}'
)


@pytest.fixture
def modell(monkeypatch):
    """Das Modell antwortet aus dem Skript — kein Netz im Test."""
    aufrufe: list[dict] = []

    async def antwort(cfg, system, user, **kwargs):
        aufrufe.append({"user": user, **kwargs})
        return ANTWORT_KONTAKT

    monkeypatch.setattr(erfassen, "chat", antwort)
    return aufrufe


async def test_signatur_wird_zum_kontakt(datenbank, modell):
    async with klient_fuer("erf-text") as k:
        await k.put("/api/settings", json={"llm_base_url": "http://modell.local/v1"})
        v = (await k.post("/api/erfassen/text", json={"art": "contact", "text": SIGNATUR})).json()

        f = v["felder"]
        assert f["first_name"] == "Julia" and f["last_name"] == "Ahrend"
        assert f["email"] == "ahrend@hanseatic-legal.de"
        assert f["firma_name"] == "Hanseatic Legal Partner mbB"

        # Was das Modell dazuerfindet, kommt nicht durch: „lieblingsfarbe"
        # ist kein Feld, „email_geraten" auch nicht.
        assert "lieblingsfarbe" not in f
        assert "email_geraten" not in f

        # Was in kein Feld passte, wird nicht verschluckt.
        assert v["rest"] == "Titel: Dr."
        assert v["dublette"] is None
        # Nichts wurde gespeichert — der Mensch drückt auf Anlegen.
        assert (await k.get("/api/contacts")).json() == []


async def test_dublette_faellt_auf(datenbank, modell):
    async with klient_fuer("erf-dublette") as k:
        await k.put("/api/settings", json={"llm_base_url": "http://modell.local/v1"})
        await k.post("/api/contacts", json={
            "first_name": "Julia", "last_name": "Ahrend", "email": "ahrend@hanseatic-legal.de",
        })
        v = (await k.post("/api/erfassen/text", json={"art": "contact", "text": SIGNATUR})).json()
        assert v["dublette"] is not None
        assert v["dublette"]["grund"] == "gleiche E-Mail-Adresse"


async def test_ohne_modell_kein_versuch(datenbank):
    async with klient_fuer("erf-kein-modell") as k:
        antwort = await k.post("/api/erfassen/text", json={"art": "contact", "text": SIGNATUR})
        assert antwort.status_code == 409
        assert "Sprachmodell" in antwort.json()["detail"]


async def test_leeres_ergebnis_wird_gemeldet(datenbank, monkeypatch):
    async def nichts(cfg, system, user, **kwargs):
        return '{"felder": {}}'

    monkeypatch.setattr(erfassen, "chat", nichts)
    async with klient_fuer("erf-leer") as k:
        await k.put("/api/settings", json={"llm_base_url": "http://modell.local/v1"})
        antwort = await k.post("/api/erfassen/text", json={"art": "contact", "text": "asdfgh"})
        assert antwort.status_code == 422


async def test_bild_geht_als_datenurl_ans_modell(datenbank, modell):
    """Das Bild wird nicht abgelegt — es geht einmal hin und ist vergessen."""
    async with klient_fuer("erf-bild") as k:
        await k.put("/api/settings", json={"llm_base_url": "http://modell.local/v1"})
        # Ein winziges gültiges PNG.
        png = bytes.fromhex(
            "89504e470d0a1a0a0000000d4948445200000001000000010806000000"
            "1f15c4890000000a49444154789c6360000002000100ffff0300000600"
            "0557bfabd40000000049454e44ae426082"
        )
        antwort = await k.post(
            "/api/erfassen/bild",
            data={"art": "contact"},
            files={"datei": ("karte.png", io.BytesIO(png), "image/png")},
        )
        assert antwort.status_code == 200
        assert antwort.json()["felder"]["last_name"] == "Ahrend"

        bilder = modell[-1]["bilder"]
        assert len(bilder) == 1
        assert bilder[0].startswith("data:image/png;base64,")


async def test_falscher_dateityp_und_zu_gross(datenbank, modell):
    async with klient_fuer("erf-datei") as k:
        await k.put("/api/settings", json={"llm_base_url": "http://modell.local/v1"})
        pdf = await k.post(
            "/api/erfassen/bild",
            data={"art": "contact"},
            files={"datei": ("x.pdf", io.BytesIO(b"%PDF-1.4"), "application/pdf")},
        )
        assert pdf.status_code == 415

        gross = await k.post(
            "/api/erfassen/bild",
            data={"art": "contact"},
            files={"datei": ("gross.png", io.BytesIO(b"x" * (erfassen.BILD_MAX_BYTES + 10)), "image/png")},
        )
        assert gross.status_code == 413


async def test_modell_ohne_augen_sagt_es(datenbank, monkeypatch):
    """Ein 400 auf ein Bild heißt „kann keine Bilder", nicht „Endpunkt aus"."""
    async def blind(cfg, system, user, **kwargs):
        raise httpx.HTTPStatusError(
            "nope",
            request=httpx.Request("POST", "http://modell.local/v1/chat/completions"),
            response=httpx.Response(400),
        )

    monkeypatch.setattr(erfassen, "chat", blind)
    async with klient_fuer("erf-blind") as k:
        await k.put("/api/settings", json={"llm_base_url": "http://modell.local/v1"})
        png = bytes.fromhex(
            "89504e470d0a1a0a0000000d4948445200000001000000010806000000"
            "1f15c4890000000a49444154789c6360000002000100ffff0300000600"
            "0557bfabd40000000049454e44ae426082"
        )
        antwort = await k.post(
            "/api/erfassen/bild",
            data={"art": "contact"},
            files={"datei": ("karte.png", io.BytesIO(png), "image/png")},
        )
        assert antwort.status_code == 422
        assert "keine Bilder" in antwort.json()["detail"]


async def test_firma_hat_eigene_felder(datenbank, monkeypatch):
    async def firma(cfg, system, user, **kwargs):
        return (
            '{"felder": {"name": "Nordwind Logistik GmbH", "domain": "nordwind-logistik.de",'
            ' "city": "Bremen", "country": "de", "first_name": "Unsinn"}}'
        )

    monkeypatch.setattr(erfassen, "chat", firma)
    async with klient_fuer("erf-firma") as k:
        await k.put("/api/settings", json={"llm_base_url": "http://modell.local/v1"})
        v = (await k.post("/api/erfassen/text", json={
            "art": "company", "text": "Nordwind Logistik GmbH, Bremen, nordwind-logistik.de",
        })).json()
        assert v["felder"]["name"] == "Nordwind Logistik GmbH"
        assert v["felder"]["country"] == "DE"       # normalisiert
        assert "first_name" not in v["felder"]      # gehört nicht zur Firma
