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
    "companies",
    "pipelines",
    "pipeline_stages",
    "products",
    "loss_reasons",
    "contacts",
    "deals",
    "deal_contacts",
    "quotes",
    "quote_items",
    "activities",
    "tasks",
]

# Spalten, die auf public.users zeigen. Beim Zurückspielen nach einer
# Neuinstallation gibt es die alten Nutzer-Kennungen nicht mehr; sie
# werden über den Olares-Namen zugeordnet und sonst auf den
# Wiederherstellenden gesetzt.
NUTZERSPALTEN: dict[str, list[str]] = {
    "companies": ["owner_id", "created_by"],
    "quotes": ["created_by"],
    "contacts": ["owner_id", "created_by"],
    "deals": ["owner_id", "created_by"],
    "activities": ["created_by"],
    "tasks": ["assigned_to", "created_by"],
}

FORMAT_VERSION = 1


def ablage() -> pathlib.Path:
    ordner = pathlib.Path(settings.app_data_dir) / "sicherungen"
    ordner.mkdir(parents=True, exist_ok=True)
    return ordner


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
        select u.id, u.olares_username, u.display_name, r.role
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
        if tabelle == "deal_contacts":
            # Hängt am Deal, hat selbst keine org_id.
            zeilen = await conn.fetch(
                """
                select dc.* from public.deal_contacts dc
                join public.deals d on d.id = dc.deal_id
                where d.org_id = $1
                """,
                org_id,
            )
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


def abzug_schreiben(daten: dict[str, Any], slug: str | None = None) -> pathlib.Path:
    """Schreibt den Abzug und räumt alte Stände weg.

    Erst in eine Nebendatei, dann umbenennen: Ein Stromausfall mitten im
    Schreiben hinterlässt sonst eine halbe Sicherung, die aussieht wie
    eine ganze.
    """
    marke = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    name = f"aicrm-{slug or 'org'}-{marke}.json"
    ziel = ablage() / name
    vorlaeufig = ziel.with_suffix(".json.teil")

    vorlaeufig.write_text(json.dumps(daten, ensure_ascii=False, indent=2))
    # Der Abzug trägt den Schlüssel zum Sprachmodell. 0600, bevor er
    # unter seinem endgültigen Namen sichtbar wird.
    os.chmod(vorlaeufig, 0o600)
    vorlaeufig.rename(ziel)

    aufraeumen()
    return ziel


def aufraeumen() -> None:
    staende = sorted(ablage().glob("aicrm-*.json"), reverse=True)
    for alt in staende[settings.sicherung_behalten :]:
        alt.unlink(missing_ok=True)


def staende() -> list[dict[str, Any]]:
    ergebnis = []
    for datei in sorted(ablage().glob("aicrm-*.json"), reverse=True):
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
    conn: asyncpg.Connection, daten: dict[str, Any], ersatz: UUID
) -> dict[str, UUID]:
    """Alte Nutzer-Kennung → heutige, über den Olares-Namen."""
    zuordnung: dict[str, UUID] = {}
    for eintrag in daten.get("nutzer", []):
        heutige = await conn.fetchval(
            "select id from public.users where olares_username = $1",
            eintrag.get("olares_username"),
        )
        zuordnung[eintrag["id"]] = heutige or ersatz
    return zuordnung


async def zurueckspielen(
    conn: asyncpg.Connection,
    daten: dict[str, Any],
    ziel_org: UUID,
    handelnder: UUID,
) -> dict[str, dict[str, int]]:
    """Spielt einen Abzug in die angegebene Organisation zurück.

    Vorhandene Zeilen bleiben unangetastet (`on conflict do nothing`).
    Das ist Absicht: Eine Wiederherstellung soll nichts überschreiben, was
    seither entstanden ist — sie füllt auf, was fehlt.
    """
    if daten.get("format") != FORMAT_VERSION:
        raise ValueError(
            f"Unbekanntes Format {daten.get('format')!r}; diese Fassung liest {FORMAT_VERSION}."
        )

    nutzer = await _nutzerzuordnung(conn, daten, handelnder)
    bilanz: dict[str, int] = {}
    uebersprungen: dict[str, int] = {}

    for tabelle in TABELLEN:
        zeilen = daten["tabellen"].get(tabelle, [])
        typen = await _spaltentypen(conn, tabelle)
        gesetzt = 0
        schon_da = 0

        for zeile in zeilen:
            werte = dict(zeile)
            if "org_id" in werte:
                werte["org_id"] = str(ziel_org)
            for spalte in NUTZERSPALTEN.get(tabelle, []):
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
