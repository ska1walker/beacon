"""Sicherung und Wiederherstellung des gesamten Bestands.

Der Grund, warum es diese Datei überhaupt gibt: Eine Deinstallation über
den Olares-Markt löscht die Datenbank. `/app/data` überlebt, die Datenbank
nicht — Olares legt sie neu an, samt neuer Org-Kennung. Für ein CRM hieße
das ohne Gegenmaßnahme: sämtliche Firmen, Kontakte, Geschäfte und der
ganze Verlauf weg, ohne Weg zurück.

Deshalb liegt neben den Daten ein vollständiger Abzug, und die Anwendung
liest ihn beim Start zurück, **wenn die Organisation leer ist**. Dasselbe
Muster wie `konfiguration.py` in Insilo, nur dass hier alles daran hängt
und nicht nur die Einrichtung.

Der Abzug enthält Zugangsdaten (den Schlüssel zum Sprachmodell) und liegt
deshalb mit Rechten 0600.
"""

from __future__ import annotations

import hashlib
import json
import os
import pathlib
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import asyncpg

from app.config import settings

# Reihenfolge ist Abhängigkeitsreihenfolge. Beim Zurückspielen muss die
# Firma vor dem Kontakt stehen und die Stufe vor dem Geschäft, sonst
# greift der Fremdschlüssel.
TABELLEN: list[str] = [
    "property_definitions",
    "companies",
    "pipelines",
    "pipeline_stages",
    "products",
    "loss_reasons",
    "webhook_sources",
    "contacts",
    "anreicherungen",
    "ticket_pipelines",
    "ticket_stages",
    "ticket_kategorien",
    "deals",
    "deal_contacts",
    "contact_companies",
    "quotes",
    "quote_items",
    "tickets",
    "activities",
    "aussagen",
    "auswertungen",
    "themenlaeufe",
    "tasks",
    # Die Zeile trägt den Pfad, unter dem die Datei liegt — samt der
    # alten Org-Kennung. Sie wird beim Zurückspielen **nicht**
    # umgeschrieben: `/app/data` überlebt eine Neuinstallation, der
    # alte Ordner steht also noch da, und ein umgeschriebener Pfad
    # zeigte ins Leere.
    "dokumente",
    "podcasts",
    "eingang",
    "ansichten",
    "listen",
    "listen_mitglieder",
    "vorlagen",
    "kampagnen",
    # Links und Mails zeigen auf Kampagnen — sie kommen danach.
    "oeffentliche_links",
    "mails",
    # Was eine Einfuhr getan und übersprungen hat. Die Datei selbst
    # bewahrt Beacon nicht auf — ohne diese Zeile ließe sich ein Import
    # nach einer Neuinstallation nicht mehr erklären.
    "einfuhren",
    "audit_log",
    # Offene Einladungen überleben eine Neuinstallation, damit ein Link,
    # den jemand schon in der Hand hat, weiter trägt. `sitzungen` und
    # `anmeldeversuche` bewusst nicht: Eine zurückgespielte Sitzung wäre
    # ein Wiedereinspielen von Zugängen, und eine zurückgespielte Bremse
    # sperrte Menschen für etwas aus, das lange her ist.
    "einladungen",
]

# Tabellen, die bewusst nicht im Abzug stehen: Identität und Zugehörigkeit
# legt Olares beim Anmelden neu an (die Nutzer gehen gesondert mit, siehe
# `nutzer`), und die Einstellungen gehen als eigener Block.
# Absichtlich nicht im Abzug. `sitzungen`: Eine zurückgespielte Sitzung
# wäre ein Wiedereinspielen von Zugängen — wer sich vor Wochen abgemeldet
# hat, wäre wieder drin. `anmeldeversuche`: Eine zurückgespielte Bremse
# sperrte Menschen für Tippfehler aus, die lange her sind.
AUSGENOMMEN = {
    "orgs", "users", "user_org_roles", "org_settings",
    "sitzungen", "anmeldeversuche",
}

