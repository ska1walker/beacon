"""Versand — was sonst erst beim ersten Kunden auffällt.

Kein echter Mailserver: Geprüft wird, was in der Mail steht (Faden,
Abmeldelink, gefüllte Platzhalter), was das Buch danach sagt (gesendet,
fehlgeschlagen, wartend) und was am Kontakt und am Ticket passiert. Ob
`smtplib` verbinden kann, prüft kein Test, sondern der Knopf „Testmail“.
"""

import json
import re
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from app import versand
from app.config import settings
from app.db import acquire, acquire_as
from app.oeffentlich import app as oeffentlich
from tests.conftest import klient_fuer

SMTP = {
    "smtp_host": "mail.example.de", "smtp_port": 587, "smtp_benutzer": "kai@aimighty.de",
    "smtp_passwort": "geheim", "smtp_sicherheit": "starttls",
    "smtp_absender": "kai@aimighty.de", "smtp_absender_name": "Kai Böhm",
    "links_basis_url": "https://links.test",
}


class Briefkasten:
    """Nimmt entgegen, was hinausgegangen wäre."""

    def __init__(self, fehler: Exception | None = None):
        self.nachrichten = []
        self.fehler = fehler

    async def __call__(self, konto, nachricht):
        if self.fehler:
            raise self.fehler
        self.nachrichten.append((konto, nachricht))


@pytest.fixture
def briefkasten(monkeypatch):
    b = Briefkasten()
    monkeypatch.setattr(versand, "senden_smtp", b)
    return b


async def _kontakt(klient, **felder):
    antwort = await klient.post("/api/contacts", json={
        "first_name": "Ann", "last_name": "Peters",
        "email": f"peters-{uuid4().hex[:8]}@fremd.de", **felder,
    })
    assert antwort.status_code == 201, antwort.text
    return antwort.json()


async def _draussen():
    return AsyncClient(transport=ASGITransport(app=oeffentlich), base_url="http://links.test")


# ---- Platzhalter und Adresse -------------------------------------------

def test_platzhalter_werden_gefuellt_und_unbekannte_leer():
    werte = versand.platzhalter_aus({"first_name": "Ann", "last_name": "Peters", "company_name": "Fremd GmbH"})
    text = versand.rendern("{{anrede}}, {{ firma }} — {{unbekannt}}|{{VORNAME}}", werte)
    assert text == "Guten Tag Ann Peters, Fremd GmbH — |Ann"


def test_anrede_ohne_namen_bleibt_hoeflich():
    assert versand.platzhalter_aus({"email": "x@y.de"})["anrede"] == "Guten Tag"


def test_basis_url_aus_der_box_domain(monkeypatch):
    """Olares nennt dem Chart die Domain des ersten Entrance; der
    öffentliche ist Index 1 derselben Kennung (gemessen, docs/BETRIEB.md)."""
    monkeypatch.setattr(settings, "app_domain", "41b89d100.kaivostudio.olares.de")
    assert versand.basis_url({}) == "https://41b89d101.kaivostudio.olares.de"
    assert versand.appid() == "41b89d10"
    # Ein eigener Wert gewinnt, ohne Schrägstrich am Ende.
    assert versand.basis_url({"links_basis_url": "https://links.firma.de/"}) == "https://links.firma.de"


def test_ohne_domain_keine_adresse(monkeypatch):
    monkeypatch.setattr(settings, "app_domain", "")
    assert versand.basis_url({}) is None


def test_nachricht_traegt_faden_und_abmeldung():
    konto = versand.smtp_aus(SMTP)
    m = versand.nachricht_bauen(
        an="a@b.de", betreff="AW: Drucker", text="Hallo", konto=konto, message_id="<neu@aimighty.de>",
        in_reply_to="<abc@fremd.de>", abmelde_url="https://links.test/o/abmelden/t",
    )
    assert m["In-Reply-To"] == "<abc@fremd.de>"
    assert m["References"] == "<abc@fremd.de>"
    assert m["List-Unsubscribe"] == "<https://links.test/o/abmelden/t>"
    assert m["From"] == "Kai Böhm <kai@aimighty.de>"
    assert m.get_content().strip() == "Hallo"


