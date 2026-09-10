"""Gespräch vorbereiten — aus dem Bestand wird ein Skript, aus dem Skript
eine Datei.

Das Modell antwortet aus dem Skript, die Sprachausgabe ist ein Nachbau
mit prüfbaren Pseudo-MP3s. Geprüft wird, was uns gehört: Der Bestand
steht im Prompt, die Segmente wechseln den Sprecher, jede Stimme bekommt
ihr Modell, die Teile werden ohne doppelte Köpfe verkettet, die Datei
liegt mit 0600 unter der Ablage, das Audio kommt mit Range, Löschen
nimmt die Datei mit, die Automatik läuft je Termin genau einmal — und
eine fremde Organisation sieht nichts davon.
"""

import json
import pathlib
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from app import podcast
from app.config import settings
from tests.conftest import klient_fuer

# Ein MPEG-1-Layer-III-Rahmen: 128 kbit/s, 44,1 kHz, ohne Padding → 417 Byte.
KOPF = bytes([0xFF, 0xFB, 0x90, 0x00])
RAHMEN = 417
ID3 = b"ID3\x04\x00\x00\x00\x00\x00\x06" + b"TITLE!"  # 10 Byte Kopf + 6 Byte Inhalt


def _rahmen(inhalt: bytes) -> bytes:
    return (KOPF + inhalt)[:RAHMEN].ljust(RAHMEN, b"\x00")


def pseudo_mp3(text: str) -> bytes:
    """ID3-Kopf, Xing-Rahmen, dann ein Datenrahmen mit dem Text."""
    return ID3 + _rahmen(b"\x00" * 32 + b"Xing") + _rahmen(text.encode())


SKRIPT = {
    "titel": "Vor dem Termin bei Brinkmann",
    "segmente": [
        {"sprecher": "moderatorin", "text": "Willkommen. Heute geht es um Brinkmann Baustoffe."},
        {"sprecher": "kollege", "text": "Ein Baustoffhändler aus Tecklenburg, rund vierzig Leute."},
        {"sprecher": "moderatorin", "text": "Was ist offen?"},
        {"sprecher": "kollege", "text": "Ein Ticket zur Rechnung und das Angebot über zehntausend Euro."},
        {"sprecher": "unbekannt", "text": "Und die Frage nach dem Budget bleibt offen."},
    ],
}


@pytest.fixture
def modell(monkeypatch):
    gesehen = {"prompts": []}

    async def chat(cfg, system, user, **kwargs):
        gesehen["prompts"].append(user)
        return json.dumps(SKRIPT)

    monkeypatch.setattr(podcast, "chat", chat)
    return gesehen


@pytest.fixture
def sprachausgabe(monkeypatch):
    """Ein Speaches-Nachbau: merkt sich jede Anfrage, antwortet mit Pseudo-MP3."""
    anfragen: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        pfad = request.url.path
        if pfad == "/v1/audio/speech":
            koerper = json.loads(request.content)
            anfragen.append(koerper)
            return httpx.Response(200, content=pseudo_mp3(koerper["input"][:40]), headers={"content-type": "audio/mpeg"})
        if pfad == "/v1/models":
            # Wie Speaches auf der Box: die Stimmen stehen am Modell, einen
            # eigenen Stimmen-Endpunkt gibt es nicht.
            return httpx.Response(200, json={"data": [
                {"id": "speaches-ai/piper-de_DE-thorsten-high", "task": "text-to-speech",
                 "voices": [{"id": "en-fallback", "language": "en-us"}, {"id": "de_DE-thorsten-high", "language": "de-de"}]},
                {"id": "speaches-ai/Kokoro-82M-v1.0-ONNX", "task": "text-to-speech", "voices": [{"id": "af_heart", "language": "en-us"}]},
            ]})
        if pfad == "/v1/registry":
            return httpx.Response(200, json={"data": [{"id": "speaches-ai/piper-de_DE-kerstin-low"}, {"id": "speaches-ai/piper-en_US-amy-low"}, {"id": "speaches-ai/piper-de_DE-thorsten-high"}]})
        if pfad.startswith("/v1/models/"):
            return httpx.Response(201, json={"ok": True})
        return httpx.Response(404)

    def http_client(timeout: float = 120.0) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.MockTransport(handler), timeout=timeout)

    monkeypatch.setattr(podcast, "http_client", http_client)
    podcast.STIMMEN_ERMITTELT.clear()
    podcast.INSTALLATIONEN.clear()
    return anfragen