# Tabellen ohne eigene org_id — sie hängen an einer Elterntabelle.
UEBER_ELTERN: dict[str, str] = {
    "deal_contacts": "select dc.* from public.deal_contacts dc join public.deals d on d.id = dc.deal_id where d.org_id = $1",
    "listen_mitglieder": "select m.* from public.listen_mitglieder m join public.listen l on l.id = m.liste_id where l.org_id = $1",
}

# Spalten, die nicht mit zurückgespielt werden: `org_id` wird auf die
# Zielorganisation gesetzt, die Zeitstempel bleiben, wie sie waren.
EINSTELLUNGEN_NICHT = {"org_id"}

FORMAT_VERSION = 1


def ablage() -> pathlib.Path:
    ordner = pathlib.Path(settings.app_data_dir) / "sicherungen"
    ordner.mkdir(parents=True, exist_ok=True)
    return ordner


# Was an einer Person hängt und mitkommt, wenn die Datenbank neu entsteht.
# Der Rest von `users` fehlt mit Absicht, und `test_sicherung.py` hält
# fest, welche Spalte warum: `created_at`, `last_seen_at` und `deleted_at`
# entstehen neu; `gesperrt_bis` ist eine Bremse von gestern, die niemand
# von damals erben soll.
ABSENDERFELDER = (
    "absender_email", "absender_name", "smtp_host", "smtp_port",
    "smtp_benutzer", "smtp_passwort", "smtp_sicherheit",
)


async def _absender_zurueck(conn, user_id: UUID, eintrag: dict[str, Any]) -> None:
    """Spielt die Absendereinstellungen zurück — nur in leere Felder."""
    if not any(eintrag.get(f) for f in ABSENDERFELDER):
        return
    await conn.execute(
        """
        update public.users set
            absender_email   = coalesce(absender_email, $2),
            absender_name    = coalesce(absender_name, $3),
            smtp_host        = coalesce(smtp_host, $4),
            smtp_port        = coalesce(smtp_port, $5),
            smtp_benutzer    = coalesce(smtp_benutzer, $6),
            smtp_passwort    = coalesce(smtp_passwort, $7),
            smtp_sicherheit  = coalesce(smtp_sicherheit, $8)
        where id = $1
        """,
        user_id,
        eintrag.get("absender_email"), eintrag.get("absender_name"),
        eintrag.get("smtp_host"),
        int(eintrag["smtp_port"]) if eintrag.get("smtp_port") else None,
        eintrag.get("smtp_benutzer"), eintrag.get("smtp_passwort"),
        eintrag.get("smtp_sicherheit"),
    )


def _zeit(wert: Any) -> datetime | None:
    """Ein Zeitstempel aus dem Abzug — dort steht er als ISO-Text."""
    if isinstance(wert, datetime):
        return wert
    if isinstance(wert, str) and wert:
        try:
            return datetime.fromisoformat(wert)
        except ValueError:
            return None
    return None


def _wandelbar(wert: Any) -> Any:
    """asyncpg gibt UUID, datetime, date und Decimal zurück — JSON nicht."""
    if isinstance(wert, UUID):
        return str(wert)
    if hasattr(wert, "isoformat"):
        return wert.isoformat()
    if isinstance(wert, memoryview):
        return wert.hex()
    return str(wert)


