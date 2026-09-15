"""Besprechungen aus Insilo — empfangen, vorschlagen, zuordnen.

Zwei Regeln halten diese Tests fest, beide mit Kai und Marc am 15.9.2026
festgelegt: Beacon behält das Protokoll, **nicht** den Wortlaut. Und nichts
wird ungefragt einem Kunden zugeordnet — auch nicht bei einem eindeutigen
Treffer, und schon gar nicht, wenn zwei Kontakte Meyer heißen.
"""

import hashlib
import hmac
import json
from uuid import uuid4

from httpx import ASGITransport, AsyncClient

from app import besprechungen, sicherung
from app.main import app
from tests.conftest import klient_fuer

WORTLAUT = "Herr Meyer: Wir brauchen das bis Freitag, sonst wird es eng."


def markdown(titel: str, sprecher: list[str]) -> str:
    """So, wie Insilo es schreibt (insilo/backend/app/exports/markdown.py)."""
    zeilen = [
        "---",
        "source: insilo",
        f"title: {titel}",
        "speakers:" if sprecher else "speakers: []",
        *[f"  - {s}" for s in sprecher],
        "---",
        "",
        f"# {titel}",
        "",
        "## Zusammenfassung",
        "",
        "Angebot für die Wartung besprochen, Serverraum im Keller.",
        "",
        "## Aufgaben",
        "",
        "- [ ] Angebot schicken",
        "",
        "## Volltranskript",
        "",
        f"[0:01] **Herr Meyer**: {WORTLAUT}",
        "",
    ]
    return "\n".join(zeilen)


def ereignis(
    titel: str,
    *,
    event: str = "meeting.ready",
    extern: str | None = None,
    sprecher: list[str] | None = None,
    zusammenfassung: dict | None = None,
    recorded_at: str = "2026-09-10T09:00:00+00:00",
) -> bytes:
    return json.dumps(
        {
            "id": uuid4().hex,
            "event": event,
            "occurred_at": "2026-09-15T10:00:00+00:00",
            "meeting": {
                "id": extern or uuid4().hex,
                "title": titel,
                "status": "ready",
                "recorded_at": recorded_at,
                "duration_sec": 1800,
                "template_name": "Vertriebsgespräch",
                "tags": [],
            },
            "markdown": markdown(titel, sprecher or []),
            "summary": {"content": zusammenfassung or {}, "llm_model": "chat"},
        },
        ensure_ascii=False,
    ).encode()


async def _quelle(klient) -> tuple[str, str]:
    q = (await klient.post("/api/quellen", json={"name": "Insilo", "kind": "insilo"})).json()
    return q["id"], q["secret"]


async def _schicken(quelle_id: str, secret: str, koerper: bytes, event: str = "meeting.ready"):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as maschine:
        return await maschine.post(
            f"/api/eingang/{quelle_id}",
            content=koerper,
            headers={
                "X-Insilo-Event": event,
                "X-Insilo-Delivery-ID": uuid4().hex,
                "X-Insilo-Signature": "sha256=" + hmac.new(secret.encode(), koerper, hashlib.sha256).hexdigest(),
            },
        )


async def _kontakt(klient, vor: str, nach: str, firma_id: str | None = None) -> dict:
    return (await klient.post("/api/contacts", json={"first_name": vor, "last_name": nach, "company_id": firma_id})).json()


async def _firma(klient, name: str) -> dict:
    return (await klient.post("/api/companies", json={"name": name})).json()


# ── Aus der Nutzlast ─────────────────────────────────────────────────────


def test_protokoll_ohne_frontmatter_und_ohne_wortlaut():
    protokoll = besprechungen.protokoll_aus(markdown("Termin", ["Herr Meyer"]))
    assert protokoll.startswith("# Termin")
    assert "Angebot schicken" in protokoll
    assert "Volltranskript" not in protokoll
    assert WORTLAUT not in protokoll
    assert "source: insilo" not in protokoll