EINSTELLUNGEN = {
    "llm_base_url": "http://modell.local/v1", "llm_model": "t", "anreicherung_automatisch": False,
    "tts_endpoint_url": "http://speaches.local:8000", "tts_stimme": "", "tts_stimme_2": "kerstin",
}


async def _bestand(k):
    a = (await k.post("/api/companies", json={"name": "Brinkmann Baustoffe GmbH", "city": "Tecklenburg", "employee_count": 40})).json()
    r = await k.post("/api/tickets", json={"betreff": "Rechnung vom März fehlt", "company_id": a["id"]})
    assert r.status_code == 201, r.text
    r = await k.post("/api/tasks", json={"title": "Vor-Ort-Termin Lager", "art": "termin", "company_id": a["id"],
                                          "due_at": (datetime.now(UTC) + timedelta(hours=3)).isoformat()})
    assert r.status_code == 201, r.text
    r = await k.post("/api/activities", json={"kind": "note", "body": "Herr Brinkmann sagt, die Zusammenfassung sei Gold wert, aber die Sprechererkennung verwechselt bei drei Leuten die Stimmen.", "company_id": a["id"]})
    assert r.status_code in (200, 201), r.text
    return a, r.json()["id"]


# ── Reine Funktionen ─────────────────────────────────────────────────────


def test_fuer_stimme_macht_lesbaren_text():
    t = podcast.fuer_stimme("**Rund 12.500 €** bzw. ca. 30 % — z. B. für die GmbH.\n\nNeue  Zeile.")
    assert t == "Rund 12500 Euro beziehungsweise circa 30 Prozent , zum Beispiel für die G m b H. Neue Zeile."


def test_mp3_zusammenfuegen_laesst_koepfe_nur_einmal():
    a, b = pseudo_mp3("eins"), pseudo_mp3("zwei")
    ganz = podcast.mp3_zusammenfuegen([a, b])
    # Teil A ohne ID3 (Xing bleibt, er steht am Anfang), Teil B nur der Datenrahmen.
    assert ganz == a[len(ID3):] + _rahmen(b"zwei")
    assert ganz.count(b"Xing") == 1 and b"TITLE!" not in ganz
    assert podcast.mp3_zusammenfuegen([b"", a]) == a[len(ID3):]


def test_segmente_rueckfall_ohne_json():
    titel, segmente = podcast._segmente_pruefen(None, "Nur ein Text.")
    assert titel is None and segmente == [{"sprecher": "kollege", "text": "Nur ein Text."}]
    titel, segmente = podcast._segmente_pruefen(SKRIPT, "")
    assert titel == "Vor dem Termin bei Brinkmann" and len(segmente) == 5
    # Ein unbekannter Sprecher wird zum Wechsel gegenüber dem Vorgänger.
    assert segmente[4]["sprecher"] == "moderatorin"
    assert podcast.dauer_schaetzen(segmente) == round(sum(len(s["text"].split()) for s in segmente) / 2.4)


# ── Der Lauf ─────────────────────────────────────────────────────────────


