"""CSV hereinholen — zuordnen, probelaufen, anwenden.

Die Datei kommt zweimal: einmal für die Vorschau, einmal für das
Anwenden. Beide Male läuft **derselbe** `probelauf()`. Das ist die
wichtigste Entscheidung hier: Was der Mensch auf dem Bildschirm gesehen
hat, ist genau das, was danach geschieht — keine zweite Bewertung, die
sich anders entscheiden könnte.

Weil dieselbe Datei zweimal hochgeladen wird, bewahrt Beacon zwischendurch
nichts auf. Kein Ablageordner, keine Ablauffrist, keine Frage, wem eine
Datei auf der Platte gehört. Bei zehn Megabyte im eigenen Netz ist das ein
Wimpernschlag.

**Nichts wird überschrieben.** Eine Zeile, deren Kontakt es schon gibt,
wird übersprungen und genannt. Der teure Fehler wäre der andere: Eine
Datei mit einer verrutschten Spalte, die stillschweigend fünfhundert
gepflegte Datensätze überschreibt.

Alles Objektspezifische steht in einem Register (`NICHT_IMPORTIERBAR`,
`VIRTUELL`, `ALIASE`). Leads und Tickets werden später je ein Eintrag
darin, nicht ein zweiter Importer daneben.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

import asyncpg
import orjson

from app import audit, csvform, eigenschaften, segmente
from app.auth import CurrentUser
from app.csvform import Unlesbar
from app.schemas import CompanyIn, ContactIn

OBJEKTE = ("contacts", "companies")

# Felder, die es in der Tabelle gibt, aber nicht in einer Einfuhr.
#
# `created_at`/`updated_at` entstehen beim Schreiben — ein Datum aus der
# Datei wäre eine Behauptung über die eigene Historie. `company_name` ist
# der Name der verknüpften Firma, kein eigenes Feld (dafür gibt es
# `firma_name`). Die Zählspalten sind berechnet. Und die
# Marketing-Einwilligung braucht einen Nachweis; eine Zelle in einer
# Tabelle ist keiner.
NICHT_IMPORTIERBAR: dict[str, set[str]] = {
    "contacts": {"created_at", "updated_at", "company_name", "marketing_einwilligung"},
    "companies": {"created_at", "updated_at", "contact_count", "open_deal_count", "open_amount_cents"},
}

# Spalten, die kein Feld der Tabelle sind, sondern eine Verknüpfung
# herstellen. Am Kontakt steht in der Datei „Firma", gemeint ist eine
# Firma, die gefunden oder angelegt wird.
VIRTUELL: dict[str, list[dict[str, str]]] = {
    "contacts": [
        {"schluessel": "firma_name", "text": "Firma"},
        {"schluessel": "firma_domain", "text": "Firmen-Domain"},
    ],
    "companies": [],
}

PFLICHT: dict[str, set[str]] = {"companies": {"name"}, "contacts": set()}

# Kopfzeilen, die andere Systeme schreiben. Deutsch und englisch, dazu
# das, was ein HubSpot-Export in die erste Zeile setzt. Der Vergleich
# läuft über `_falten`, Groß-/Kleinschreibung und Satzzeichen sind also
# egal.
ALIASE: dict[str, dict[str, tuple[str, ...]]] = {
    "contacts": {
        "first_name": ("vorname", "first name", "firstname", "given name"),
        "last_name": ("nachname", "name", "last name", "lastname", "surname", "familienname"),
        "email": ("e mail", "email", "e mail adresse", "email address", "mail", "e mail 1"),
        "phone": ("telefon", "telefonnummer", "phone", "phone number", "festnetz"),
        "mobile": ("mobil", "mobiltelefonnummer", "handy", "mobile", "mobile phone number"),
        "job_title": ("position", "job title", "jobtitle", "titel", "funktion", "rolle"),
        "buying_role": ("kaufrolle", "buying role"),
        "linkedin_url": ("linkedin", "linkedin url", "linkedin profil"),
        "lifecycle_stage": ("stufe", "lifecycle phase", "lifecycle stage", "status"),
        "source": ("herkunft", "quelle", "original source", "urspruengliche quelle"),
        "notes": ("notizen", "notes", "bemerkung", "anmerkungen"),
        "owner_id": ("besitzer", "kontaktinhaber", "contact owner", "owner", "zustaendig"),
        "firma_name": (
            "firma", "unternehmen", "company", "company name", "zugehoeriges unternehmen",
            "associated company", "firmenname", "name des unternehmens", "organisation",
        ),
        "firma_domain": (
            "firmen domain", "unternehmens domain name", "company domain name",
            "domain", "website des unternehmens",
        ),
    },
    "companies": {
        "name": ("firma", "firmenname", "unternehmen", "company", "company name", "name des unternehmens"),
        "domain": ("domain", "unternehmens domain name", "company domain name"),
        "industry": ("branche", "industry", "sektor"),
        "employee_count": ("mitarbeiter", "mitarbeiterzahl", "anzahl der mitarbeiter", "number of employees", "employees"),
        "street": ("strasse", "street", "street address", "adresse", "anschrift"),
        "postal_code": ("plz", "postleitzahl", "postal code", "zip", "zip code"),
        "city": ("ort", "stadt", "city"),
        "country": ("land", "country", "land region", "country region"),
        "phone": ("telefon", "telefonnummer", "phone", "phone number"),
        "website": ("website", "webseite", "website url", "homepage", "url"),
        "linkedin_url": ("linkedin", "linkedin url", "linkedin unternehmensseite"),
        "lifecycle_stage": ("stufe", "lifecycle phase", "lifecycle stage", "status"),
        "source": ("herkunft", "quelle", "original source"),
        "description": ("beschreibung", "description", "ueber uns"),
        "owner_id": ("besitzer", "unternehmensinhaber", "company owner", "owner"),
    },
}

# Rechtsformen, die beim Firmenabgleich hinten wegfallen. Wortgleich mit
# `firmenschluessel` in `frontend/lib/format.ts` — dieselbe Liste, damit
# der Importer nicht schlechter zuordnet als der Anlegen-Dialog.
RECHTSFORMEN = {
    "gmbh", "mbh", "mbb", "ug", "ag", "kg", "kgaa", "ohg", "gbr", "se", "ev",
    "ek", "partg", "partgmbb", "co", "haftungsbeschraenkt",
    "ltd", "limited", "inc", "llc", "llp", "plc", "bv", "nv", "sa", "sarl",
    "srl", "spa", "oy", "ab", "as",
}

# Herkunft, die importierte Datensätze tragen, wenn die Datei keine nennt.
HERKUNFT = "Import"

_NICHT_WORT = re.compile(r"[^a-z0-9]+")


def _falten(text: str) -> str:
    """Kopfzeilen vergleichbar machen — wie `eigenschaften.schluessel_aus`."""
    klein = text.strip().lower()
    klein = klein.replace("ä", "ae").replace("ö", "oe").replace("ü", "ue").replace("ß", "ss")
    return _NICHT_WORT.sub(" ", klein).strip()


def firmenschluessel(name: str) -> str:
    """„Nordwind Logistik GmbH" und „Nordwind Logistik" sind dieselbe Firma.

    Weggeworfen wird nur, was **hinten** steht. „Partner" bleibt stehen,
    es gehört bei Kanzleien zum Namen: Ein Abgleich, der zu viel wegwirft,
    führt zwei verschiedene Firmen zusammen, und das ist der teurere
    Fehler.
    """
    worte = [w for w in re.split(r"\s+", re.sub(r"[.,()&]", " ", name.lower())) if w]
    while len(worte) > 1 and worte[-1] in RECHTSFORMEN:
        worte.pop()
    return " ".join(worte)


def domain_normalisieren(text: str) -> str:
    """`https://www.acme.de/kontakt` und `acme.de` sind dieselbe Domain."""
    roh = text.strip().lower()
    roh = re.sub(r"^[a-z][a-z0-9+.-]*://", "", roh)
    roh = roh.split("/")[0].split("?")[0].removeprefix("www.")
    return roh.strip(". ")


@dataclass(frozen=True)
class Ziel:
    """Ein Feld, auf das sich eine Spalte der Datei legen lässt."""

    schluessel: str
    text: str
    art: str
    optionen: list[dict[str, str]] = field(default_factory=list)
    eigen: bool = False
    virtuell: bool = False


@dataclass
class Zeile:
    nr: int
    werte: dict[str, Any]
    custom: dict[str, Any]
    firma_id: UUID | None
    neue_firma: str | None
    urteil: str  # "anlegen" | "ueberspringen"
    grund: str | None = None
    satz: str | None = None


@dataclass
class Probelauf:
    zeilen: list[Zeile]
    hinweise: list[str]

    def bilanz(self) -> dict[str, Any]:
        gruende: dict[str, int] = {}
        for z in self.zeilen:
            if z.grund:
                gruende[z.grund] = gruende.get(z.grund, 0) + 1
        neue = {z.neue_firma for z in self.zeilen if z.urteil == "anlegen" and z.neue_firma}
        return {
            "anlegen": sum(1 for z in self.zeilen if z.urteil == "anlegen"),
            "firmen_anlegen": len(neue),
            "ueberspringen": sum(1 for z in self.zeilen if z.urteil == "ueberspringen"),
            "gruende": gruende,
        }


async def ziele_fuer(conn: asyncpg.Connection, entity: str) -> list[Ziel]:
    """Alles, worauf eine Spalte zeigen darf — feste Felder und eigene."""
    if entity not in OBJEKTE:
        raise Unlesbar("objekt", entity, f"Unbekanntes Objekt: {entity}")

    ziele = [
        Ziel(f["schluessel"], f["text"], f["art"], f["optionen"], eigen=f["eigen"])
        for f in await segmente.felder_fuer(conn, entity)
        if f["schluessel"] not in NICHT_IMPORTIERBAR[entity]
    ]
    ziele += [Ziel(v["schluessel"], v["text"], "text", virtuell=True) for v in VIRTUELL[entity]]
    return ziele


def zuordnen(kopf: list[str], ziele: list[Ziel], entity: str) -> list[str | None]:
    """Für jede Dateispalte ein Ziel — oder nichts.

    Drei Anläufe je Spalte, in dieser Reihenfolge: der Schlüssel selbst
    (so findet eine von Beacon geschriebene Datei zurück), die
    Beschriftung, dann die Aliasliste fremder Systeme. Die eigene
    Benennung geht vor der fremden — wer eine Eigenschaft „Domain"
    nennt, meint seine eigene.

    Jedes Ziel wird höchstens einmal belegt. Zwei Spalten „Telefon"
    schrieben sonst still gegeneinander, und die zweite gewänne.
    """
    nach_schluessel = {z.schluessel for z in ziele}
    nach_text = {_falten(z.text): z.schluessel for z in ziele}
    nach_alias = {
        _falten(name): schluessel
        for schluessel, namen in ALIASE.get(entity, {}).items()
        for name in namen
        if schluessel in nach_schluessel
    }

    vergeben: set[str] = set()
    ergebnis: list[str | None] = []
    for spalte in kopf:
        gefaltet = _falten(spalte)
        treffer = (
            spalte if spalte in nach_schluessel
            else nach_text.get(gefaltet) or nach_alias.get(gefaltet)
        )
        if treffer and treffer not in vergeben:
            vergeben.add(treffer)
            ergebnis.append(treffer)
        else:
            ergebnis.append(None)
    return ergebnis


def entity_erraten(kopf: list[str]) -> str:
    """Kontakte oder Firmen? Was die Kopfzeile verrät.

    Eine Datei mit E-Mail, Vor- oder Nachname ist eine Personenliste.
    Sonst entscheidet, ob ein Firmenname oder eine Domain darin steht.
    Im Zweifel Kontakte — das ist die häufigere Datei.
    """
    gefaltet = {_falten(s) for s in kopf}
    for schluessel in ("email", "first_name", "last_name"):
        if gefaltet & set(ALIASE["contacts"][schluessel]):
            return "contacts"
    if gefaltet & set(ALIASE["companies"]["name"]) or gefaltet & set(ALIASE["companies"]["domain"]):
        return "companies"
    return "contacts"


async def _personen(conn: asyncpg.Connection) -> tuple[dict[str, str], dict[str, str]]:
    """Kennung → Name und Name → Kennung (klein), für Besitzerspalten."""
    zeilen = await conn.fetch(
        "select u.id, coalesce(u.display_name, u.olares_username) as name, u.olares_username "
        "from public.users u join public.user_org_roles r on r.user_id = u.id "
        "where u.deleted_at is null"
    )
    nach_id = {str(z["id"]): z["name"] for z in zeilen}
    nach_name: dict[str, str] = {}
    for z in zeilen:
        nach_name.setdefault(z["name"].casefold(), str(z["id"]))
        nach_name.setdefault(z["olares_username"].casefold(), str(z["id"]))
    return nach_id, nach_name


async def probelauf(
    conn: asyncpg.Connection,
    user: CurrentUser,
    entity: str,
    kopf: list[str],
    zeilen: list[list[str]],
    zuordnung: list[str | None],
) -> Probelauf:
    """Bewertet jede Zeile, ohne etwas zu schreiben.

    Vorschau und Anwenden rufen diese Funktion gleichermaßen. Was hier
    „anlegen" heißt, wird angelegt; was „überspringen" heißt, wird
    genannt. Zwei getrennte Bewertungen wären zwei Gelegenheiten, sich
    unterschiedlich zu entscheiden.

    Alles Nachschlagbare wird **einmal** geladen, nicht je Zeile: die
    Definitionen der eigenen Eigenschaften, die Personen, die
    vorhandenen E-Mail-Adressen und Firmen. Bei zwanzigtausend Zeilen
    ist das der Unterschied zwischen Sekunden und Minuten.
    """
    ziele = {z.schluessel: z for z in await ziele_fuer(conn, entity)}
    defs = await eigenschaften.definitionen(conn, entity)
    _, personen_nach_name = await _personen(conn)

    bekannte_mails: set[str] = set()
    if entity == "contacts":
        bekannte_mails = {
            z["e"] for z in await conn.fetch(
                "select lower(email) as e from public.contacts "
                "where deleted_at is null and email is not null"
            )
        }

    firmen = await conn.fetch(
        "select id, name, domain from public.companies where deleted_at is null"
    )
    firma_nach_domain = {
        domain_normalisieren(f["domain"]): f["id"] for f in firmen if f["domain"]
    }
    firma_nach_name = {firmenschluessel(f["name"]): f["id"] for f in firmen if f["name"]}

    bekannte_domains = set(firma_nach_domain)
    bekannte_namen = set(firma_nach_name)

    # Was in dieser Datei schon vorkam. Zwei Kontakte derselben neuen
    # Firma sollen **eine** Firma ergeben, nicht zwei.
    gesehene_mails: set[str] = set()
    gesehene_firmen: dict[str, str] = {}
    unbekannte_personen = 0
    ergebnis: list[Zeile] = []

    for versatz, roh in enumerate(zeilen):
        # Zeile 1 ist die Kopfzeile — die Nummer soll die sein, die in
        # Excel links am Rand steht.
        nr = versatz + 2
        werte: dict[str, Any] = {}
        custom_roh: dict[str, Any] = {}
        firma_name = firma_domain = ""
        fehler: Unlesbar | None = None

        for spalte, schluessel in enumerate(zuordnung):
            if schluessel is None or spalte >= len(roh):
                continue
            ziel = ziele.get(schluessel)
            if ziel is None:
                continue
            text = roh[spalte]
            if ziel.virtuell:
                if schluessel == "firma_name":
                    firma_name = csvform.formelschutz_entfernen(text.strip())
                else:
                    firma_domain = domain_normalisieren(text)
                continue
            try:
                wert = csvform.wert_lesen(
                    {"schluessel": ziel.schluessel, "text": ziel.text, "art": ziel.art,
                     "optionen": ziel.optionen},
                    text, personen_nach_name,
                )
            except Unlesbar as exc:
                # Ein unbekannter Besitzer kippt die Zeile nicht: Eine
                # Datei aus einem fremden System nennt Menschen, die es
                # hier nicht gibt. Der Datensatz gehört dann dem, der
                # importiert — sichtbar, nicht stillschweigend.
                if exc.grund == "unbekannte_person":
                    unbekannte_personen += 1
                    continue
                fehler = exc
                break
            if wert is None:
                continue
            if ziel.eigen:
                custom_roh[ziel.schluessel.removeprefix(segmente.CUSTOM_PRAEFIX)] = wert
            else:
                werte[ziel.schluessel] = wert

        if fehler is not None:
            ergebnis.append(Zeile(nr, {}, {}, None, None, "ueberspringen", fehler.grund, fehler.satz))
            continue

        custom: dict[str, Any] = {}
        if custom_roh:
            try:
                custom = eigenschaften.pruefen(custom_roh, defs)
            except eigenschaften.Ungueltig as exc:
                ergebnis.append(
                    Zeile(nr, {}, {}, None, None, "ueberspringen", "ungueltiger_wert", str(exc))
                )
                continue

        # Ist überhaupt etwas da?
        if not werte and not custom and not firma_name and not firma_domain:
            ergebnis.append(Zeile(nr, {}, {}, None, None, "ueberspringen", "leer", "Die Zeile ist leer."))
            continue
        fehlende_pflicht = PFLICHT[entity] - werte.keys()
        if fehlende_pflicht:
            fehlt = ", ".join(ziele[s].text for s in sorted(fehlende_pflicht) if s in ziele)
            ergebnis.append(
                Zeile(nr, {}, {}, None, None, "ueberspringen", "leer", f"Ohne {fehlt} geht es nicht.")
            )
            continue

        # Dubletten
        if entity == "contacts":
            mail = (werte.get("email") or "").lower()
            if mail and mail in bekannte_mails:
                ergebnis.append(
                    Zeile(nr, werte, custom, None, None, "ueberspringen", "dublette_email",
                          f"{mail}: diesen Kontakt gibt es schon.")
                )
                continue
            if mail and mail in gesehene_mails:
                ergebnis.append(
                    Zeile(nr, werte, custom, None, None, "ueberspringen", "dublette_datei",
                          f"{mail}: steht weiter oben in derselben Datei.")
                )
                continue
            if mail:
                gesehene_mails.add(mail)
        else:
            domain = domain_normalisieren(werte.get("domain") or "")
            schluessel = firmenschluessel(werte.get("name") or "")
            if domain and domain in bekannte_domains:
                grund = "dublette_domain" if domain in firma_nach_domain else "dublette_datei"
                ergebnis.append(
                    Zeile(nr, werte, custom, None, None, "ueberspringen", grund,
                          f"{domain}: diese Firma gibt es schon.")
                )
                continue
            if not domain and schluessel and schluessel in bekannte_namen:
                grund = "dublette_name" if schluessel in firma_nach_name else "dublette_datei"
                ergebnis.append(
                    Zeile(nr, werte, custom, None, None, "ueberspringen", grund,
                          f"„{werte.get('name')}“: diese Firma gibt es schon.")
                )
                continue
            if domain:
                bekannte_domains.add(domain)
            if schluessel:
                bekannte_namen.add(schluessel)

        # Die Firma des Kontakts: gefunden oder neu.
        firma_id: UUID | None = None
        neue_firma: str | None = None
        if entity == "contacts" and (firma_name or firma_domain):
            if firma_domain and firma_domain in firma_nach_domain:
                firma_id = firma_nach_domain[firma_domain]
            elif firma_name and firmenschluessel(firma_name) in firma_nach_name:
                firma_id = firma_nach_name[firmenschluessel(firma_name)]
            else:
                merkmal = firma_domain or firmenschluessel(firma_name)
                neue_firma = gesehene_firmen.setdefault(merkmal, firma_name or firma_domain)

        ergebnis.append(Zeile(nr, werte, custom, firma_id, neue_firma, "anlegen"))

    hinweise: list[str] = []
    if unbekannte_personen:
        hinweise.append(
            f"{unbekannte_personen} Zeilen nennen einen Besitzer, den es hier nicht gibt — "
            "diese Datensätze werden Ihnen zugeschrieben."
        )
    return Probelauf(ergebnis, hinweise)


async def anwenden(
    conn: asyncpg.Connection,
    user: CurrentUser,
    entity: str,
    lauf: Probelauf,
    *,
    dateiname: str,
    kodierung: str,
    trenner: str,
    zuordnung: list[str | None],
) -> dict[str, Any]:
    """Schreibt, was der Probelauf mit „anlegen" bewertet hat.

    Läuft in der Transaktion des Aufrufers: Geht irgendwo etwas
    Unerwartetes schief, ist nichts geschrieben. Ein halber Import wäre
    schlimmer als keiner — man sähe ihm nicht an, wo er aufgehört hat.
    """
    from app.routers import companies as firmen_router
    from app.routers import contacts as kontakt_router

    bilanz = lauf.bilanz()
    firmen_ids: dict[str, UUID] = {}

    # Erst die Firmen: Ein Kontakt braucht die Kennung seiner Firma,
    # bevor er selbst entsteht.
    for zeile in lauf.zeilen:
        if zeile.urteil != "anlegen" or not zeile.neue_firma or zeile.neue_firma in firmen_ids:
            continue
        name = zeile.neue_firma
        neu = CompanyIn(name=name[:200], source=HERKUNFT)
        if "." in name and " " not in name:
            neu = CompanyIn(name=name[:200], domain=name, source=HERKUNFT)
        firmen_ids[name] = await firmen_router.einfuegen(conn, user, neu, "{}")

    angelegt = 0
    for zeile in lauf.zeilen:
        if zeile.urteil != "anlegen":
            continue
        werte = dict(zeile.werte)
        werte.setdefault("source", HERKUNFT)
        custom_json = orjson.dumps(zeile.custom).decode()

        if entity == "contacts":
            werte["company_id"] = zeile.firma_id or firmen_ids.get(zeile.neue_firma or "")
            neue_id = await kontakt_router.einfuegen(
                conn, user, ContactIn(**werte), custom_json
            )
        else:
            neue_id = await firmen_router.einfuegen(
                conn, user, CompanyIn(**werte), custom_json
            )
        angelegt += 1
        await audit.log_fuer(
            conn, user, action="create", entity=entity, entity_id=neue_id,
            diff={"einfuhr": dateiname, "zeile": zeile.nr},
        )

    uebersprungen = [
        {"zeile": z.nr, "grund": z.grund, "text": z.satz}
        for z in lauf.zeilen if z.urteil == "ueberspringen"
    ][:500]

    einfuhr_id = await conn.fetchval(
        """
        insert into public.einfuhren
          (org_id, entity, dateiname, kodierung, trenner, zeilen, angelegt,
           firmen_angelegt, uebersprungen, gruende, details, zuordnung, created_by)
        values ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10::jsonb,$11::jsonb,$12::jsonb,$13)
        returning id
        """,
        user.org_id, entity, dateiname, kodierung, trenner, len(lauf.zeilen),
        angelegt, len(firmen_ids), bilanz["ueberspringen"],
        orjson.dumps(bilanz["gruende"]).decode(),
        orjson.dumps(uebersprungen).decode(),
        orjson.dumps(zuordnung).decode(),
        user.user_id,
    )
    return {
        "id": einfuhr_id,
        "entity": entity,
        "angelegt": angelegt,
        "firmen_angelegt": len(firmen_ids),
        "uebersprungen": bilanz["ueberspringen"],
        "gruende": bilanz["gruende"],
        "details": uebersprungen,
    }