def test_sprecher_ohne_nummern_und_beteiligte_ohne_doppel():
    sprecher = besprechungen.sprecher_aus(markdown("T", ["Katrin Lohse", "SPEAKER_01", '"Klein, Berater"']))
    assert sprecher == ["Katrin Lohse", "Klein, Berater"]

    beteiligte = besprechungen.beteiligte_aus(
        ["Katrin Lohse"],
        {"anwesende": ["Frau Lohse", "Herr Vogel"], "kunde": "Frau Schäfer (HR-Leitung)"},
    )
    # „Frau Lohse" ist nicht dieselbe Zeichenkette wie „Katrin Lohse",
    # aber Beacon vergleicht erst später — hier wird nur Gleiches entfernt.
    assert "Herr Vogel" in beteiligte
    assert "Frau Schäfer" in beteiligte
    assert beteiligte.count("Katrin Lohse") == 1


# ── Empfangen ────────────────────────────────────────────────────────────


async def test_fertige_besprechung_ohne_wortlaut(datenbank):
    """Der Wortlaut bleibt in Insilo — auch nicht versteckt in einer Spalte."""
    async with klient_fuer("besp-a") as k:
        quelle_id, secret = await _quelle(k)
        antwort = await _schicken(quelle_id, secret, ereignis("Wartung Serverraum", sprecher=["Herr Meyer"]))
        assert antwort.status_code == 200, antwort.text

        seite = (await k.get("/api/besprechungen")).json()
        assert seite["gesamt"] == 1
        voll = (await k.get(f"/api/besprechungen/{seite['eintraege'][0]['id']}")).json()

    assert voll["titel"] == "Wartung Serverraum"
    assert voll["dauer_sek"] == 1800
    assert voll["recorded_at"].startswith("2026-09-10")
    assert WORTLAUT not in json.dumps(voll, ensure_ascii=False)
    assert "Volltranskript" not in voll["protokoll"]


async def test_zwischenstaende_legen_nichts_an(datenbank):
    """„angelegt" und „fehlgeschlagen" sind Zustände in Insilo, kein Gespräch."""
    async with klient_fuer("besp-b") as k:
        quelle_id, secret = await _quelle(k)
        for event in ("meeting.created", "meeting.failed", "test.ping"):
            antwort = await _schicken(quelle_id, secret, ereignis("x", event=event), event=event)
            assert antwort.status_code == 200
        assert (await k.get("/api/besprechungen")).json()["gesamt"] == 0
        assert (await k.get("/api/eingang")).json() == []


async def test_wiederholung_und_neue_zusammenfassung(datenbank):
    """Dieselbe Besprechung zweimal ist eine Zeile — mit dem neueren Protokoll."""
    async with klient_fuer("besp-c") as k:
        quelle_id, secret = await _quelle(k)
        firma = await _firma(k, "Brinkmann Baustoffe")
        extern = uuid4().hex

        await _schicken(quelle_id, secret, ereignis("Termin Brinkmann Baustoffe", extern=extern))
        [b] = (await k.get("/api/besprechungen")).json()["eintraege"]
        await k.post(f"/api/besprechungen/{b['id']}/zuordnen", json={"company_id": firma["id"]})

        # Insilo erzeugt die Zusammenfassung neu und schickt noch einmal.
        neu = json.loads(ereignis("Termin Brinkmann Baustoffe — überarbeitet", extern=extern))
        neu["markdown"] = neu["markdown"].replace("Serverraum im Keller", "Serverraum im Erdgeschoss")
        await _schicken(quelle_id, secret, json.dumps(neu, ensure_ascii=False).encode())

        seite = (await k.get("/api/besprechungen")).json()
        verlauf = (await k.get(f"/api/activities?company_id={firma['id']}")).json()

    assert seite["gesamt"] == 1
    assert seite["eintraege"][0]["status"] == "zugeordnet"
    [aktivitaet] = [a for a in verlauf if a["kind"] == "meeting"]
    assert "Erdgeschoss" in aktivitaet["body"]
    assert aktivitaet["subject"].endswith("überarbeitet")


async def test_in_insilo_geloescht(datenbank):
    async with klient_fuer("besp-d") as k:
        quelle_id, secret = await _quelle(k)
        firma = await _firma(k, "Löschfirma")
        extern = uuid4().hex
        await _schicken(quelle_id, secret, ereignis("Termin", extern=extern))
        [b] = (await k.get("/api/besprechungen")).json()["eintraege"]
        await k.post(f"/api/besprechungen/{b['id']}/zuordnen", json={"company_id": firma["id"]})

        await _schicken(quelle_id, secret, ereignis("Termin", event="meeting.deleted", extern=extern), event="meeting.deleted")

        assert (await k.get("/api/besprechungen")).json()["gesamt"] == 0
        verlauf = (await k.get(f"/api/activities?company_id={firma['id']}")).json()
        assert [a for a in verlauf if a["kind"] == "meeting"] == []