async def test_firma_wird_zum_podcast(datenbank, modell, sprachausgabe):
    async with klient_fuer("podcast-1") as k:
        await k.put("/api/settings", json=EINSTELLUNGEN)
        e = (await k.get("/api/settings")).json()
        assert e["tts_ready"] and e["tts_modell"] == "speaches-ai/piper-de_DE-thorsten-high" and e["tts_modell_2"].endswith("kerstin-low")
        a, _ = await _bestand(k)

        s = (await k.get("/api/podcasts/status")).json()
        assert s == {"llm_ready": True, "tts_ready": True, "hint": ""}

        r = await k.post("/api/podcasts", json={"entity": "companies", "entity_id": a["id"], "anlass": "Vor-Ort-Termin"})
        assert r.status_code == 202, r.text
        pid = r.json()["id"]
        assert r.json()["status"] == "laeuft"
        # Solange die Folge entsteht, gibt es keine zweite.
        assert (await k.post("/api/podcasts", json={"entity": "companies", "entity_id": a["id"]})).status_code == 409
        await podcast.hintergrund_abwarten()

        p = (await k.get(f"/api/podcasts/{pid}")).json()
        assert p["status"] == "fertig", p
        assert p["titel"] == "Vor dem Termin bei Brinkmann" and p["anlass"] == "Vor-Ort-Termin"
        assert p["fortschritt"] == {"schritt": "fertig", "segment": 5, "gesamt": 5}
        assert [x["sprecher"] for x in p["segmente"]] == ["moderatorin", "kollege", "moderatorin", "kollege", "moderatorin"]
        assert p["skript"].startswith("Moderatorin: Willkommen.") and "\n\nKollege: Ein Baustoff" in p["skript"]
        assert p["dauer_s"] and p["llm_modell"] == "t"

        # Der Bestand stand im Prompt: Firma, Ticket, Termin, Notiz, Anlass.
        prompt = modell["prompts"][0]
        for erwartet in ("Brinkmann Baustoffe GmbH", "Rechnung vom März fehlt", "Vor-Ort-Termin Lager", "Sprechererkennung verwechselt", "Anlass: Vor-Ort-Termin"):
            assert erwartet in prompt, erwartet

        # Jede Stimme mit ihrem Modell; die Moderatorin mit eingetragener,
        # der Kollege mit ermittelter Stimme. Der Text ging in der
        # Stimmfassung raus, nicht mit Markdown.
        assert len(sprachausgabe) == 5
        assert sprachausgabe[0]["model"] == "speaches-ai/piper-de_DE-kerstin-low" and sprachausgabe[0]["voice"] == "kerstin"
        assert sprachausgabe[1]["model"] == "speaches-ai/piper-de_DE-thorsten-high" and sprachausgabe[1]["voice"] == "de_DE-thorsten-high"
        assert all(x["response_format"] == "mp3" for x in sprachausgabe)

        # Die Datei: unter der Ablage, 0600, genau die verketteten Teile.
        treffer = list((pathlib.Path(settings.app_data_dir) / "podcasts").glob(f"*/{pid}.mp3"))
        assert len(treffer) == 1
        datei = treffer[0]
        assert oct(datei.stat().st_mode & 0o777) == "0o600"
        erwartet = podcast.mp3_zusammenfuegen([pseudo_mp3(podcast.fuer_stimme(s["text"])[:40]) for s in SKRIPT["segmente"]])
        assert datei.read_bytes() == erwartet and p["bytes"] == len(erwartet)

        audio = await k.get(f"/api/podcasts/{pid}/audio")
        assert audio.status_code == 200 and audio.headers["content-type"] == "audio/mpeg"
        assert audio.content == erwartet and "inline" in audio.headers["content-disposition"]
        teil = await k.get(f"/api/podcasts/{pid}/audio", headers={"Range": "bytes=0-99"})
        assert teil.status_code == 206 and len(teil.content) == 100

        liste = (await k.get(f"/api/podcasts?entity=companies&entity_id={a['id']}")).json()
        assert [x["id"] for x in liste] == [pid]
        heute = (await k.get("/api/podcasts/heute")).json()
        assert [x["id"] for x in heute] == [pid] and heute[0]["name"] == "Brinkmann Baustoffe GmbH"

        # Im Verlauf steht, dass eine Folge entstand — als KI-Eintrag.
        verlauf = (await k.get(f"/api/activities?company_id={a['id']}")).json()
        ki = [v for v in verlauf if v["kind"] == "ai"]
        assert ki and ki[0]["subject"] == "Gesprächsvorbereitung als Podcast"

        # Eine fremde Organisation sieht nichts.
        async with klient_fuer("podcast-fremd") as fremd:
            assert (await fremd.get(f"/api/podcasts/{pid}")).status_code == 404
            assert (await fremd.get(f"/api/podcasts/{pid}/audio")).status_code == 404

        # Löschen nimmt die Datei mit.
        assert (await k.delete(f"/api/podcasts/{pid}")).status_code == 204
        assert not datei.exists()
        assert (await k.get(f"/api/podcasts/{pid}")).status_code == 404
        assert (await k.get(f"/api/podcasts?entity=companies&entity_id={a['id']}")).json() == []


