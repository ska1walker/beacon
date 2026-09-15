"""Besprechungen aus Insilos gemeinsamem Ordner — der Weg, den Relay geht.

Die Dateien hier sind so gebaut, wie Insilo sie schreibt
(`insilo/backend/app/relay_drop.py`, schema 1): vorne der Kopf der Ablage,
dahinter Insilos Markdown mit eigenem Kopf. Eine echte Datei von der Box
vom 15.9.2026 hatte genau diese Form.
"""

import hashlib
import hmac
import json
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from app import insilo_ablage
from app.config import settings
from app.main import app
from tests.conftest import klient_fuer


def ablagedatei(
    insilo_id: str,
    titel: str,
    *,
    abschnitte: str = "",
    schema: int = 1,
    recorded_at: str = "2026-09-15T07:20:41.370000+00:00",
) -> str:
    return "\n".join(
        [
            "---",
            f'insilo_id: "{insilo_id}"',
            f'title: "{titel}"',
            f'recorded_at: "{recorded_at}"',
            "duration_min: 32",
            'language: "de"',
            'participants: ["Katrin Lohse", "SPEAKER_01"]',
            'tags: ["Wartung"]',
            'template: "Vertriebsgespräch"',
            "source_url: ''",
            f"schema: {schema}",
            "---",
            "---",
            "source: insilo",
            f"meeting_id: {insilo_id}",
            f'title: "{titel}"',
            "speakers:",
            "  - Katrin Lohse",
            "  - SPEAKER_01",
            "---",
            "",
            f"# {titel}",
            "",
            "**Datum:** 15.09.2026 · **Dauer:** 32 min · **Vorlage:** Vertriebsgespräch",
            "",
            abschnitte,
            "## Zusammenfassung",
            "",
            "Angebot für die Wartung besprochen.",
            "",
            "## Offene Aufgaben",
            "",
            "- [ ] Angebot schicken — Frau Lohse, fällig Freitag",
            "",
        ]
    )


@pytest.fixture
def ordner(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "insilo_ablage_dir", str(tmp_path))
    return tmp_path


def _legen(ordner, name: str, text: str) -> None:
    (ordner / name).write_text(text, encoding="utf-8")


# ── Eine Datei ──────────────────────────────────────────────────────────


def test_datei_nach_vertrag():
    kennung = str(uuid4())
    datei = insilo_ablage.lesen(
        ablagedatei(kennung, "Abstimmung", abschnitte="## Anwesende\n\n- Frau Lohse\n- Berater Klein\n\n## Kunde\n\nMeyer Präzisionstechnik\n")
    )
    assert datei is not None
    assert datei.insilo_id == kennung
    assert datei.titel == "Abstimmung"
    assert datei.dauer_sek == 32 * 60
    assert datei.vorlage == "Vertriebsgespräch"
    assert datei.schlagworte == ["Wartung"]
    assert datei.recorded_at is not None and datei.recorded_at.hour == 7
    # Das Markdown beginnt mit Insilos eigenem Kopf — so liest es auch der Webhook.
    assert datei.markdown.startswith("---\nsource: insilo")
    assert datei.zusammenfassung == {
        "anwesende": ["Frau Lohse", "Berater Klein"],
        "kunde": ["Meyer Präzisionstechnik"],
    }


def test_aufgaben_sind_keine_beteiligten():
    datei = insilo_ablage.lesen(ablagedatei("x", "T", abschnitte="## Anwesende\n\n- Frau Lohse\n  - **Rolle:** Einkauf\n"))
    assert datei is not None
    assert datei.zusammenfassung == {"anwesende": ["Frau Lohse"]}


def test_fremdes_schema_wird_nicht_geraten():
    assert insilo_ablage.lesen(ablagedatei("x", "T", schema=2)) is None
    assert insilo_ablage.lesen("# Nur Markdown\n") is None
    assert insilo_ablage.lesen('---\ntitle: "ohne Kennung"\nschema: 1\n---\n') is None


def test_wer_liest():
    assert insilo_ablage.wirksam(None, 1) is True
    assert insilo_ablage.wirksam(None, 2) is False, "zwei Organisationen: keine bekommt still die Gespräche"
    assert insilo_ablage.wirksam(True, 2) is True
    assert insilo_ablage.wirksam(False, 1) is False


# ── Der Ordner ──────────────────────────────────────────────────────────