def test_ohne_konto_kein_smtp():
    assert versand.smtp_aus({"smtp_host": "x"}) is None
    assert versand.smtp_aus({"smtp_host": "x", "smtp_absender": "a@b.de", "smtp_sicherheit": "quatsch"}).sicherheit == "starttls"


# ---- Einstellungen -----------------------------------------------------

async def test_passwort_geht_hinein_und_nie_zurueck(datenbank):
    async with klient_fuer("vers-einst") as k:
        e = (await k.put("/api/settings", json=SMTP)).json()
        assert e["smtp_passwort_set"] is True
        assert e["smtp_ready"] is True
        assert "smtp_passwort" not in e
        assert e["links_basis_wirksam"] == "https://links.test"
        # Leer gesendet heißt „nicht angefasst“.
        e = (await k.put("/api/settings", json={"smtp_passwort": "", "smtp_host": "neu.example.de"})).json()
        assert e["smtp_passwort_set"] is True
        assert e["smtp_host"] == "neu.example.de"


async def test_testmail_ohne_konto_sagt_das(datenbank):
    async with klient_fuer("vers-leer") as k:
        antwort = await k.post("/api/settings/versand/testen")
        assert antwort.status_code == 409
        assert "SMTP" in antwort.json()["detail"]


async def test_testmail_geht_an_den_absender(datenbank, briefkasten):
    async with klient_fuer("vers-test") as k:
        await k.put("/api/settings", json=SMTP)
        antwort = await k.post("/api/settings/versand/testen")
        assert antwort.status_code == 200, antwort.text
        assert antwort.json()["an"] == "kai@aimighty.de"
        konto, m = briefkasten.nachrichten[-1]
        assert konto.host == "mail.example.de"
        assert m["To"] == "kai@aimighty.de"


# ---- Double-Opt-In -----------------------------------------------------

async def test_anfragen_schickt_link_und_der_link_bestaetigt(datenbank, briefkasten):
    async with klient_fuer("vers-doi") as k:
        await k.put("/api/settings", json=SMTP)
        kontakt = await _kontakt(k)
        antwort = await k.post(f"/api/contacts/{kontakt['id']}/einwilligung", json={"aktion": "anfragen"})
        assert antwort.status_code == 200, antwort.text
        assert antwort.json()["marketing_einwilligung"] == "angefragt"
        assert antwort.json()["einwilligung_quelle"] == "double-opt-in"

        _, m = briefkasten.nachrichten[-1]
        text = m.get_content()
        assert "Guten Tag Ann Peters" in text
        assert "{{" not in text
        link = re.search(r"https://links\.test/o/bestaetigen/(\S+)", text)
        assert link, text
        assert m["Subject"] == versand.DOI_BETREFF

        async with await _draussen() as d:
            seite = await d.get(f"/o/bestaetigen/{link.group(1)}")
        assert seite.status_code == 200
        kontakt = (await k.get(f"/api/contacts/{kontakt['id']}")).json()
        assert kontakt["marketing_einwilligung"] == "bestaetigt"
        assert kontakt["einwilligung_quelle"] == "double-opt-in"

        # Und im Buch steht die Mail als gesendet.
        async with acquire_as(await conn_nutzer(k)) as conn:
            z = await conn.fetchrow("select status::text, message_id from public.mails where contact_id = $1", kontakt["id"])
        assert z["status"] == "gesendet"
        assert z["message_id"].startswith("<")


async def test_eigene_vorlage_wird_benutzt(datenbank, briefkasten):
    async with klient_fuer("vers-vorlage") as k:
        await k.put("/api/settings", json={**SMTP, "doi_betreff": "Kurz bestätigen, {{vorname}}",
                                           "doi_text": "Hier: {{bestaetigungslink}}"})
        kontakt = await _kontakt(k)
        await k.post(f"/api/contacts/{kontakt['id']}/einwilligung", json={"aktion": "anfragen"})
        _, m = briefkasten.nachrichten[-1]
        assert m["Subject"] == "Kurz bestätigen, Ann"
        assert m.get_content().startswith("Hier: https://links.test/o/bestaetigen/")


