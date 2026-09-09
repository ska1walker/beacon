"""Dateien am Datensatz.

Geprüft wird vor allem das, was schiefgehen kann, wenn man einer Datei
aus dem Internet glaubt: ein Name, der aus der Ablage hinausführt, ein
Inhalt, den der Browser als Seite ausführt, eine Größe, die den Speicher
füllt — und die Trennung zweier Organisationen, die hier zwei Ordner auf
derselben Platte sind.
"""

import pathlib

import pytest

from app import dokumente as kern
from tests.conftest import klient_fuer

PDF = b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n1 0 obj\n<<>>\nendobj\ntrailer\n<<>>\n%%EOF\n"


def _auf_platte(dokument_id: str) -> pathlib.Path:
    """Die eine Datei zu dieser Kennung — gesucht, nicht gefragt.

    Der Pfad steht in der Datenbank, aber `acquire()` sieht die Zeile
    unter FORCE ROW LEVEL SECURITY nicht. Für den Test ist die Platte
    ohnehin die ehrlichere Quelle.
    """
    treffer = sorted(kern.ablage().glob(f"*/{dokument_id}*"))
    assert len(treffer) == 1, treffer
    return treffer[0]


async def _kontakt(k, name: str) -> str:
    antwort = await k.post("/api/contacts", json={"first_name": "Doku", "last_name": name})
    assert antwort.status_code == 201, antwort.text
    return antwort.json()["id"]


async def _hochladen(k, kontakt_id: str, dateiname: str, inhalt: bytes, typ: str):
    return await k.post(
        "/api/dokumente",
        data={"contact_id": kontakt_id},
        files={"datei": (dateiname, inhalt, typ)},
    )


async def test_ein_dokument_haengt_am_kontakt_und_kommt_zurueck(datenbank):
    async with klient_fuer("dok-eins") as k:
        kontakt = await _kontakt(k, "Eins")
        a = await _hochladen(k, kontakt, "Angebot.pdf", PDF, "application/pdf")
        assert a.status_code == 201, a.text
        assert a.json()["name"] == "Angebot.pdf"
        assert a.json()["groesse"] == len(PDF)

        liste = await k.get("/api/dokumente", params={"contact_id": kontakt})
        assert [d["name"] for d in liste.json()] == ["Angebot.pdf"]

        datei = await k.get(f"/api/dokumente/{a.json()['id']}/datei")
        assert datei.status_code == 200
        assert datei.content == PDF


async def test_ein_dateiname_fuehrt_nie_aus_der_ablage_hinaus(datenbank):
    """`../../` im Namen ist ein hässlicher Anzeigename, kein Angriff."""
    async with klient_fuer("dok-pfad") as k:
        kontakt = await _kontakt(k, "Pfad")
        a = await _hochladen(
            k, kontakt, "../../../../etc/passwort.txt", b"harmlos", "text/plain"
        )
        assert a.status_code == 201, a.text

        # Auf der Platte heißt die Datei nach ihrer Kennung, nicht nach
        # dem, was der Hochladende geschickt hat.
        auf_platte = _auf_platte(a.json()["id"])
        assert auf_platte.parent.parent == kern.ablage()
        assert auf_platte.read_bytes() == b"harmlos"
        # Der Mensch sieht trotzdem den Namen, den er hochgeladen hat —
        # nur ohne die Pfadanteile.
        assert a.json()["name"] == "passwort.txt"


def test_der_pfadwaechter_laesst_nichts_ausserhalb_durch():
    assert kern.pfad("dokumente/../../etc/passwd") is None
    assert kern.pfad("../sicherungen/abzug.json") is None
    assert kern.pfad("") is None
    assert kern.pfad("dokumente/abc/def.pdf") is not None


@pytest.mark.parametrize(
    "typ,im_fenster",
    [
        ("application/pdf", True),
        ("image/png", True),
        ("image/svg+xml", False),
        ("text/html", False),
        ("application/octet-stream", False),
        (None, False),
    ],
)
def test_nur_bild_und_pdf_duerfen_ins_fenster(typ, im_fenster):
    assert kern.darf_im_fenster(typ) is im_fenster


