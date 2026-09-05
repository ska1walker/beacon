"""Post abholen — die Fälle, die sonst erst im Betrieb auffallen.

Kein echtes Postfach: Geprüft wird die Übersetzung von einer Nachricht in
ein Ticket und die Buchführung darum. Ob `imaplib` verbinden kann, prüft
kein Test, sondern der Knopf „Jetzt abholen".
"""

import email
from datetime import UTC, datetime, timedelta

import pytest

from app import postfach
from tests.conftest import klient_fuer


def nachricht(**kopf) -> email.message.Message:
    roh = kopf.pop("body", "Der Drucker im zweiten Stock streikt.")
    zeilen = {
        "From": "Frau Peters <peters@fremd.de>",
        "Subject": "Drucker streikt",
        "Message-ID": "<abc123@fremd.de>",
        "Date": "Fri, 05 Sep 2026 09:00:00 +0200",
        **kopf,
    }
    text = "".join(f"{k}: {v}\n" for k, v in zeilen.items() if v is not None)
    return email.message_from_string(text + "\n" + roh)


# ---- Übersetzung -------------------------------------------------------

def test_aus_einer_mail_wird_ein_ereignis():
    e = postfach.als_ereignis(nachricht())
    assert e["event"] == "ticket.erstellt"
    assert e["id"] == "<abc123@fremd.de>"
    assert e["ticket"]["betreff"] == "Drucker streikt"
    assert e["ticket"]["absender"] == {"email": "peters@fremd.de", "name": "Frau Peters"}
    assert "zweiten Stock" in e["ticket"]["beschreibung"]


def test_kodierter_betreff_wird_lesbar():
    e = postfach.als_ereignis(nachricht(Subject="=?UTF-8?B?R3LDvMOfZSB2b20gRW1wZmFuZw==?="))
    assert e["ticket"]["betreff"] == "Grüße vom Empfang"


@pytest.mark.parametrize("kopf", [
    {"Auto-Submitted": "auto-replied"},
    {"Precedence": "bulk"},
    {"X-Autoreply": "yes"},
    {"List-Id": "<liste.example.de>"},
    {"From": "MAILER-DAEMON@example.de"},
    {"From": "noreply@shop.de"},
])
def test_automaten_werden_uebergangen(kopf):
    """Eine Abwesenheitsnotiz ist keine Anfrage — und eine Antwort darauf
    wäre der Anfang einer Schleife."""
    assert postfach.als_ereignis(nachricht(**kopf)) is None


def test_ohne_absender_kein_ticket():
    assert postfach.als_ereignis(nachricht(From="")) is None


def test_html_wird_zu_lesbarem_text():
    roh = email.message_from_string(
        "From: a@b.de\nSubject: Test\nMessage-ID: <x@b.de>\n"
        "Content-Type: text/html; charset=utf-8\n\n"
        "<html><style>p{color:red}</style><p>Erste Zeile</p><p>Zweite &amp; letzte</p></html>"
    )
    text = postfach.als_ereignis(roh)["ticket"]["beschreibung"]
    assert "Erste Zeile" in text
    assert "Zweite & letzte" in text
    assert "color:red" not in text
    assert "<p>" not in text


# ---- Der Lauf ----------------------------------------------------------

async def _stelle_post(monkeypatch, nachrichten):
    """Statt eines Postfachs eine Liste — der IMAP-Teil ist hier nicht die Frage."""
    async def abholen(pf):
        return 42, list(enumerate(nachrichten, start=1))

    monkeypatch.setattr(postfach, "abholen", abholen)