async def test_anfragen_ohne_adresse_der_links_sagt_das(datenbank, briefkasten, monkeypatch):
    monkeypatch.setattr(settings, "app_domain", "")
    async with klient_fuer("vers-ohne-basis") as k:
        await k.put("/api/settings", json={**SMTP, "links_basis_url": None})
        kontakt = await _kontakt(k)
        antwort = await k.post(f"/api/contacts/{kontakt['id']}/einwilligung", json={"aktion": "anfragen"})
        assert antwort.status_code == 409
        assert "Adresse der öffentlichen Links" in antwort.json()["detail"]
        assert briefkasten.nachrichten == []


async def test_bestandskunde_wird_gesetzt_und_belegt(datenbank):
    async with klient_fuer("vers-bestand") as k:
        kontakt = await _kontakt(k)
        k2 = (await k.post(f"/api/contacts/{kontakt['id']}/einwilligung", json={"aktion": "bestandskunde"})).json()
        assert k2["marketing_einwilligung"] == "bestandskunde"
        assert k2["einwilligung_am"]
        assert "§7" in k2["einwilligung_nachweis"]["grund"]
        k3 = (await k.post(f"/api/contacts/{kontakt['id']}/einwilligung", json={"aktion": "keine"})).json()
        assert k3["marketing_einwilligung"] == "keine"
        assert k3["einwilligung_am"] is None


# ---- Ticket-Antwort ----------------------------------------------------

async def test_antwort_haengt_am_faden_und_setzt_die_uhr(datenbank, briefkasten):
    async with klient_fuer("vers-ticket") as k:
        await k.put("/api/settings", json=SMTP)
        kontakt = await _kontakt(k)
        t = (await k.post("/api/tickets", json={"betreff": "Drucker streikt", "contact_id": kontakt["id"]})).json()
        assert t["erste_antwort_am"] is None

        antwort = await k.post(f"/api/tickets/{t['id']}/antworten", json={"text": "Wir kümmern uns."})
        assert antwort.status_code == 200, antwort.text
        t2 = antwort.json()
        assert t2["erste_antwort_am"]
        assert t2["stufe_art"] == "wartet_auf_kontakt"

        _, m = briefkasten.nachrichten[-1]
        assert m["To"] == kontakt["email"]
        assert m["Subject"] == f"AW: Drucker streikt [{t['kennung']}]"
        assert m["In-Reply-To"] is None  # von Hand angelegt — keine Anfrage-Mail

        verlauf = (await k.get(f"/api/activities?ticket_id={t['id']}")).json()
        mail = next(a for a in verlauf if a["kind"] == "email")
        assert mail["payload"]["richtung"] == "ausgehend"
        assert mail["payload"]["message_id"] == m["Message-ID"]


async def test_antwort_ohne_adresse_und_ohne_konto(datenbank, briefkasten):
    async with klient_fuer("vers-ticket-leer") as k:
        t = (await k.post("/api/tickets", json={"betreff": "Ohne Absender"})).json()
        antwort = await k.post(f"/api/tickets/{t['id']}/antworten", json={"text": "Hallo?"})
        assert antwort.status_code == 409
        assert "keine Adresse" in antwort.json()["detail"]

        kontakt = await _kontakt(k)
        t = (await k.post("/api/tickets", json={"betreff": "Mit Kontakt", "contact_id": kontakt["id"]})).json()
        antwort = await k.post(f"/api/tickets/{t['id']}/antworten", json={"text": "Hallo?"})
        assert antwort.status_code == 409
        assert "SMTP" in antwort.json()["detail"]
        assert briefkasten.nachrichten == []