# ── Vorschlagen ──────────────────────────────────────────────────────────


async def test_eindeutiger_treffer_wird_vorgeschlagen_nicht_zugeordnet(datenbank):
    """„Frau Lohse" im Gespräch, Katrin Lohse im Bestand — vorausgewählt, nicht zugeordnet."""
    async with klient_fuer("besp-e") as k:
        quelle_id, secret = await _quelle(k)
        firma = await _firma(k, "Meyer Präzisionstechnik")
        lohse = await _kontakt(k, "Katrin", "Lohse", firma["id"])
        deal = (await k.post("/api/deals", json={"name": "Wartungsvertrag", "company_id": firma["id"]})).json()

        await _schicken(quelle_id, secret, ereignis("Abstimmung", zusammenfassung={"anwesende": ["Frau Lohse", "Berater Klein"]}))
        [b] = (await k.get("/api/besprechungen")).json()["eintraege"]

    assert b["status"] == "offen", "nichts wird ungefragt zugeordnet"
    v = b["vorschlag"]
    assert v["quelle"] == "namen"
    assert v["company"]["id"] == firma["id"]
    assert [x["id"] for x in v["kontakte"]] == [lohse["id"]]
    assert v["deal"]["id"] == deal["id"]
    assert v["mehrdeutig"] is False


async def test_zwei_meyers_werden_nicht_vorausgewaehlt(datenbank):
    """Marcs Einwand gegen die Vollautomatik, als Test."""
    async with klient_fuer("besp-f") as k:
        quelle_id, secret = await _quelle(k)
        a = await _firma(k, "Holzbau Nord")
        b = await _firma(k, "Steuerkanzlei Süd")
        await _kontakt(k, "Klaus", "Meyer", a["id"])
        await _kontakt(k, "Petra", "Meyer", b["id"])

        await _schicken(quelle_id, secret, ereignis("Kurzes Telefonat", sprecher=["Herr Meyer"]))
        [besprechung] = (await k.get("/api/besprechungen")).json()["eintraege"]

    v = besprechung["vorschlag"]
    assert v["mehrdeutig"] is True
    assert v["company"] is None and v["kontakte"] == []
    assert {x["company_name"] for x in v["kandidaten"]} == {"Holzbau Nord", "Steuerkanzlei Süd"}
    assert "Meyer" in v["grund"]


async def test_vorname_loest_die_mehrdeutigkeit(datenbank):
    async with klient_fuer("besp-g") as k:
        quelle_id, secret = await _quelle(k)
        a = await _firma(k, "Holzbau Nord")
        await _kontakt(k, "Klaus", "Meyer", a["id"])
        anna = await _kontakt(k, "Anna", "Meyer", (await _firma(k, "Kanzlei West"))["id"])

        await _schicken(quelle_id, secret, ereignis("Telefonat", sprecher=["Anna Meyer"]))
        [b] = (await k.get("/api/besprechungen")).json()["eintraege"]

    assert [x["id"] for x in b["vorschlag"]["kontakte"]] == [anna["id"]]


async def test_andere_hinweise_loesen_die_mehrdeutigkeit(datenbank):
    """Steht die Firma im Titel, zählt nur der Meyer dieser Firma."""
    async with klient_fuer("besp-h") as k:
        quelle_id, secret = await _quelle(k)
        nord = await _firma(k, "Holzbau Nord")
        klaus = await _kontakt(k, "Klaus", "Meyer", nord["id"])
        await _kontakt(k, "Petra", "Meyer", (await _firma(k, "Steuerkanzlei Süd"))["id"])

        await _schicken(quelle_id, secret, ereignis("Baubesprechung Holzbau Nord", sprecher=["Herr Meyer"]))
        [b] = (await k.get("/api/besprechungen")).json()["eintraege"]

    assert b["vorschlag"]["company"]["id"] == nord["id"]
    assert [x["id"] for x in b["vorschlag"]["kontakte"]] == [klaus["id"]]