async def abzug_erstellen(conn: asyncpg.Connection, org_id: UUID) -> dict[str, Any]:
    """Alles, was zu dieser Organisation gehört, als eine Struktur."""
    org = await conn.fetchrow("select name, slug, settings from public.orgs where id = $1", org_id)

    daten: dict[str, Any] = {
        "format": FORMAT_VERSION,
        "erstellt_am": datetime.now(UTC).isoformat(),
        "organisation": {
            "id": str(org_id),
            "name": org["name"] if org else None,
            "slug": org["slug"] if org else None,
        },
        "tabellen": {},
    }

    # Die Nutzer kommen mit, damit „wem gehört dieser Deal" nach einer
    # Neuinstallation nicht ins Leere zeigt.
    nutzer = await conn.fetch(
        """
        select u.id, u.olares_username, u.display_name, u.email, u.zugang, u.einstellungen,
               u.passwort_hash, u.passwort_am, u.totp_geheimnis,
               u.absender_email, u.absender_name, u.smtp_host, u.smtp_port,
               u.smtp_benutzer, u.smtp_passwort, u.smtp_sicherheit,
               r.role
        from public.users u
        join public.user_org_roles r on r.user_id = u.id
        where r.org_id = $1
        """,
        org_id,
    )
    daten["nutzer"] = [
        {k: _wandelbar(v) if not isinstance(v, str | int | float | bool | type(None)) else v
         for k, v in dict(z).items()}
        for z in nutzer
    ]

    for tabelle in TABELLEN:
        if tabelle in UEBER_ELTERN:
            zeilen = await conn.fetch(UEBER_ELTERN[tabelle], org_id)
        else:
            zeilen = await conn.fetch(
                f"select * from public.{tabelle} where org_id = $1", org_id
            )
        daten["tabellen"][tabelle] = [
            {
                k: (v if isinstance(v, str | int | float | bool | type(None)) else _wandelbar(v))
                for k, v in dict(z).items()
            }
            for z in zeilen
        ]

    einstellungen = await conn.fetchrow(
        "select * from public.org_settings where org_id = $1", org_id
    )
    daten["einstellungen"] = (
        {
            k: (v if isinstance(v, str | int | float | bool | type(None)) else _wandelbar(v))
            for k, v in dict(einstellungen).items()
        }
        if einstellungen
        else {}
    )

    return daten