async def test_lead_kontext_und_fehler_landen_in_der_zeile(datenbank, modell, sprachausgabe, monkeypatch):
    async with klient_fuer("podcast-2") as k:
        await k.put("/api/settings", json=EINSTELLUNGEN)
        a, _ = await _bestand(k)
        d = (await k.post("/api/deals", json={"name": "Insilo für Brinkmann", "company_id": a["id"], "amount_cents": 1250000})).json()

        r = await k.post("/api/podcasts", json={"entity": "deals", "entity_id": d["id"]})
        assert r.status_code == 202, r.text
        await podcast.hintergrund_abwarten()
        p = (await k.get(f"/api/podcasts/{r.json()['id']}")).json()
        assert p["status"] == "fertig" and p["anlass"] == "das nächste Gespräch"
        prompt = modell["prompts"][-1]
        assert prompt.index("Lead: Insilo für Brinkmann") < prompt.index("Firma: Brinkmann Baustoffe GmbH")
        assert "12500 €" in prompt and "Rechnung vom März fehlt" in prompt

        # Fällt die Sprachausgabe aus, steht der Fehler in der Zeile.
        async def kaputt(*a, **kw):
            raise httpx.ConnectError("Verbindung abgelehnt")

        monkeypatch.setattr(podcast, "sprechen", kaputt)
        r = await k.post("/api/podcasts", json={"entity": "deals", "entity_id": d["id"]})
        assert r.status_code == 202
        await podcast.hintergrund_abwarten()
        p = (await k.get(f"/api/podcasts/{r.json()['id']}")).json()
        assert p["status"] == "fehler" and "ConnectError" in p["fehler"]
        assert (await k.get(f"/api/podcasts/{p['id']}/audio")).status_code == 404


async def test_ohne_sprachausgabe_oder_modell_409(datenbank, modell, sprachausgabe):
    async with klient_fuer("podcast-3") as k:
        a = (await k.post("/api/companies", json={"name": "Ohne Stimme AG"})).json()
        await k.put("/api/settings", json={"llm_base_url": "http://modell.local/v1", "llm_model": "t", "tts_endpoint_url": None, "anreicherung_automatisch": False})
        s = (await k.get("/api/podcasts/status")).json()
        assert s["llm_ready"] and not s["tts_ready"] and "Sprachausgabe" in s["hint"]
        assert (await k.post("/api/podcasts", json={"entity": "companies", "entity_id": a["id"]})).status_code == 409
        assert (await k.post("/api/podcasts/probe", json={})).status_code == 409
        await k.put("/api/settings", json={"llm_base_url": None, "tts_endpoint_url": "http://speaches.local:8000"})
        assert (await k.post("/api/podcasts", json={"entity": "companies", "entity_id": a["id"]})).status_code == 409
        assert (await k.post("/api/podcasts", json={"entity": "companies", "entity_id": "00000000-0000-0000-0000-000000000000"})).status_code == 409


async def test_probe_und_stimmen(datenbank, sprachausgabe):
    async with klient_fuer("podcast-4") as k:
        await k.put("/api/settings", json=EINSTELLUNGEN)
        r = await k.post("/api/podcasts/probe", json={"sprecher": "moderatorin"})
        assert r.status_code == 200 and r.headers["content-type"] == "audio/mpeg"
        assert sprachausgabe[-1]["voice"] == "kerstin" and "Moderatorin" in sprachausgabe[-1]["input"]
        r = await k.post("/api/podcasts/probe", json={"sprecher": "kollege"})
        assert r.status_code == 200 and sprachausgabe[-1]["voice"] == "de_DE-thorsten-high"

        st = (await k.get("/api/podcasts/stimmen")).json()
        # Deutsch zuerst, Installiertes nicht noch einmal unter „verfügbar".
        assert st["installiert"] == ["speaches-ai/piper-de_DE-thorsten-high", "speaches-ai/Kokoro-82M-v1.0-ONNX"]
        assert st["verfuegbar"] == ["speaches-ai/piper-de_DE-kerstin-low", "speaches-ai/piper-en_US-amy-low"]

        r = await k.post("/api/podcasts/stimmen/einrichten", json={"modell": "speaches-ai/piper-de_DE-kerstin-low"})
        assert r.status_code == 202
        await podcast.hintergrund_abwarten()
        st = (await k.get("/api/podcasts/stimmen")).json()
        assert st["installationen"] == {"speaches-ai/piper-de_DE-kerstin-low": "fertig"}
        assert (await k.post("/api/podcasts/stimmen/einrichten", json={"modell": "../x"})).status_code == 422