async def test_kein_treffer_ohne_modell_ist_kein_fehler(datenbank):
    async with klient_fuer("besp-i") as k:
        quelle_id, secret = await _quelle(k)
        antwort = await _schicken(quelle_id, secret, ereignis("Irgendein Gespräch", sprecher=["Herr Unbekannt"]))
        [b] = (await k.get("/api/besprechungen")).json()["eintraege"]

    assert antwort.status_code == 200
    assert b["vorschlag"]["company"] is None
    assert "Kein genannter Name" in b["vorschlag"]["grund"]


async def test_modell_waehlt_nur_aus_der_kandidatenliste(datenbank, monkeypatch):
    """Eine erfundene Kennung ist nur eine Kennung von einem falschen Kunden entfernt."""
    from app.db import acquire_as
    from app.llm import LLMConfig

    async with klient_fuer("besp-j") as k:
        quelle_id, secret = await _quelle(k)
        firma = await _firma(k, "Nordwind Logistik")
        await _schicken(quelle_id, secret, ereignis("Lagerlogistik Nordwind besprochen"))
        [b] = (await k.get("/api/besprechungen")).json()["eintraege"]
        wer = (await k.get("/api/mitglieder/wer")).json()

        async def cfg(conn, org_id):
            return LLMConfig(base_url="http://modell.local/v1", api_key="", model="test")

        monkeypatch.setattr(besprechungen, "load_llm_config", cfg)

        async def fremd(*a, **kw):
            return json.dumps({"company_id": str(uuid4()), "contact_ids": [], "grund": "geraten"})

        monkeypatch.setattr(besprechungen, "chat", fremd)
        async with acquire_as(wer["user_id"]) as conn:
            assert await besprechungen.vorschlag_ueber_modell(conn, wer["org_id"], b["id"]) is None

        async def richtig(*a, **kw):
            return json.dumps({"company_id": firma["id"], "contact_ids": [str(uuid4())], "grund": "Nordwind im Titel"})

        monkeypatch.setattr(besprechungen, "chat", richtig)
        async with acquire_as(wer["user_id"]) as conn:
            v = await besprechungen.vorschlag_ueber_modell(conn, wer["org_id"], b["id"])

        [nachher] = (await k.get("/api/besprechungen")).json()["eintraege"]

    assert v["company_id"] == firma["id"]
    assert v["contact_ids"] == [], "ein Kontakt außerhalb der Liste fällt weg"
    assert nachher["vorschlag"]["quelle"] == "modell"
    assert nachher["status"] == "offen"


# ── Zuordnen ─────────────────────────────────────────────────────────────


async def test_zuordnen_steht_an_jedem_kontakt_und_einmal_an_der_firma(datenbank):
    async with klient_fuer("besp-k") as k:
        quelle_id, secret = await _quelle(k)
        firma = await _firma(k, "Dreierfirma")
        a = await _kontakt(k, "Anna", "Eins", firma["id"])
        b = await _kontakt(k, "Bernd", "Zwei", firma["id"])
        c = await _kontakt(k, "Clara", "Drei", firma["id"])

        await _schicken(quelle_id, secret, ereignis("Runde mit dreien", recorded_at="2026-08-01T08:30:00+00:00"))
        [besp] = (await k.get("/api/besprechungen")).json()["eintraege"]

        antwort = await k.post(
            f"/api/besprechungen/{besp['id']}/zuordnen",
            json={"company_id": firma["id"], "contact_ids": [a["id"], b["id"], c["id"]]},
        )
        assert antwort.status_code == 200, antwort.text
        assert antwort.json()["status"] == "zugeordnet"
        assert len(antwort.json()["kontakte"]) == 3

        an_firma = [x for x in (await k.get(f"/api/activities?company_id={firma['id']}")).json() if x["kind"] == "meeting"]
        je_kontakt = [
            [x for x in (await k.get(f"/api/activities?contact_id={p['id']}")).json() if x["kind"] == "meeting"]
            for p in (a, b, c)
        ]

    assert len(an_firma) == 1
    assert an_firma[0]["occurred_at"].startswith("2026-08-01")
    assert all(len(x) == 1 for x in je_kontakt)