async def test_liest_neu_und_schlaegt_vor(datenbank, ordner):
    async with klient_fuer("ablage-a") as k:
        firma = (await k.post("/api/companies", json={"name": "Meyer Präzisionstechnik"})).json()
        lohse = (await k.post("/api/contacts", json={"first_name": "Katrin", "last_name": "Lohse", "company_id": firma["id"]})).json()
        kennung = str(uuid4())
        _legen(ordner, "2026-09-15T07_20--aaaa1111.md", ablagedatei(kennung, "Abstimmung", abschnitte="## Anwesende\n\n- Frau Lohse\n"))
        (ordner / "2026-09-15T07_21--bbbb2222.md.tmp").write_text("halb", encoding="utf-8")

        bilanz = (await k.post("/api/besprechungen/ablage/lesen")).json()
        assert bilanz["neu"] == 1 and bilanz["dateien"] == 1, "ein .tmp ist ein halb geschriebener Lauf"

        [b] = (await k.get("/api/besprechungen")).json()["eintraege"]
        assert b["status"] == "offen", "auch aus dem Ordner wird nichts ungefragt zugeordnet"
        assert b["vorschlag"]["company"]["id"] == firma["id"]
        assert [x["id"] for x in b["vorschlag"]["kontakte"]] == [lohse["id"]]
        assert b["dauer_sek"] == 32 * 60

        voll = (await k.get(f"/api/besprechungen/{b['id']}")).json()
        assert "Angebot für die Wartung" in voll["protokoll"]
        assert not voll["protokoll"].startswith("---")

        nochmal = (await k.post("/api/besprechungen/ablage/lesen")).json()
        assert (nochmal["neu"], nochmal["geaendert"]) == (0, 0), "unverändert wird nicht neu gelesen"


async def test_geaendert_und_entfernt(datenbank, ordner):
    async with klient_fuer("ablage-b") as k:
        eins, zwei = str(uuid4()), str(uuid4())
        _legen(ordner, "2026-09-10T09_00--eins0000.md", ablagedatei(eins, "Erstes Gespräch"))
        _legen(ordner, "2026-09-11T09_00--zwei0000.md", ablagedatei(zwei, "Zweites Gespräch"))
        await k.post("/api/besprechungen/ablage/lesen")

        # Insilo schreibt eine neu erzeugte Zusammenfassung in dieselbe Datei.
        _legen(ordner, "2026-09-10T09_00--eins0000.md", ablagedatei(eins, "Erstes Gespräch, neu zusammengefasst"))
        bilanz = (await k.post("/api/besprechungen/ablage/lesen")).json()
        assert bilanz["geaendert"] == 1
        titel = sorted(b["titel"] for b in (await k.get("/api/besprechungen")).json()["eintraege"])
        assert titel == ["Erstes Gespräch, neu zusammengefasst", "Zweites Gespräch"]

        # In Insilo gelöscht: die Datei ist weg.
        (ordner / "2026-09-11T09_00--zwei0000.md").unlink()
        bilanz = (await k.post("/api/besprechungen/ablage/lesen")).json()
        assert bilanz["entfernt"] == 1
        assert [b["titel"] for b in (await k.get("/api/besprechungen")).json()["eintraege"]] == [
            "Erstes Gespräch, neu zusammengefasst"
        ]


async def test_leerer_ordner_loescht_nichts(datenbank, ordner):
    """Ein leerer Ordner sieht aus wie einer, der noch nicht gefüllt ist."""
    async with klient_fuer("ablage-c") as k:
        _legen(ordner, "2026-09-10T09_00--leer0000.md", ablagedatei(str(uuid4()), "Bleibt"))
        await k.post("/api/besprechungen/ablage/lesen")
        (ordner / "2026-09-10T09_00--leer0000.md").unlink()

        bilanz = (await k.post("/api/besprechungen/ablage/lesen")).json()
        assert bilanz["entfernt"] == 0
        assert (await k.get("/api/besprechungen")).json()["gesamt"] == 1


async def test_umbenannt_bleibt_eine_besprechung(datenbank, ordner):
    """Eine geänderte Aufnahmezeit ändert den Dateinamen, nicht die Besprechung."""
    async with klient_fuer("ablage-d") as k:
        kennung = str(uuid4())
        _legen(ordner, "2026-09-10T09_00--umbe0000.md", ablagedatei(kennung, "Termin"))
        await k.post("/api/besprechungen/ablage/lesen")
        (ordner / "2026-09-10T09_00--umbe0000.md").unlink()
        _legen(ordner, "2026-09-10T10_30--umbe0000.md", ablagedatei(kennung, "Termin", recorded_at="2026-09-10T10:30:00+00:00"))

        bilanz = (await k.post("/api/besprechungen/ablage/lesen")).json()
        assert bilanz["entfernt"] == 0
        [b] = (await k.get("/api/besprechungen")).json()["eintraege"]
        assert b["recorded_at"].startswith("2026-09-10T10:30")