async def test_html_und_svg_werden_heruntergeladen_nicht_angezeigt(datenbank):
    """Sonst liefe fremdes Skript im Ursprung von Beacon."""
    async with klient_fuer("dok-skript") as k:
        kontakt = await _kontakt(k, "Skript")
        for name, typ in (("boese.html", "text/html"), ("boese.svg", "image/svg+xml")):
            a = await _hochladen(k, kontakt, name, b"<script>alert(1)</script>", typ)
            assert a.status_code == 201, a.text
            assert a.json()["im_fenster"] is False
            datei = await k.get(f"/api/dokumente/{a.json()['id']}/datei")
            assert datei.headers["content-disposition"].startswith("attachment")
            assert datei.headers["x-content-type-options"] == "nosniff"


async def test_zu_gross_wird_abgelehnt(datenbank, monkeypatch):
    monkeypatch.setattr(kern, "MAX_BYTES", 1024)
    async with klient_fuer("dok-gross") as k:
        kontakt = await _kontakt(k, "Gross")
        a = await _hochladen(k, kontakt, "dick.bin", b"x" * 2048, "application/octet-stream")
        assert a.status_code == 413


async def test_ohne_bezug_und_mit_zweien_wird_abgelehnt(datenbank):
    async with klient_fuer("dok-bezug") as k:
        kontakt = await _kontakt(k, "Bezug")
        firma = await k.post("/api/companies", json={"name": "Doku GmbH"})
        ohne = await k.post(
            "/api/dokumente", files={"datei": ("a.pdf", PDF, "application/pdf")}
        )
        assert ohne.status_code == 400
        zwei = await k.post(
            "/api/dokumente",
            data={"contact_id": kontakt, "company_id": firma.json()["id"]},
            files={"datei": ("a.pdf", PDF, "application/pdf")},
        )
        assert zwei.status_code == 400


async def test_eine_fremde_organisation_sieht_und_holt_nichts(datenbank):
    async with klient_fuer("dok-eigen") as eigen:
        kontakt = await _kontakt(eigen, "Eigen")
        a = await _hochladen(eigen, kontakt, "vertraulich.pdf", PDF, "application/pdf")
        dokument_id = a.json()["id"]

    async with klient_fuer("dok-fremd") as fremd:
        liste = await fremd.get("/api/dokumente", params={"contact_id": kontakt})
        assert liste.json() == []
        assert (await fremd.get(f"/api/dokumente/{dokument_id}/datei")).status_code == 404
        assert (await fremd.delete(f"/api/dokumente/{dokument_id}")).status_code == 404

    # und für die eigene Organisation liegt es unverändert da
    async with klient_fuer("dok-eigen") as eigen:
        assert (await eigen.get(f"/api/dokumente/{dokument_id}/datei")).status_code == 200


async def test_loeschen_nimmt_die_datei_von_der_platte(datenbank):
    async with klient_fuer("dok-loesch") as k:
        kontakt = await _kontakt(k, "Loesch")
        a = await _hochladen(k, kontakt, "weg.pdf", PDF, "application/pdf")
        auf_platte = _auf_platte(a.json()["id"])

        assert (await k.delete(f"/api/dokumente/{a.json()['id']}")).status_code == 204
        assert not auf_platte.exists()
        assert (await k.get("/api/dokumente", params={"contact_id": kontakt})).json() == []


async def test_eine_leere_datei_ergibt_keinen_eintrag(datenbank):
    async with klient_fuer("dok-leer") as k:
        kontakt = await _kontakt(k, "Leer")
        a = await _hochladen(k, kontakt, "leer.txt", b"", "text/plain")
        assert a.status_code == 400
        assert (await k.get("/api/dokumente", params={"contact_id": kontakt})).json() == []


async def test_dokumente_stehen_im_abzug(datenbank):
    """Sonst wäre nach einer Neuinstallation die Datei da und die Zeile weg."""
    from app import sicherung

    assert "dokumente" in sicherung.TABELLEN