async def test_umhaengen_und_loesen(datenbank):
    async with klient_fuer("besp-l") as k:
        quelle_id, secret = await _quelle(k)
        erst = await _firma(k, "Erste Firma")
        zweit = await _firma(k, "Zweite Firma")
        await _schicken(quelle_id, secret, ereignis("Termin"))
        [b] = (await k.get("/api/besprechungen")).json()["eintraege"]

        await k.post(f"/api/besprechungen/{b['id']}/zuordnen", json={"company_id": erst["id"]})
        await k.post(f"/api/besprechungen/{b['id']}/zuordnen", json={"company_id": zweit["id"]})
        an_erst = [x for x in (await k.get(f"/api/activities?company_id={erst['id']}")).json() if x["kind"] == "meeting"]
        an_zweit = [x for x in (await k.get(f"/api/activities?company_id={zweit['id']}")).json() if x["kind"] == "meeting"]
        assert (len(an_erst), len(an_zweit)) == (0, 1)

        geloest = (await k.post(f"/api/besprechungen/{b['id']}/loesen")).json()
        assert geloest["status"] == "offen"
        assert [x for x in (await k.get(f"/api/activities?company_id={zweit['id']}")).json() if x["kind"] == "meeting"] == []

        # Und wieder zuordnen geht — der gelöschte Eintrag steht nicht im Weg.
        wieder = await k.post(f"/api/besprechungen/{b['id']}/zuordnen", json={"company_id": erst["id"]})
        assert wieder.status_code == 200


async def test_fremde_firma_und_fremde_besprechung(datenbank):
    async with klient_fuer("besp-m") as a, klient_fuer("besp-n") as fremd:
        quelle_id, secret = await _quelle(a)
        await _schicken(quelle_id, secret, ereignis("Vertraulich"))
        [b] = (await a.get("/api/besprechungen")).json()["eintraege"]
        fremde_firma = await _firma(fremd, "Fremdfirma")

        falsch = await a.post(f"/api/besprechungen/{b['id']}/zuordnen", json={"company_id": fremde_firma["id"]})
        assert falsch.status_code == 404

        assert (await fremd.get("/api/besprechungen")).json()["gesamt"] == 0
        assert (await fremd.get(f"/api/besprechungen/{b['id']}")).status_code == 404


# ── Liste ────────────────────────────────────────────────────────────────


async def test_suche_zeitraum_und_zaehler(datenbank):
    async with klient_fuer("besp-o") as k:
        quelle_id, secret = await _quelle(k)
        firma = await _firma(k, "Suchfirma")
        await _schicken(quelle_id, secret, ereignis("Frühjahr", recorded_at="2026-03-01T09:00:00+00:00"))
        await _schicken(quelle_id, secret, ereignis("Sommer", recorded_at="2026-07-01T09:00:00+00:00"))
        [sommer] = [b for b in (await k.get("/api/besprechungen")).json()["eintraege"] if b["titel"] == "Sommer"]
        await k.post(f"/api/besprechungen/{sommer['id']}/zuordnen", json={"company_id": firma["id"]})

        # Ein Wort aus dem Protokoll, nicht aus dem Titel.
        assert (await k.get("/api/besprechungen?q=Serverraum")).json()["gesamt"] == 2
        assert (await k.get("/api/besprechungen?q=Somm")).json()["gesamt"] == 1
        assert (await k.get("/api/besprechungen?von=2026-06-01")).json()["gesamt"] == 1
        assert (await k.get("/api/besprechungen?status=offen")).json()["eintraege"][0]["titel"] == "Frühjahr"
        zahlen = (await k.get("/api/besprechungen/anzahl")).json()

    assert zahlen == {"offen": 1, "zugeordnet": 1, "alle": 2}


async def test_link_nach_insilo(datenbank):
    async with klient_fuer("besp-p") as k:
        quelle = (await k.post("/api/quellen", json={"name": "Insilo", "kind": "insilo"})).json()
        extern = uuid4().hex
        await _schicken(quelle["id"], quelle["secret"], ereignis("Termin", extern=extern))
        [b] = (await k.get("/api/besprechungen")).json()["eintraege"]
        assert (await k.get(f"/api/besprechungen/{b['id']}")).json()["insilo_link"] is None

        falsch = await k.patch(f"/api/quellen/{quelle['id']}", json={"oberflaeche_url": "javascript:alert(1)"})
        assert falsch.status_code == 400
        await k.patch(f"/api/quellen/{quelle['id']}", json={"oberflaeche_url": "https://insilo.example.olares.de/"})
        link = (await k.get(f"/api/besprechungen/{b['id']}")).json()["insilo_link"]

    assert link == f"https://insilo.example.olares.de/m/{extern}"