async def test_lauf_legt_tickets_an_und_merkt_sich_die_uid(datenbank, monkeypatch):
    async with klient_fuer("post-lauf") as k:
        await k.put("/api/settings", json={
            "imap_host": "imap.example.de", "imap_benutzer": "support@aimighty.de",
            "imap_passwort": "geheim", "imap_aktiv": True,
        })
        await _stelle_post(monkeypatch, [
            nachricht(Subject="Erste", **{"Message-ID": "<1@x.de>"}),
            nachricht(Subject="Zweite", **{"Message-ID": "<2@x.de>"}),
            nachricht(Subject="Abwesend", **{"Message-ID": "<3@x.de>", "Auto-Submitted": "auto-replied"}),
        ])

        bilanz = (await k.post("/api/settings/postfach/abholen")).json()
        assert bilanz == {"gelesen": 3, "tickets": 2, "uebergangen": 1, "doppelt": 0}

        tickets = (await k.get("/api/tickets")).json()
        assert sorted(t["betreff"] for t in tickets) == ["Erste", "Zweite"]
        assert all(t["quelle"] == "email" for t in tickets)
        assert all(t["absender_email"] == "peters@fremd.de" for t in tickets)

        # Der Stand wird gemerkt, damit der nächste Lauf dort weitermacht.
        e = (await k.get("/api/settings")).json()
        assert e["imap_zuletzt"] is not None
        assert e["imap_letzter_fehler"] is None
        assert e["imap_passwort_set"] is True
        assert "imap_passwort" not in e, "das Passwort darf nie zurückkommen"


async def test_dieselbe_nachricht_zweimal_gibt_ein_ticket(datenbank, monkeypatch):
    """Der Abholer darf sich überschneiden, ohne Schaden anzurichten."""
    async with klient_fuer("post-doppelt") as k:
        await k.put("/api/settings", json={
            "imap_host": "imap.example.de", "imap_benutzer": "s@a.de",
            "imap_passwort": "geheim", "imap_aktiv": True,
        })
        await _stelle_post(monkeypatch, [nachricht(Subject="Nur einmal")])

        erste = (await k.post("/api/settings/postfach/abholen")).json()
        zweite = (await k.post("/api/settings/postfach/abholen")).json()
        assert erste["tickets"] == 1
        assert zweite["tickets"] == 0 and zweite["doppelt"] == 1
        assert len((await k.get("/api/tickets")).json()) == 1


async def test_bekannter_absender_haengt_am_kontakt(datenbank, monkeypatch):
    async with klient_fuer("post-kontakt") as k:
        firma = (await k.post("/api/companies", json={"name": "Fremd GmbH"})).json()
        kontakt = (await k.post("/api/contacts", json={
            "first_name": "Ann", "last_name": "Peters",
            "email": "peters@fremd.de", "company_id": firma["id"],
        })).json()
        await k.put("/api/settings", json={
            "imap_host": "imap.example.de", "imap_benutzer": "s@a.de",
            "imap_passwort": "geheim", "imap_aktiv": True,
        })
        await _stelle_post(monkeypatch, [nachricht()])

        await k.post("/api/settings/postfach/abholen")
        t = (await k.get("/api/tickets")).json()[0]
        assert t["contact_id"] == kontakt["id"]
        assert t["company_id"] == firma["id"]


async def test_sla_rechnet_ab_dem_absendedatum(datenbank, monkeypatch):
    async with klient_fuer("post-sla") as k:
        await k.put("/api/settings", json={
            "imap_host": "imap.example.de", "imap_benutzer": "s@a.de",
            "imap_passwort": "geheim", "imap_aktiv": True,
        })
        vorhin = datetime.now(UTC) - timedelta(hours=5)
        await _stelle_post(monkeypatch, [
            nachricht(Date=email.utils.format_datetime(vorhin), Subject="Schon älter")
        ])
        await k.post("/api/settings/postfach/abholen")

        t = (await k.get("/api/tickets")).json()[0]
        rest = (datetime.fromisoformat(t["faellig_am"]) - datetime.now(UTC)).total_seconds() / 3600
        assert 18 < rest < 20, f"{rest} Stunden — erwartet 24 minus 5"


async def test_ohne_zugangsdaten_sagt_es_deutlich(datenbank):
    async with klient_fuer("post-leer") as k:
        antwort = await k.post("/api/settings/postfach/abholen")
        assert antwort.status_code == 502
        assert "Passwort" in antwort.json()["detail"]