def abzug_kennung(daten: dict[str, Any]) -> str:
    """Ein Fingerabdruck des Inhalts — ohne den Zeitstempel der Erstellung.

    Zwei Abzüge mit gleicher Kennung enthalten dasselbe. Die Schleife
    schreibt nur, wenn sich die Kennung bewegt hat: Sonst füllte sie die
    Ablage alle fünf Minuten mit demselben Stand.
    """
    ohne_zeit = {k: v for k, v in daten.items() if k != "erstellt_am"}
    return hashlib.sha256(json.dumps(ohne_zeit, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def abzug_schreiben(daten: dict[str, Any], slug: str | None = None) -> pathlib.Path:
    """Schreibt den Abzug und räumt alte Stände weg.

    Erst in eine Nebendatei, dann umbenennen: Ein Stromausfall mitten im
    Schreiben hinterlässt sonst eine halbe Sicherung, die aussieht wie
    eine ganze.
    """
    marke = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    name = f"beacon-{slug or 'org'}-{marke}.json"
    ziel = ablage() / name
    vorlaeufig = ziel.with_suffix(".json.teil")

    vorlaeufig.write_text(json.dumps(daten, ensure_ascii=False, indent=2))
    # Der Abzug trägt den Schlüssel zum Sprachmodell. 0600, bevor er
    # unter seinem endgültigen Namen sichtbar wird.
    os.chmod(vorlaeufig, 0o600)
    vorlaeufig.rename(ziel)

    aufraeumen()
    return ziel


def _abzuege() -> list[pathlib.Path]:
    """Alle Abzüge — auch die, die noch `aicrm-` heißen: Eine Umbenennung
    des Produkts darf keinen Bestand verlieren."""
    return [*ablage().glob("beacon-*.json"), *ablage().glob("aicrm-*.json")]


def aufraeumen() -> None:
    staende = sorted(_abzuege(), reverse=True)
    for alt in staende[settings.sicherung_behalten :]:
        alt.unlink(missing_ok=True)


def staende() -> list[dict[str, Any]]:
    ergebnis = []
    for datei in sorted(_abzuege(), reverse=True):
        stat = datei.stat()
        ergebnis.append(
            {
                "name": datei.name,
                "groesse_bytes": stat.st_size,
                "erstellt_am": datetime.fromtimestamp(stat.st_mtime, UTC).isoformat(),
            }
        )
    return ergebnis


def abzug_lesen(name: str) -> dict[str, Any]:
    # Kein Pfad, nur ein Name: Ein '../' im Parameter würde sonst jede
    # Datei der Box lesbar machen.
    datei = ablage() / pathlib.Path(name).name
    if not datei.is_file():
        raise FileNotFoundError(name)
    return json.loads(datei.read_text())


async def _nutzerzuordnung(
    conn: asyncpg.Connection, daten: dict[str, Any], ersatz: UUID, ziel_org: UUID
) -> dict[str, UUID]:
    """Alte Nutzer-Kennung → heutige, über den Olares-Namen.

    Personen ohne eigenen Olares-Zugang werden dabei **wieder angelegt**.
    Ohne das verschwände nach einer Neuinstallation jeder Sitzplatz, und
    alles, was Marc gehörte, gehörte plötzlich dem, der die
    Wiederherstellung ausgelöst hat. Besitz und Protokoll wären damit
    stillschweigend umgeschrieben — schlimmer als ein Datenverlust, weil
    es niemandem auffällt.
    """
    zuordnung: dict[str, UUID] = {}
    for eintrag in daten.get("nutzer", []):
        name = eintrag.get("olares_username")
        if not name:
            continue

        heutige = await conn.fetchval(
            "select id from public.users where olares_username = $1", name
        )

        # Was die Person für sich eingestellt hatte, kommt mit — im Abzug
        # als Text (kein JSON-Codec am Pool), zur Sicherheit auch als dict.
        einst = eintrag.get("einstellungen") or "{}"
        if not isinstance(einst, str):
            einst = json.dumps(einst)

        if heutige is None and eintrag.get("zugang") == "sitzplatz":
            heutige = await conn.fetchval(
                """
                insert into public.users
                  (olares_username, display_name, email, zugang, einstellungen,
                   passwort_hash, passwort_am)
                values ($1, $2, $3, 'sitzplatz', $4::jsonb, $5, $6)
                on conflict (olares_username) do update set display_name = excluded.display_name
                returning id
                """,
                name,
                eintrag.get("display_name"),
                eintrag.get("email"),
                einst,
                eintrag.get("passwort_hash"),
                _zeit(eintrag.get("passwort_am")),
            )
        elif heutige is not None:
            # Wer schon da ist und schon etwas eingestellt hat, behält es —
            # Wiederherstellen füllt nur, was leer ist.
            await conn.execute(
                "update public.users set einstellungen = $2::jsonb "
                "where id = $1 and einstellungen = '{}'::jsonb",
                heutige, einst,
            )
            # Der Passwort-Hash kommt mit — sonst stünde nach einer
            # Neuinstallation im Modus `eigen` niemand mehr vor der Tür,
            # der hineinkäme: Der Olares-Kopf zählt dort nicht mehr. Nur
            # füllen, nie überschreiben; ein neu gesetztes Passwort gewinnt.
            if eintrag.get("passwort_hash"):
                await conn.execute(
                    "update public.users set passwort_hash = $2, passwort_am = $3, "
                    "totp_geheimnis = coalesce(public.users.totp_geheimnis, $4) "
                    "where id = $1 and passwort_hash is null",
                    heutige, eintrag["passwort_hash"], _zeit(eintrag.get("passwort_am")),
                    eintrag.get("totp_geheimnis"),
                )
            # Und womit diese Person schickt. Ohne das trüge nach einer
            # Neuinstallation wieder jeder die Adresse der Organisation —
            # die Einstellung wäre still verschwunden. Auch hier gilt:
            # füllen, nicht überschreiben.
            await _absender_zurueck(conn, heutige, eintrag)

        if heutige is not None:
            # Die Mitgliedschaft gehört dazu: Ohne sie könnte der Sitzplatz
            # nicht wieder eingenommen werden (siehe _sitzplatz_einnehmen).
            await conn.execute(
                "insert into public.user_org_roles (user_id, org_id, role) "
                "values ($1, $2, coalesce($3::public.user_role, 'member')) "
                "on conflict (user_id, org_id) do nothing",
                heutige,
                ziel_org,
                eintrag.get("role"),
            )

        zuordnung[eintrag["id"]] = heutige or ersatz
    return zuordnung


async def zurueckspielen(
    conn: asyncpg.Connection,
    daten: dict[str, Any],
    ziel_org: UUID,
    handelnder: UUID,
    *,
    frisch: bool = False,
) -> dict[str, dict[str, int]]:
    """Spielt einen Abzug in die angegebene Organisation zurück.

    Vorhandene Zeilen bleiben unangetastet (`on conflict do nothing`).
    Das ist Absicht: Eine Wiederherstellung soll nichts überschreiben, was
    seither entstanden ist — sie füllt auf, was fehlt.

    `frisch` sagt: Die Organisation ist gerade erst entstanden (Wiederanlauf
    nach einer Deinstallation). Dann gelten auch die Einstellungen aus dem
    Abzug ganz — sonst blieben die Vorgaben stehen, die Olares gerade neu
    angelegt hat, und die Wahl des Menschen wäre verloren.
    """
    if daten.get("format") != FORMAT_VERSION:
        raise ValueError(
            f"Unbekanntes Format {daten.get('format')!r}; diese Fassung liest {FORMAT_VERSION}."
        )

    nutzer = await _nutzerzuordnung(conn, daten, handelnder, ziel_org)
    bilanz: dict[str, int] = {}
    uebersprungen: dict[str, int] = {}

    bilanz["einstellungen"] = await _einstellungen_zurueckspielen(
        conn, daten.get("einstellungen") or {}, ziel_org, nutzer, handelnder, ueberschreiben=frisch
    )

    for tabelle in TABELLEN:
        zeilen = daten["tabellen"].get(tabelle, [])
        typen = await _spaltentypen(conn, tabelle)
        nutzerspalten = await _nutzerspalten(conn, tabelle)
        gesetzt = 0
        schon_da = 0

        for zeile in zeilen:
            werte = dict(zeile)
            if "org_id" in werte:
                werte["org_id"] = str(ziel_org)
            for spalte in nutzerspalten:
                alt = werte.get(spalte)
                if alt:
                    werte[spalte] = str(nutzer.get(alt, handelnder))

            # Spaltennamen aus dem Abzug werden gegen die tatsächlichen
            # Spalten geprüft, nicht geglaubt: Ein manipulierter Abzug soll
            # keinen eigenen Bezeichner ins SQL schieben können.
            unbekannt = set(werte) - set(typen)
            if unbekannt:
                raise ValueError(f"{tabelle}: unbekannte Spalten im Abzug: {sorted(unbekannt)}")

            spalten = list(werte.keys())
            # Alles geht als Text hinaus und wird in der Anweisung auf den
            # echten Spaltentyp gecastet. Der direkte Weg ginge nicht: Im
            # Abzug ist eine UUID ein String, und asyncpg reicht einen
            # String nicht an eine uuid-Spalte durch. Ein Cast je Spaltentyp
            # deckt uuid, Zeitstempel, Datum, numeric, jsonb und die
            # Aufzählungstypen mit derselben Zeile ab.
            platzhalter = ", ".join(
                f"${i + 1}::text::{typen[name]}" for i, name in enumerate(spalten)
            )
            # `returning id` statt eines blinden execute: Bei `do nothing`
            # kommt nichts zurück, und nur so ist der Unterschied zwischen
            # „geschrieben" und „war schon da" zu sehen. Eine Bilanz, die
            # gelesene Zeilen als geschriebene meldet, ist schlimmer als
            # keine — sie behauptet eine Rettung, die nicht stattfand.
            geschrieben = await conn.fetchval(
                f"insert into public.{tabelle} ({', '.join(spalten)}) "
                f"values ({platzhalter}) on conflict do nothing returning 1",
                *[_als_text(werte[name]) for name in spalten],
            )
            if geschrieben:
                gesetzt += 1
            else:
                schon_da += 1

        bilanz[tabelle] = gesetzt
        uebersprungen[tabelle] = schon_da

    return {"geschrieben": bilanz, "uebersprungen": uebersprungen}


_typen_zwischenspeicher: dict[str, dict[str, str]] = {}
_nutzerspalten_zwischenspeicher: dict[str, list[str]] = {}


async def _nutzerspalten(conn: asyncpg.Connection, tabelle: str) -> list[str]:
    """Welche Spalten dieser Tabelle auf public.users zeigen — aus den
    Fremdschlüsseln der Datenbank, nicht aus einer Liste.

    Eine gepflegte Liste vergisst die nächste Tabelle, und dann scheitert
    die Wiederherstellung an genau dem Fremdschlüssel, den niemand
    eingetragen hat. Die Datenbank weiß es immer.
    """
    if tabelle not in _nutzerspalten_zwischenspeicher:
        zeilen = await conn.fetch(
            """
            select a.attname
              from pg_constraint c
              join pg_attribute a on a.attrelid = c.conrelid and a.attnum = any(c.conkey)
             where c.contype = 'f'
               and c.conrelid = ('public.' || quote_ident($1))::regclass
               and c.confrelid = 'public.users'::regclass
            """,
            tabelle,
        )
        _nutzerspalten_zwischenspeicher[tabelle] = [z["attname"] for z in zeilen]
    return _nutzerspalten_zwischenspeicher[tabelle]


async def _einstellungen_zurueckspielen(
    conn: asyncpg.Connection,
    einstellungen: dict[str, Any],
    ziel_org: UUID,
    nutzer: dict[str, UUID],
    handelnder: UUID,
    *,
    ueberschreiben: bool = False,
) -> int:
    """Füllt die Einstellungen der Organisation auf — nur, was leer ist,
    oder alles, wenn die Organisation frisch ist.

    Sprachmodell, Suchdienst, SMTP, Postfach, Absender: Das ist, was ein
    Mensch eingerichtet hat, und es ist nach einer Neuinstallation genauso
    weg wie der Bestand. Vorhandene Werte bleiben, wie beim Bestand.
    """
    if not einstellungen:
        return 0
    typen = await _spaltentypen(conn, "org_settings")
    nutzerspalten = await _nutzerspalten(conn, "org_settings")
    await conn.execute(
        "insert into public.org_settings (org_id) values ($1) on conflict do nothing", ziel_org
    )
    gesetzt = 0
    for spalte, wert in einstellungen.items():
        if spalte in EINSTELLUNGEN_NICHT or spalte not in typen or wert is None:
            continue
        if spalte in nutzerspalten:
            wert = str(nutzer.get(wert, handelnder))
        bedingung = "" if ueberschreiben else f" and {spalte} is null"
        geschrieben = await conn.fetchval(
            f"update public.org_settings set {spalte} = $1::text::{typen[spalte]} "
            f"where org_id = $2{bedingung} returning 1",
            _als_text(wert), ziel_org,
        )
        if geschrieben:
            gesetzt += 1
    return gesetzt


async def _spaltentypen(conn: asyncpg.Connection, tabelle: str) -> dict[str, str]:
    """Spaltenname → Typname, wie Postgres ihn für einen Cast versteht."""
    if tabelle not in _typen_zwischenspeicher:
        zeilen = await conn.fetch(
            """
            select column_name, udt_name
            from information_schema.columns
            where table_schema = 'public' and table_name = $1
            """,
            tabelle,
        )
        _typen_zwischenspeicher[tabelle] = {z["column_name"]: z["udt_name"] for z in zeilen}
    return _typen_zwischenspeicher[tabelle]


def _als_text(wert: Any) -> str | None:
    """Alles als Text; den Rest erledigt der Cast in der Anweisung."""
    if wert is None:
        return None
    if isinstance(wert, dict | list):
        return json.dumps(wert, ensure_ascii=False)
    if isinstance(wert, bool):
        return "true" if wert else "false"
    return str(wert)