def test_beide_tabellen_stehen_in_der_sicherung():
    assert "besprechungen" in sicherung.TABELLEN
    assert "besprechung_kontakte" in sicherung.TABELLEN
    assert sicherung.TABELLEN.index("besprechungen") > sicherung.TABELLEN.index("activities")


def _umzug_sql() -> str:
    """Nur der Umzugsteil der Migration 0030."""
    import pathlib

    sql = (pathlib.Path(__file__).resolve().parents[2] / "supabase" / "migrations" / "0030_besprechungen.sql").read_text()
    return sql[sql.index("-- ── Umzug aus dem Eingang"):]


async def test_umzug_aus_dem_eingang(datenbank):
    """Die Migration 0030 holt alte Insilo-Posten aus dem Eingang.

    Die Tests spielen alle Migrationen auf eine leere Datenbank — der Umzug
    liefe dort nie. Also werden hier alte Posten angelegt und nur der
    Umzugsteil noch einmal ausgeführt. Gerade der hätte auf der Box still
    nichts getan: FORCE aus 0002 gilt auch für die Eigentümerin der Tabellen.
    """
    from app.db import acquire

    async with klient_fuer("besp-umzug") as k:
        quelle_id, _ = await _quelle(k)
        firma = await _firma(k, "Altfirma")
        wer = (await k.get("/api/mitglieder/wer")).json()

    umzug = _umzug_sql()

    async with acquire() as conn:
        # Wie bis 0.9.9: ein zugeordneter Posten mit Aktivität, ein offener,
        # ein Zwischenstand — und die Aktivität trägt noch den Wortlaut.
        await conn.execute("alter table public.activities disable row level security")
        await conn.execute("alter table public.eingang disable row level security")
        aktivitaet = await conn.fetchval(
            "insert into public.activities (org_id, kind, subject, body, company_id, external_source, external_id) "
            "values ($1, 'meeting', 'Alt', $2, $3, 'insilo', 'alt-1') returning id",
            wer["org_id"], markdown("Alt", ["Herr Meyer"]), firma["id"],
        )
        for extern, event, akt in (("alt-1", "meeting.ready", aktivitaet), ("alt-2", "meeting.ready", None), ("alt-3", "meeting.created", None)):
            await conn.execute(
                "insert into public.eingang (org_id, source_id, delivery_id, event, external_id, titel, markdown, payload, activity_id, company_id) "
                "values ($1,$2,$3,$4,$5,$6,$7,$8::jsonb,$9,$10)",
                wer["org_id"], quelle_id, uuid4().hex, event, extern, f"Posten {extern}", markdown("Alt", []),
                json.dumps({"meeting": {"id": extern, "recorded_at": "2026-05-05T10:00:00+00:00", "duration_sec": 600}}),
                akt, firma["id"] if akt else None,
            )
        await conn.execute("alter table public.activities enable row level security")
        await conn.execute("alter table public.eingang enable row level security")

        await conn.execute(umzug)

    async with klient_fuer("besp-umzug") as k:
        seite = (await k.get("/api/besprechungen?status=alle")).json()
        verlauf = (await k.get(f"/api/activities?company_id={firma['id']}")).json()
        eingang = (await k.get("/api/eingang")).json()

    nach_titel = {b["titel"]: b for b in seite["eintraege"]}
    assert set(nach_titel) == {"Posten alt-1", "Posten alt-2"}
    assert nach_titel["Posten alt-1"]["status"] == "zugeordnet"
    assert nach_titel["Posten alt-2"]["status"] == "offen"
    assert nach_titel["Posten alt-2"]["recorded_at"].startswith("2026-05-05")
    assert eingang == []
    [alt] = [a for a in verlauf if a["kind"] == "meeting"]
    assert WORTLAUT not in alt["body"], "der Wortlaut muss auch aus den alten Aktivitäten"
    assert alt["payload"]["besprechung_id"] == nach_titel["Posten alt-1"]["id"]