async def test_abgelehnter_versand_bleibt_im_buch(datenbank, monkeypatch):
    kaputt = Briefkasten(fehler=ConnectionRefusedError("verbindung abgelehnt"))
    monkeypatch.setattr(versand, "senden_smtp", kaputt)
    async with klient_fuer("vers-kaputt") as k:
        await k.put("/api/settings", json=SMTP)
        kontakt = await _kontakt(k)
        t = (await k.post("/api/tickets", json={"betreff": "Kaputt", "contact_id": kontakt["id"]})).json()
        antwort = await k.post(f"/api/tickets/{t['id']}/antworten", json={"text": "Test"})
        assert antwort.status_code == 502
        assert "verbindung abgelehnt" in antwort.json()["detail"]
        e = (await k.get("/api/settings")).json()
        assert "verbindung abgelehnt" in e["smtp_letzter_fehler"]
        async with acquire_as(await conn_nutzer(k)) as conn:
            z = await conn.fetchrow("select status::text, versuche, fehler from public.mails where ticket_id = $1", t["id"])
        assert z["status"] == "wartend"  # der erste von drei Versuchen
        assert z["versuche"] == 1
        # Die erste Antwort zählt nicht, was nie ankam.
        assert (await k.get(f"/api/tickets/{t['id']}")).json()["erste_antwort_am"] is None


# ---- Der Lauf ----------------------------------------------------------

async def test_lauf_schickt_wartendes_und_haengt_marketing_die_abmeldung_an(datenbank, briefkasten):
    async with klient_fuer("vers-lauf") as k:
        await k.put("/api/settings", json=SMTP)
        kontakt = await _kontakt(k)
        nutzer = await conn_nutzer(k)
        async with acquire_as(nutzer) as conn:
            org = await conn.fetchval("select org_id from public.contacts where id = $1", kontakt["id"])
            await versand.einreihen(conn, org, art="marketing", an=kontakt["email"], betreff="Neu bei uns",
                                    text="Hallo {{vorname}}", contact_id=kontakt["id"])
            bilanz = await versand.verarbeiten(conn, org, sender=briefkasten)
        assert bilanz == {"gesendet": 1, "gescheitert": 0}
        _, m = briefkasten.nachrichten[-1]
        assert m["List-Unsubscribe"].startswith("<https://links.test/o/abmelden/")
        text = m.get_content()
        assert "abmelden: https://links.test/o/abmelden/" in text

        # Und der Link darin meldet wirklich ab.
        token = re.search(r"/o/abmelden/(\S+)", text).group(1)
        async with await _draussen() as d:
            assert (await d.get(f"/o/abmelden/{token}")).status_code == 200
        assert (await k.get(f"/api/contacts/{kontakt['id']}")).json()["marketing_einwilligung"] == "abgemeldet"


async def conn_nutzer(klient):
    async with acquire() as conn:
        return await conn.fetchval(
            "select id from public.users where olares_username = $1", klient.headers["X-Bfl-User"]
        )


async def test_schleifen_finden_wartende_mails_und_faellige_postfaecher(datenbank):
    """`mails` und `org_settings` stehen unter FORCE ROW LEVEL SECURITY.
    Die Schleifen fragten ohne Nutzerkontext — und fanden nie etwas."""
    from app.main import _post_faellig, _versand_offen

    async with klient_fuer("vers-schleife") as k:
        kontakt = await _kontakt(k)
        nutzer = await conn_nutzer(k)
        async with acquire_as(nutzer) as conn:
            org = await conn.fetchval("select org_id from public.contacts where id = $1", kontakt["id"])
            await versand.einreihen(conn, org, art="transaktional", an=kontakt["email"], betreff="Hallo", text="Text")
        assert org in [o["org_id"] for o in await _versand_offen()]
        assert org not in [o["org_id"] for o in await _post_faellig()]
        await k.put("/api/settings", json={"imap_host": "imap.test", "imap_benutzer": "x", "imap_passwort": "y", "imap_aktiv": True})
        assert org in [o["org_id"] for o in await _post_faellig()]


# ── Jeder unter seinem eigenen Namen ────────────────────────────────────