async def test_webhook_und_ordner_treffen_dieselbe_zeile(datenbank, ordner):
    """Kommt eine Besprechung auf beiden Wegen, bleibt es eine — mit Link."""
    async with klient_fuer("ablage-e") as k:
        quelle = (await k.post("/api/quellen", json={"name": "Insilo", "kind": "insilo"})).json()
        await k.patch(f"/api/quellen/{quelle['id']}", json={"oberflaeche_url": "https://insilo.example.olares.de"})
        kennung = str(uuid4())
        koerper = json.dumps(
            {
                "id": uuid4().hex,
                "event": "meeting.ready",
                "meeting": {"id": kennung, "title": "Doppelt", "recorded_at": "2026-09-10T09:00:00+00:00"},
                "markdown": "# Doppelt\n\nPer Webhook.\n",
                "summary": {"content": {}},
            }
        ).encode()
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as maschine:
            antwort = await maschine.post(
                f"/api/eingang/{quelle['id']}",
                content=koerper,
                headers={
                    "X-Insilo-Event": "meeting.ready",
                    "X-Insilo-Delivery-ID": uuid4().hex,
                    "X-Insilo-Signature": "sha256=" + hmac.new(quelle["secret"].encode(), koerper, hashlib.sha256).hexdigest(),
                },
            )
        assert antwort.status_code == 200

        _legen(ordner, "2026-09-10T09_00--dopp0000.md", ablagedatei(kennung, "Doppelt"))
        await k.post("/api/besprechungen/ablage/lesen")

        [b] = (await k.get("/api/besprechungen")).json()["eintraege"]
        link = (await k.get(f"/api/besprechungen/{b['id']}")).json()["insilo_link"]
    assert link == f"https://insilo.example.olares.de/m/{kennung}", "die Quelle bleibt, der Link auch"


async def test_einstellungen_und_link_ohne_quelle(datenbank, ordner):
    async with klient_fuer("ablage-f") as k:
        stand = (await k.get("/api/besprechungen/ablage")).json()
        assert stand["eingehaengt"] is True and stand["ordner_da"] is True
        assert stand["einstellung"] is None

        falsch = await k.put("/api/besprechungen/ablage", json={"adresse": "javascript:alert(1)"})
        assert falsch.status_code == 422

        stand = (await k.put("/api/besprechungen/ablage", json={"aktiv": True, "adresse": "https://insilo.box.olares.de/"})).json()
        assert stand["aktiv"] is True and stand["einstellung"] is True

        kennung = str(uuid4())
        _legen(ordner, "2026-09-10T09_00--link0000.md", ablagedatei(kennung, "Mit Link"))
        await k.post("/api/besprechungen/ablage/lesen")
        [b] = (await k.get("/api/besprechungen")).json()["eintraege"]
        link = (await k.get(f"/api/besprechungen/{b['id']}")).json()["insilo_link"]
        stand = (await k.get("/api/besprechungen/ablage")).json()

    assert link == f"https://insilo.box.olares.de/m/{kennung}"
    assert stand["uebernommen"] == 1 and stand["dateien"] == 1 and stand["zuletzt"]


async def test_ohne_ordner(datenbank, monkeypatch):
    monkeypatch.setattr(settings, "insilo_ablage_dir", "")
    async with klient_fuer("ablage-g") as k:
        stand = (await k.get("/api/besprechungen/ablage")).json()
        lesen = await k.post("/api/besprechungen/ablage/lesen")
    assert stand["eingehaengt"] is False and stand["aktiv"] is False
    assert lesen.status_code == 409


async def test_fremde_organisation_sieht_nichts(datenbank, ordner):
    async with klient_fuer("ablage-h") as k:
        _legen(ordner, "2026-09-10T09_00--frem0000.md", ablagedatei(str(uuid4()), "Nur für h"))
        await k.post("/api/besprechungen/ablage/lesen")
    async with klient_fuer("ablage-i") as andere:
        assert (await andere.get("/api/besprechungen")).json()["gesamt"] == 0
