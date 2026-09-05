"""Segmentierung: aus Bedingungen wird eine Abfrage.

Das ist die Kernfunktion, um die herum HubSpot gebaut ist. Eine Liste ist
dort nie „alle Kontakte“, sondern immer eine Frage an den Bestand:
Geschäftsführer in Hamburg, deren letzte Berührung älter als 30 Tage ist.
Wer diese Frage einmal gestellt hat, speichert sie als **Ansicht** und
findet sie am nächsten Morgen wieder.

Drei Dinge macht dieses Modul:

1. **Es sagt, welche Felder es gibt** — je Objekt eine feste Liste plus
   die selbst angelegten Eigenschaften. Die Oberfläche baut ihre
   Auswahlfelder daraus, statt sie noch einmal aufzuzählen.
2. **Es übersetzt Bedingungen in SQL** — mit einer Whitelist für
   Spaltennamen und Parametern für jeden Wert. Ein Feldname aus der
   Anfrage erreicht die Datenbank nie als Text.
3. **Es rechnet relative Zeiträume** aus („in den letzten 30 Tagen“),
   damit eine gespeicherte Ansicht morgen etwas anderes zeigt als heute.
   Ein festes Datum in der Ansicht wäre nach einer Woche falsch.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Literal

import asyncpg

Art = Literal["text", "auswahl", "mehrfachauswahl", "zahl", "datum", "jaNein", "person"]

# Welche Operatoren zu welcher Art von Feld passen. Die Oberfläche liest
# das hier aus; sie soll nicht „enthält“ an einer Zahl anbieten.
OPERATOREN: dict[str, list[str]] = {
    "text": ["ist", "ist_nicht", "enthaelt", "enthaelt_nicht", "beginnt_mit", "leer", "nicht_leer"],
    "auswahl": ["ist", "ist_nicht", "ist_eines_von", "leer", "nicht_leer"],
    # Eine Mehrfachauswahl beantwortet andere Fragen als eine Auswahl.
    # „ist“ gibt es hier nicht: Ein Feld mit drei Werten *ist* keiner
    # davon, es *hat* sie. Der Unterschied zwischen „eines von“ und
    # „alle von“ ist der zwischen einer Zielgruppe und einer Schnittmenge.
    "mehrfachauswahl": [
        "hat_eines_von", "hat_alle_von", "hat_keines_von", "hat_nicht_alle_von",
        "leer", "nicht_leer",
    ],
    "zahl": ["ist", "groesser", "kleiner", "leer", "nicht_leer"],
    "datum": ["nach", "vor", "letzte_tage", "aelter_als_tage", "leer", "nicht_leer"],
    "jaNein": ["ist_wahr", "ist_falsch"],
    "person": ["ist", "ist_nicht", "leer", "nicht_leer"],
}

# Operatoren, die keinen Wert brauchen. Ein „leer“ mit Wert wäre ein
# Bedienfehler, kein Filter.
OHNE_WERT = {"leer", "nicht_leer", "ist_wahr", "ist_falsch"}

# Operatoren, die auf eine gespeicherte Liste gehen statt auf einen
# Wert. Sie brauchen den jsonb-Ausdruck, nicht den Textauszug.
MEHRFACH_OPERATOREN = {"hat_eines_von", "hat_alle_von", "hat_keines_von", "hat_nicht_alle_von"}


class Ungueltig(ValueError):  # noqa: N818 — die Fachbegriffe hier sind deutsch
    """Eine Bedingung, die so nicht gestellt werden kann."""


@dataclass(frozen=True)
class Feld:
    schluessel: str
    text: str
    art: Art
    sql: str
    # Für Auswahlfelder: was zur Wahl steht. Die Oberfläche zeigt den
    # Text, gespeichert wird der Wert.
    optionen: list[dict[str, str]] = field(default_factory=list)
    # Ein berechnetes Feld (Unterabfrage) lässt sich zeigen und sortieren,
    # aber nicht in eine WHERE-Klausel setzen — dort gilt es noch nicht.
    filterbar: bool = True
    # Rechtsbündig in der Tabelle, weil man Zahlen an der Einerstelle
    # vergleicht.
    zahl: bool = False


STUFEN = [
    {"wert": "lead", "text": "Kontakt"},
    {"wert": "qualified", "text": "Qualifiziert"},
    {"wert": "opportunity", "text": "Chance"},
    {"wert": "customer", "text": "Kunde"},
    {"wert": "partner", "text": "Partner"},
    {"wert": "disqualified", "text": "Verworfen"},
]

FIRMEN_FELDER: list[Feld] = [
    Feld("name", "Firma", "text", "c.name"),
    Feld("domain", "Domain", "text", "c.domain"),
    Feld("industry", "Branche", "text", "c.industry"),
    Feld("employee_count", "Mitarbeiter", "zahl", "c.employee_count", zahl=True),
    Feld("street", "Straße", "text", "c.street"),
    Feld("postal_code", "PLZ", "text", "c.postal_code"),
    Feld("city", "Ort", "text", "c.city"),
    Feld("country", "Land", "text", "c.country"),
    Feld("phone", "Telefon", "text", "c.phone"),
    Feld("website", "Website", "text", "c.website"),
    Feld("linkedin_url", "LinkedIn", "text", "c.linkedin_url"),
    Feld("lifecycle_stage", "Stufe", "auswahl", "c.lifecycle_stage::text", optionen=STUFEN),
    Feld("source", "Herkunft", "text", "c.source"),
    Feld("description", "Beschreibung", "text", "c.description"),
    Feld("owner_id", "Besitzer", "person", "c.owner_id::text"),
    Feld("created_at", "Angelegt", "datum", "c.created_at"),
    Feld("updated_at", "Zuletzt geändert", "datum", "c.updated_at"),
    Feld("contact_count", "Kontakte", "zahl", "contact_count", filterbar=False, zahl=True),
    Feld("open_deal_count", "Offene Deals", "zahl", "open_deal_count", filterbar=False, zahl=True),
    Feld("open_amount_cents", "Offener Wert", "zahl", "open_amount_cents", filterbar=False, zahl=True),
]

KONTAKT_FELDER: list[Feld] = [
    Feld("first_name", "Vorname", "text", "k.first_name"),
    Feld("last_name", "Nachname", "text", "k.last_name"),
    Feld("email", "E-Mail", "text", "k.email"),
    Feld("phone", "Telefon", "text", "k.phone"),
    Feld("mobile", "Mobil", "text", "k.mobile"),
    Feld("job_title", "Position", "text", "k.job_title"),
    Feld("buying_role", "Kaufrolle", "text", "k.buying_role"),
    Feld("linkedin_url", "LinkedIn", "text", "k.linkedin_url"),
    Feld("company_name", "Firma", "text", "f.name"),
    Feld("lifecycle_stage", "Stufe", "auswahl", "k.lifecycle_stage::text", optionen=STUFEN),
    Feld("source", "Herkunft", "text", "k.source"),
    Feld("notes", "Notizen", "text", "k.notes"),
    Feld("owner_id", "Besitzer", "person", "k.owner_id::text"),
    Feld("created_at", "Angelegt", "datum", "k.created_at"),
    Feld("updated_at", "Zuletzt geändert", "datum", "k.updated_at"),
]

PRIORITAETEN = [
    {"wert": "dringend", "text": "Dringend"},
    {"wert": "hoch", "text": "Hoch"},
    {"wert": "mittel", "text": "Mittel"},
    {"wert": "niedrig", "text": "Niedrig"},
]

TICKET_FELDER: list[Feld] = [
    Feld("nummer", "Nummer", "zahl", "t.nummer", zahl=True),
    Feld("betreff", "Betreff", "text", "t.betreff"),
    Feld("beschreibung", "Beschreibung", "text", "t.beschreibung"),
    Feld("stufe_name", "Stufe", "text", "s.name"),
    Feld("prioritaet", "Priorität", "auswahl", "t.prioritaet::text", optionen=PRIORITAETEN),
    Feld("kategorie", "Kategorie", "text", "t.kategorie"),
    Feld(
        "quelle", "Quelle", "auswahl", "t.quelle::text",
        # Muss zur Aufzählung `ticket_quelle` in der Datenbank passen.
        # Eine zweite, handgeführte Liste ist eine Falle: Kommt ein Wert
        # dazu und bleibt hier stehen, lassen sich genau die neuen Tickets
        # nicht mehr nach ihrer Herkunft finden — und niemand vermisst
        # einen Filter, den es nie gab. `test_segmente` hält beide
        # Listen deshalb gegeneinander.
        optionen=[
            {"wert": "manuell", "text": "Von Hand"},
            {"wert": "email", "text": "E-Mail"},
            {"wert": "telefon", "text": "Telefon"},
            {"wert": "insilo", "text": "Insilo"},
            {"wert": "formular", "text": "Formular"},
            {"wert": "api", "text": "Schnittstelle"},
            {"wert": "bot", "text": "Bot"},
        ],
    ),
    Feld("owner_id", "Zuständig", "person", "t.owner_id::text"),
    Feld("kontakt_name", "Kontakt", "text", "coalesce(k.first_name || ' ', '') || coalesce(k.last_name, '')"),
    Feld("firma_name", "Firma", "text", "f.name"),
    Feld("faellig_am", "Fällig", "datum", "t.faellig_am"),
    Feld("erste_antwort_am", "Erste Antwort", "datum", "t.erste_antwort_am"),
    Feld("geschlossen_am", "Geschlossen", "datum", "t.geschlossen_am"),
    Feld("created_at", "Angelegt", "datum", "t.created_at"),
    Feld("updated_at", "Zuletzt geändert", "datum", "t.updated_at"),
    Feld("letzte_aktivitaet", "Letzte Aktivität", "datum", "letzte_aktivitaet", filterbar=False),
]

AUFGABEN_FELDER: list[Feld] = [
    Feld("title", "Titel", "text", "t.title"),
    Feld("body", "Notiz", "text", "t.body"),
    Feld(
        "art", "Art", "auswahl", "t.art::text",
        optionen=[
            {"wert": "todo", "text": "To-do"},
            {"wert": "anruf", "text": "Anruf"},
            {"wert": "email", "text": "E-Mail"},
            {"wert": "termin", "text": "Termin"},
        ],
    ),
    Feld(
        "phase", "Phase", "auswahl", "t.phase::text",
        optionen=[
            {"wert": "nicht_gestartet", "text": "Nicht gestartet"},
            {"wert": "in_arbeit", "text": "In Arbeit"},
            {"wert": "wartet", "text": "Wartet"},
        ],
    ),
    Feld("prioritaet", "Dringlichkeit", "auswahl", "t.prioritaet::text", optionen=PRIORITAETEN),
    Feld(
        "status", "Zustand", "auswahl", "t.status::text",
        optionen=[
            {"wert": "open", "text": "Offen"},
            {"wert": "done", "text": "Erledigt"},
            {"wert": "cancelled", "text": "Verworfen"},
        ],
    ),
    Feld("due_at", "Fällig", "datum", "t.due_at"),
    Feld("assigned_to", "Zugewiesen", "person", "t.assigned_to::text"),
    Feld("company_name", "Firma", "text", "f.name"),
    Feld("kontakt_name", "Kontakt", "text", "coalesce(k.first_name || ' ', '') || coalesce(k.last_name, '')"),
    Feld("deal_name", "Lead", "text", "d.name"),
    Feld("ticket_betreff", "Ticket", "text", "ti.betreff"),
    Feld("created_at", "Angelegt", "datum", "t.created_at"),
    Feld("completed_at", "Erledigt am", "datum", "t.completed_at"),
]

FELDER: dict[str, list[Feld]] = {
    "companies": FIRMEN_FELDER,
    "contacts": KONTAKT_FELDER,
    "tickets": TICKET_FELDER,
    "tasks": AUFGABEN_FELDER,
}

# Die Spalte, in der die selbst angelegten Eigenschaften liegen.
CUSTOM_SPALTE = {"companies": "c.custom", "contacts": "k.custom", "tickets": "t.custom"}

# Welche Spalten der Tabelle die Oberfläche zeigt, wenn niemand etwas
# ausgewählt hat. Dieselben wie bisher — eine neue Funktion soll die
# gewohnte Liste nicht umstellen.
VORGABE_SPALTEN = {
    "companies": ["name", "industry", "city", "lifecycle_stage", "contact_count", "open_deal_count", "open_amount_cents"],
    "contacts": ["first_name", "last_name", "job_title", "company_name", "buying_role", "email", "lifecycle_stage"],
    "tickets": ["nummer", "betreff", "stufe_name", "prioritaet", "kategorie", "owner_id", "firma_name", "faellig_am"],
    "tasks": ["title", "phase", "art", "prioritaet", "due_at", "assigned_to", "kontakt_name", "company_name"],
}

VORGABE_SORTIERUNG = {"feld": "updated_at", "richtung": "desc"}

# Der Präfix, an dem eine selbst angelegte Eigenschaft erkennbar ist.
CUSTOM_PRAEFIX = "custom."


def _feld(entity: str, schluessel: str) -> Feld | None:
    for f in FELDER[entity]:
        if f.schluessel == schluessel:
            return f
    return None


async def felder_fuer(conn: asyncpg.Connection, entity: str) -> list[dict[str, Any]]:
    """Alle Felder eines Objekts — feste plus selbst angelegte.

    Die Oberfläche baut daraus die Spaltenwahl und den Filterbau. Sie
    kennt die Feldliste dadurch nicht doppelt.
    """
    if entity not in FELDER:
        raise Ungueltig(f"Unbekanntes Objekt: {entity}")

    from app import eigenschaften

    # Die Arten heißen in `property_definitions` englisch (`property_kind`),
    # in der Oberfläche deutsch. Hier ist die eine Stelle, an der beide
    # zusammenkommen.
    art_aus_eigenschaft: dict[str, Art] = {
        "text": "text",
        "number": "zahl",
        "date": "datum",
        "bool": "jaNein",
        "select": "auswahl",
        "multiselect": "mehrfachauswahl",
    }

    liste = [
        {
            "schluessel": f.schluessel,
            "text": f.text,
            "art": f.art,
            "optionen": f.optionen,
            "filterbar": f.filterbar,
            "zahl": f.zahl,
            "eigen": False,
            "operatoren": OPERATOREN[f.art],
        }
        for f in FELDER[entity]
    ]

    if entity not in CUSTOM_SPALTE:
        return liste

    for d in await eigenschaften.definitionen(conn, entity):
        art = art_aus_eigenschaft.get(d["kind"], "text")
        liste.append(
            {
                "schluessel": CUSTOM_PRAEFIX + d["key"],
                "text": d["label"],
                "art": art,
                # Archivierte Optionen bleiben im Filter wählbar: Wer den
                # Wert aus dem Verkehr zieht, will die Datensätze, die ihn
                # noch tragen, gerade dann finden können.
                "optionen": eigenschaften.optionen(d["options"]),
                "filterbar": True,
                "zahl": art == "zahl",
                "eigen": True,
                "operatoren": OPERATOREN[art],
            }
        )
    return liste


def _relatives_datum(tage: Any) -> datetime:
    try:
        zahl = int(tage)
    except (TypeError, ValueError) as exc:
        raise Ungueltig("Ein Zeitraum braucht eine Anzahl Tage.") from exc
    if zahl < 0:
        raise Ungueltig("Ein Zeitraum kann nicht negativ sein.")
    return datetime.now().astimezone() - _tage(zahl)


def _tage(zahl: int):
    from datetime import timedelta

    return timedelta(days=zahl)


def _als_datum(wert: Any) -> datetime:
    """Nimmt ein ISO-Datum aus der Bedingung entgegen."""
    if isinstance(wert, datetime):
        return wert
    text = str(wert or "").strip()
    try:
        if len(text) == 10:
            return datetime.combine(date.fromisoformat(text), datetime.min.time()).astimezone()
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise Ungueltig(f"Kein lesbares Datum: {text!r}") from exc


@dataclass
class Bedingung:
    feld: str
    operator: str
    wert: Any = None


def _sql_und_art(entity: str, schluessel: str, args: list[Any]) -> tuple[str, Art]:
    """Gibt den SQL-Ausdruck für ein Feld zurück — und dessen Art.

    Für eine selbst angelegte Eigenschaft ist der Ausdruck
    `custom ->> $n`: Der Schlüssel geht als **Parameter** hinein, nicht
    als Text in die Abfrage. Damit ist auch ein frei gewählter
    Eigenschaftsname unbedenklich.
    """
    if schluessel.startswith(CUSTOM_PRAEFIX):
        name = schluessel[len(CUSTOM_PRAEFIX) :]
        if not name:
            raise Ungueltig("Eine eigene Eigenschaft braucht einen Namen.")
        if entity not in CUSTOM_SPALTE:
            raise Ungueltig(f"„{entity}“ kennt keine eigenen Eigenschaften.")
        args.append(name)
        return f"({CUSTOM_SPALTE[entity]} ->> ${len(args)})", "text"

    f = _feld(entity, schluessel)
    if f is None:
        raise Ungueltig(f"Unbekanntes Feld: {schluessel}")
    if not f.filterbar:
        raise Ungueltig(f"Nach „{f.text}“ lässt sich nicht filtern.")
    return f.sql, f.art


def _mehrfach_sql(entity: str, b: Bedingung, args: list[Any]) -> str:
    """„hat eines von“, „hat alle von“, „hat keines von“ auf einer Liste.

    Der gespeicherte Wert ist eine jsonb-Liste, also wird auch mit
    jsonb-Mitteln gefragt: `?|` prüft auf Schnittmenge, `?&` auf
    Enthaltensein aller. Beide bedient der GIN-Index aus 0015 — ein
    Umweg über `->> ... ilike '%wert%'` täte es fachlich auch und wäre
    bei „Nord“ und „Nordost“ falsch.

    `coalesce(..., false)`, weil ein fehlender Schlüssel SQL-NULL liefert
    und NULL in einer WHERE-Klausel nicht „nein“ heißt, sondern
    „unbekannt“ — bei `hat_keines_von` wäre das der Unterschied zwischen
    „alle ohne diese Werte“ und „alle, die überhaupt etwas eingetragen
    haben“.
    """
    if not b.feld.startswith(CUSTOM_PRAEFIX):
        raise Ungueltig(f"„{b.operator}“ gibt es nur an einer Mehrfachauswahl.")
    name = b.feld[len(CUSTOM_PRAEFIX) :]
    if not name:
        raise Ungueltig("Eine eigene Eigenschaft braucht einen Namen.")
    if entity not in CUSTOM_SPALTE:
        raise Ungueltig(f"„{entity}“ kennt keine eigenen Eigenschaften.")

    werte = b.wert if isinstance(b.wert, list) else ([b.wert] if b.wert else [])
    werte = [str(w) for w in werte if str(w).strip()]
    if not werte:
        raise Ungueltig("Dieser Vergleich braucht mindestens einen Wert.")

    args.append(name)
    ausdruck = f"({CUSTOM_SPALTE[entity]} -> ${len(args)})"
    args.append(werte)
    liste = f"${len(args)}::text[]"

    alle = f"coalesce({ausdruck} ?& {liste}, false)"
    eines = f"coalesce({ausdruck} ?| {liste}, false)"
    return {
        "hat_alle_von": alle,
        "hat_nicht_alle_von": f"not {alle}",
        "hat_eines_von": eines,
        "hat_keines_von": f"not {eines}",
    }[b.operator]


def bedingung_zu_sql(entity: str, b: Bedingung, args: list[Any]) -> str:
    """Eine einzelne Bedingung als SQL-Fragment; Werte gehen in `args`."""
    if b.operator in MEHRFACH_OPERATOREN:
        return _mehrfach_sql(entity, b, args)

    ausdruck, art = _sql_und_art(entity, b.feld, args)
    op = b.operator

    if op not in OPERATOREN.get(art, []) and not (
        b.feld.startswith(CUSTOM_PRAEFIX) and op in OPERATOREN["text"] + OPERATOREN["zahl"] + OPERATOREN["datum"]
    ):
        raise Ungueltig(f"„{op}“ passt nicht zu diesem Feld.")

    if op == "leer":
        return f"({ausdruck} is null or {ausdruck}::text = '')"
    if op == "nicht_leer":
        return f"({ausdruck} is not null and {ausdruck}::text <> '')"
    if op == "ist_wahr":
        return f"({ausdruck})::text in ('true','t','1','ja')"
    if op == "ist_falsch":
        return f"(({ausdruck}) is null or ({ausdruck})::text in ('false','f','0','nein'))"

    if b.wert is None or (isinstance(b.wert, str) and not b.wert.strip()):
        raise Ungueltig(f"„{op}“ braucht einen Wert.")

    if op == "ist_eines_von":
        werte = b.wert if isinstance(b.wert, list) else [b.wert]
        if not werte:
            raise Ungueltig("„ist eines von“ braucht mindestens einen Wert.")
        args.append([str(w) for w in werte])
        return f"({ausdruck})::text = any(${len(args)}::text[])"

    if art in ("zahl",) and op in ("ist", "groesser", "kleiner"):
        try:
            args.append(float(b.wert))
        except (TypeError, ValueError) as exc:
            raise Ungueltig(f"„{b.wert}“ ist keine Zahl.") from exc
        zeichen = {"ist": "=", "groesser": ">", "kleiner": "<"}[op]
        # Bei einer eigenen Eigenschaft steht die Zahl als Text in JSON.
        guss = "::numeric" if not b.feld.startswith(CUSTOM_PRAEFIX) else "::numeric"
        return f"(nullif({ausdruck}::text,'')){guss} {zeichen} ${len(args)}"

    if art == "datum" or (b.feld.startswith(CUSTOM_PRAEFIX) and op in ("nach", "vor", "letzte_tage", "aelter_als_tage")):
        guss = f"(nullif({ausdruck}::text,''))::timestamptz"
        if op == "letzte_tage":
            args.append(_relatives_datum(b.wert))
            return f"{guss} >= ${len(args)}"
        if op == "aelter_als_tage":
            args.append(_relatives_datum(b.wert))
            return f"{guss} < ${len(args)}"
        args.append(_als_datum(b.wert))
        return f"{guss} {'>=' if op == 'nach' else '<'} ${len(args)}"

    # Text, Auswahl, Person
    if op in ("ist", "ist_nicht"):
        args.append(str(b.wert))
        return f"({ausdruck})::text {'=' if op == 'ist' else 'is distinct from'} ${len(args)}"
    if op in ("enthaelt", "enthaelt_nicht"):
        args.append(f"%{b.wert}%")
        return f"({ausdruck})::text {'ilike' if op == 'enthaelt' else 'not ilike'} ${len(args)}"
    if op == "beginnt_mit":
        args.append(f"{b.wert}%")
        return f"({ausdruck})::text ilike ${len(args)}"

    raise Ungueltig(f"Unbekannter Operator: {op}")


def filter_zu_sql(entity: str, bedingungen: list[Bedingung], args: list[Any], *, verknuepfung: str = "und") -> str:
    """Alle Bedingungen zu einem WHERE-Zusatz. Leer heißt: kein Zusatz."""
    if entity not in FELDER:
        raise Ungueltig(f"Unbekanntes Objekt: {entity}")
    if not bedingungen:
        return ""
    if verknuepfung not in ("und", "oder"):
        raise Ungueltig("Bedingungen werden mit „und“ oder „oder“ verknüpft.")
    if len(bedingungen) > 20:
        raise Ungueltig("Mehr als zwanzig Bedingungen sind keine Liste mehr, sondern ein Bericht.")
    teile = [bedingung_zu_sql(entity, b, args) for b in bedingungen]
    trenner = " and " if verknuepfung == "und" else " or "
    return " and (" + trenner.join(teile) + ")"


def sortierung_zu_sql(entity: str, feld: str | None, richtung: str | None) -> str:
    """`order by` aus einem Feldnamen — nur aus der Whitelist."""
    schluessel = feld or VORGABE_SORTIERUNG["feld"]
    richtung_sql = "desc" if (richtung or VORGABE_SORTIERUNG["richtung"]).lower() == "desc" else "asc"

    if schluessel.startswith(CUSTOM_PRAEFIX):
        # Eigene Eigenschaften stehen als Text im JSON; sortiert wird als
        # Text. Der Schlüssel kann hier nicht als Parameter gebunden
        # werden (order by nimmt keine Parameter), deshalb wird er auf
        # unbedenkliche Zeichen geprüft — dieselbe Regel, mit der er
        # angelegt wurde.
        name = schluessel[len(CUSTOM_PRAEFIX) :]
        if not name.replace("_", "").isalnum():
            raise Ungueltig(f"Unbrauchbarer Eigenschaftsname: {name}")
        return f" order by {CUSTOM_SPALTE[entity]} ->> '{name}' {richtung_sql} nulls last"

    f = _feld(entity, schluessel)
    if f is None:
        raise Ungueltig(f"Nach „{schluessel}“ lässt sich nicht sortieren.")
    return f" order by {f.sql} {richtung_sql} nulls last"


def bedingungen_aus(roh: Any) -> list[Bedingung]:
    """Aus dem JSON der Anfrage werden geprüfte Bedingungen."""
    if roh in (None, "", []):
        return []
    if not isinstance(roh, list):
        raise Ungueltig("Ein Filter ist eine Liste von Bedingungen.")
    fertig: list[Bedingung] = []
    for eintrag in roh:
        if not isinstance(eintrag, dict):
            raise Ungueltig("Jede Bedingung ist ein Objekt mit Feld und Operator.")
        feld = str(eintrag.get("feld") or "").strip()
        operator = str(eintrag.get("operator") or "").strip()
        if not feld or not operator:
            raise Ungueltig("Jede Bedingung braucht Feld und Operator.")
        wert = eintrag.get("wert")
        if operator in OHNE_WERT:
            wert = None
        fertig.append(Bedingung(feld=feld, operator=operator, wert=wert))
    return fertig