def test_ohne_eigene_adresse_bleibt_es_beim_haus():
    haus = {"smtp_host": "send.one.com", "smtp_absender": "kai.boehm@aimighty.de",
            "smtp_absender_name": "Kai Böhm", "smtp_benutzer": "kai.boehm@aimighty.de"}
    assert versand.smtp_fuer(haus, None).absender == "kai.boehm@aimighty.de"
    assert versand.smtp_fuer(haus, {"absender_email": ""}).absender == "kai.boehm@aimighty.de"


def test_eigene_adresse_wechselt_nur_das_von():
    """Dasselbe Konto, dieselbe Anmeldung — nur der Absender ist ein anderer."""
    haus = {"smtp_host": "send.one.com", "smtp_port": 587, "smtp_benutzer": "kai.boehm@aimighty.de",
            "smtp_passwort": "geheim", "smtp_absender": "kai.boehm@aimighty.de",
            "smtp_absender_name": "Kai Böhm"}
    k = versand.smtp_fuer(haus, {"absender_email": "marc.bayer@aimighty.de", "absender_name": "Marc Bayer"})
    assert k.absender == "marc.bayer@aimighty.de"
    assert k.von == "Marc Bayer <marc.bayer@aimighty.de>"
    # Angemeldet wird weiterhin als das Hauskonto.
    assert k.benutzer == "kai.boehm@aimighty.de"
    assert k.passwort == "geheim"
    assert k.host == "send.one.com"


def test_eine_fremde_domain_geht_nicht_ueber_das_gemeinsame_konto():
    """Sonst wäre das Konto der Organisation ein Weg, als beliebige Adresse
    zu schreiben — etwa als der Geschäftsführer eines Kunden."""
    haus = {"smtp_host": "send.one.com", "smtp_absender": "kai.boehm@aimighty.de"}
    with pytest.raises(versand.Unmoeglich) as fehler:
        versand.smtp_fuer(haus, {"absender_email": "chef@fremdefirma.de"})
    assert "aimighty.de" in str(fehler.value)


def test_mit_eigenen_zugangsdaten_zaehlt_die_domain_nicht():
    """Wer sich selbst anmeldet, führt, was sein Anbieter durchlässt."""
    haus = {"smtp_host": "send.one.com", "smtp_absender": "kai.boehm@aimighty.de"}
    k = versand.smtp_fuer(haus, {
        "absender_email": "marc@bayer-consulting.de", "absender_name": "Marc Bayer",
        "smtp_host": "mail.bayer-consulting.de", "smtp_port": 465,
        "smtp_benutzer": "marc@bayer-consulting.de", "smtp_passwort": "seins",
        "smtp_sicherheit": "ssl",
    })
    assert (k.host, k.port, k.sicherheit) == ("mail.bayer-consulting.de", 465, "ssl")
    assert k.benutzer == "marc@bayer-consulting.de" and k.passwort == "seins"
    assert k.absender == "marc@bayer-consulting.de"


def test_ohne_hauskonto_hilft_eine_eigene_adresse_allein_nicht():
    assert versand.smtp_fuer({}, {"absender_email": "marc.bayer@aimighty.de"}) is None


def test_die_antwort_geht_ans_postfach_der_organisation():
    """Beacon liest ein Postfach. Ohne Reply-To liefe die Antwort auf Marcs
    eigene Adresse und wäre im Bestand nie zu sehen."""
    konto = versand.Smtp(host="h", port=587, benutzer=None, passwort=None, sicherheit="starttls",
                         absender="marc.bayer@aimighty.de", absender_name="Marc Bayer")
    m = versand.nachricht_bauen(an="kunde@example.de", betreff="Angebot", text="Hallo",
                                konto=konto, message_id="<a@b>",
                                antwort_an="kai.boehm@aimighty.de")
    assert m["From"] == "Marc Bayer <marc.bayer@aimighty.de>"
    assert m["Reply-To"] == "kai.boehm@aimighty.de"
    # Schickt jemand ohnehin unter der Hausadresse, steht kein Reply-To da —
    # ein Kopf, der auf sich selbst zeigt, ist nur Rauschen.
    gleich = versand.nachricht_bauen(an="kunde@example.de", betreff="A", text="B", konto=konto,
                                     message_id="<c@d>", antwort_an="MARC.BAYER@aimighty.de")
    assert gleich["Reply-To"] is None