async def test_automatik_einmal_je_termin(datenbank, modell, sprachausgabe):
    async with klient_fuer("podcast-5") as k:
        await k.put("/api/settings", json={**EINSTELLUNGEN, "podcast_automatisch": True})
        a, _ = await _bestand(k)  # enthält einen Termin in drei Stunden
        b = (await k.post("/api/companies", json={"name": "Später dran GmbH"})).json()
        # Ein Termin übermorgen zählt nicht, eine Aufgabe ohne Bezug auch nicht.
        await k.post("/api/tasks", json={"title": "Später", "art": "termin", "company_id": b["id"], "due_at": (datetime.now(UTC) + timedelta(hours=40)).isoformat()})
        await k.post("/api/tasks", json={"title": "Ohne Bezug", "art": "termin", "due_at": (datetime.now(UTC) + timedelta(hours=2)).isoformat()})

        assert await podcast.automatisch_vorbereiten() == 1
        await podcast.hintergrund_abwarten()
        assert await podcast.automatisch_vorbereiten() == 0

        heute = (await k.get("/api/podcasts/heute")).json()
        assert len(heute) == 1 and heute[0]["status"] == "fertig"
        assert heute[0]["termin_titel"] == "Vor-Ort-Termin Lager" and heute[0]["anlass"].startswith("Vor-Ort-Termin Lager am ")
        assert heute[0]["entity_id"] == a["id"]

        # Ausgeschaltet läuft nichts — auch nicht für neue Termine.
        await k.put("/api/settings", json={"podcast_automatisch": False})
        await k.post("/api/tasks", json={"title": "Noch einer", "art": "termin", "company_id": b["id"], "due_at": (datetime.now(UTC) + timedelta(hours=5)).isoformat()})
        assert await podcast.automatisch_vorbereiten() == 0


async def test_jede_tabelle_der_sicherung_kennt_podcasts():
    from app import sicherung

    assert "podcasts" in sicherung.TABELLEN and sicherung.TABELLEN.index("podcasts") > sicherung.TABELLEN.index("tasks")


# ── Fehlerbericht ────────────────────────────────────────────────────────


async def test_oberflaechenfehler_landen_im_protokoll(datenbank, capsys):
    async with klient_fuer("fehler-1") as k:
        r = await k.post("/api/fehler", json={"nachricht": "TypeError: x is not a function", "stack": "at a\nat b", "pfad": "/firmen/1", "agent": "Safari"})
        assert r.status_code == 204
        aus = capsys.readouterr().out
        assert "Oberflächenfehler [fehler-1] /firmen/1: TypeError: x is not a function" in aus
        assert "  at a\n  at b" in aus and "Browser: Safari" in aus
        assert (await k.post("/api/fehler", json={"nachricht": "x" * 3000})).status_code == 422




# ---------------------------------------------------------------------------
# Modell und Stimme sind zwei Dinge
# ---------------------------------------------------------------------------

async def test_eingetragene_stimme_wird_genommen_und_nicht_erraten(sprachausgabe):
    """Für jeden Dienst, der nicht Speaches ist.

    Bei Speaches steht die Stimme am Modell, und Beacon errät sie durch
    Probieren. Bei einem anderen OpenAI-kompatiblen Dienst sind Modell und
    Stimme zwei Angaben — Marc am 10.9.2026 auf seiner Box mit Omnivoice:
    Modell `tts-voxtral`, Stimme `clone:new`. In der Maske gab es dafür
    kein Feld, obwohl der Server sie längst mitschickt.
    """
    tts = podcast.TTSConfig(
        endpoint_url="http://tts.local",
        api_key="",
        modell="tts-voxtral",
        stimme="clone:new",
        modell_2="tts-voxtral",
        stimme_2="clone:maike",
    )
    await podcast.sprechen(tts, [
        {"sprecher": "kollege", "text": "Guten Tag."},
        {"sprecher": "moderatorin", "text": "Willkommen."},
    ])

    assert [(a["model"], a["voice"]) for a in sprachausgabe] == [
        ("tts-voxtral", "clone:new"),
        ("tts-voxtral", "clone:maike"),
    ]


async def test_ohne_stimme_wird_sie_weiter_erraten(sprachausgabe):
    """Der Piper-Fall bleibt, wie er war — leer heißt „rate"."""
    tts = podcast.TTSConfig(
        endpoint_url="http://tts.local",
        api_key="",
        modell="speaches-ai/piper-de_DE-thorsten-high",
        stimme="",
        modell_2="speaches-ai/piper-de_DE-thorsten-high",
        stimme_2="",
    )
    await podcast.sprechen(tts, [{"sprecher": "kollege", "text": "Guten Tag."}])

    gesprochen = [a for a in sprachausgabe if a["input"].startswith("Guten Tag")]
    assert gesprochen, "es wurde nichts gesprochen"
    assert gesprochen[0]["voice"] == "de_DE-thorsten-high"