async def test_marc_schickt_unter_seinem_namen_kai_unter_seinem(datenbank, briefkasten):
    """Der ganze Weg: zwei Menschen, ein Konto, zwei Absender.

    Entscheidend ist, dass die Zuordnung an `mails.created_by` hängt und
    nicht daran, wer die Schleife anstößt — sonst ginge Marcs Angebot als
    Kai hinaus, sobald Kai als Nächster etwas versendet.
    """
    async with klient_fuer("vers-absender") as k:
        await k.put("/api/settings", json={**SMTP, "imap_host": "imap.one.com",
                                           "imap_benutzer": "kai@aimighty.de"})
        m = (await k.post("/api/mitglieder", json={"display_name": "Marc Bayer"})).json()
        kontakt = await _kontakt(k)
        kai = await conn_nutzer(k)

        # Marc setzt seine Adresse — über seinen eigenen Sitzplatz, denn
        # niemand ändert die Absenderadresse eines anderen.
        gesetzt = await k.put(
            "/api/mitglieder/wer/absender",
            json={"absender_email": "marc.bayer@aimighty.de", "absender_name": "Marc Bayer"},
            headers={"X-Beacon-Sitzplatz": m["id"]},
        )
        assert gesetzt.status_code == 200, gesetzt.text
        assert gesetzt.json()["haus_absender"] == SMTP["smtp_absender"]

        async with acquire_as(kai) as conn:
            org = await conn.fetchval("select org_id from public.contacts where id = $1", kontakt["id"])
            await versand.einreihen(conn, org, art="transaktional", an=kontakt["email"],
                                    betreff="Angebot", text="Hallo", created_by=m["id"])
            await versand.einreihen(conn, org, art="transaktional", an=kontakt["email"],
                                    betreff="Nachfrage", text="Hallo", created_by=kai)
            bilanz = await versand.verarbeiten(conn, org, sender=briefkasten)
        assert bilanz["gesendet"] == 2, bilanz

    absender = {n["Subject"]: (n["From"], n["Reply-To"]) for _, n in briefkasten.nachrichten}
    assert absender["Angebot"][0] == "Marc Bayer <marc.bayer@aimighty.de>"
    assert absender["Nachfrage"][0] == f'Kai Böhm <{SMTP["smtp_absender"]}>'
    # Beide Antworten laufen in das Postfach, das Beacon einliest.
    assert absender["Angebot"][1] == SMTP["smtp_absender"]
    assert absender["Nachfrage"][1] is None


async def test_eine_fremde_domain_wird_beim_speichern_abgewiesen(datenbank):
    async with klient_fuer("vers-domain") as k:
        await k.put("/api/settings", json=SMTP)
        r = await k.put("/api/mitglieder/wer/absender",
                        json={"absender_email": "chef@fremdefirma.de"})
        assert r.status_code == 422
        assert "aimighty.de" in r.json()["detail"]
        # Und nichts wurde gespeichert.
        assert (await k.get("/api/mitglieder/wer/absender")).json()["absender_email"] is None


async def test_das_eigene_smtp_passwort_kommt_nie_zurueck(datenbank):
    async with klient_fuer("vers-pw") as k:
        await k.put("/api/settings", json=SMTP)
        await k.put("/api/mitglieder/wer/absender", json={
            "absender_email": "wer@aimighty.de", "smtp_host": "mail.example.de",
            "smtp_benutzer": "wer@aimighty.de", "smtp_passwort": "streng geheim",
        })
        gelesen = (await k.get("/api/mitglieder/wer/absender")).json()
        assert gelesen["smtp_passwort_set"] is True
        assert "streng geheim" not in json.dumps(gelesen)
        assert "smtp_passwort" not in gelesen
