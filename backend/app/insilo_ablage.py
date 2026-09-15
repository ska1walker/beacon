"""Besprechungen aus Insilos gemeinsamem Ordner lesen — so wie Relay.

**Warum es das neben dem Webhook gibt.** Auf derselben Box braucht es
keinen Webhook: Insilo legt jede fertige Zusammenfassung als Datei in den
geteilten Olares-Ordner `appCommon` (`insilo/backend/app/relay_drop.py`,
seit Insilo 0.1.93), und Beacon liest dort mit — ohne Quelle, ohne
Geheimnis, ohne dass jemand in Insilo etwas einstellt. Relay, die
Mail-App, liest denselben Ordner; beide lesen nur, geschrieben wird er
allein von Insilo.

**Vertrag (schema 1).** Eine Datei je Besprechung,
`<YYYY-MM-DD>T<HH>_<MM>--<id8>.md`. Vorne ein Kopf in einem Mini-Dialekt —
eine `schluessel: wert`-Zeile je Angabe, Texte in Anführungszeichen, Listen
als JSON —, dahinter Insilos kanonisches Markdown, **ohne** den Wortlaut.
Das Markdown trägt seinen eigenen Kopf mit den Sprechern, genau wie im
Webhook; `besprechungen.speichern` liest es deshalb unverändert.

**Was fehlt gegenüber dem Webhook.** Die Vorlagenfelder kommen nicht als
JSON, nur als Abschnitte im Markdown. Die Abschnitte, in denen Menschen
stehen („Anwesende", „Kunde", „Mandant"), liest `_zusammenfassung_aus`
zurück — mehr braucht der Vorschlag nicht. Löschen und Umbenennen gibt es
nicht als Ereignis; eine Datei, die nicht mehr da ist, heißt: in Insilo
gelöscht.

**Welche Organisation.** Der Ordner gehört der Box, nicht einer
Organisation in Beacon. Eine Organisation liest ihn, wenn sie es
eingeschaltet hat (`org_settings.insilo_ablage = true`) — oder, solange
niemand etwas eingestellt hat, wenn sie die einzige auf der Box ist. So
braucht der Normalfall keine Einrichtung, und auf einer Box mit zwei
Organisationen landen die Gespräche der einen nicht still bei der anderen.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

import asyncpg

from app import besprechungen
from app.config import settings

log = logging.getLogger(__name__)

SCHEMA = 1

# Abschnitte in Insilos Markdown, in denen Menschen stehen — rückwärts zu
# den Vorlagenfeldern, die `besprechungen.beteiligte_aus` kennt
# (insilo/backend/app/exports/markdown.py, `_SECTION_TITLES`).
ABSCHNITT_ZU_FELD = {
    "anwesende": "anwesende",
    "teilnehmer": "teilnehmer",
    "teilnehmende": "teilnehmende",
    "kunde": "kunde",
    "mandant": "mandantenname",
    "gesprächspartner": "gespraechspartner",
    "gespraechspartner": "gespraechspartner",
    "ansprechpartner": "ansprechpartner",
}

# Wie weit ein Lauf zurückliegt — für die Einstellungen, nicht für die
# Logik. Eine Zahl je Organisation, im Speicher: Nach einem Neustart steht
# „noch nicht gelesen", bis die Schleife das erste Mal da war.
STAND: dict[str, dict[str, Any]] = {}


class AblageFehlt(Exception):  # noqa: N818 — ein Zustand, kein Fehlerfall im Sinne von „Error"
    """Der Ordner ist nicht eingehängt oder nicht lesbar."""


def verzeichnis() -> Path | None:
    """Der eingehängte Ordner, oder `None`, wenn das Chart keinen einhängt."""
    roh = (settings.insilo_ablage_dir or "").strip()
    return Path(roh) if roh else None


def wirksam(einstellung: bool | None, organisationen: int) -> bool:
    """Liest diese Organisation den Ordner?"""
    if einstellung is not None:
        return einstellung
    return organisationen == 1


# ── Eine Datei ──────────────────────────────────────────────────────────


@dataclass
class Datei:
    insilo_id: str
    titel: str | None
    recorded_at: datetime | None
    dauer_sek: int | None
    vorlage: str | None
    schlagworte: list[str]
    markdown: str
    zusammenfassung: dict[str, Any] = field(default_factory=dict)


def _wert(roh: str) -> Any:
    roh = roh.strip()
    if roh in ("", "''", '""'):
        return ""
    if roh[0] == '"' and roh[-1] == '"' and len(roh) >= 2:
        return roh[1:-1]
    if roh[0] == "[":
        try:
            return json.loads(roh)
        except ValueError:
            return []
    if re.fullmatch(r"-?\d+", roh):
        return int(roh)
    return roh


def lesen(text: str) -> Datei | None:
    """Eine Ablagedatei, oder `None`, wenn sie nicht dem Vertrag entspricht.

    Ein unbekanntes Schema wird nicht geraten: Liest Beacon ein Format
    falsch, stünde ein falsches Protokoll am Kunden — dann lieber gar keins
    und eine Zeile im Protokoll.
    """
    if not text.startswith("---\n"):
        return None
    ende = text.find("\n---\n", 3)
    if ende == -1:
        return None
    kopf: dict[str, Any] = {}
    for zeile in text[4:ende].split("\n"):
        schluessel, trenner, wert = zeile.partition(":")
        if trenner:
            kopf[schluessel.strip()] = _wert(wert)
    if kopf.get("schema") != SCHEMA or not str(kopf.get("insilo_id") or "").strip():
        return None

    markdown = text[ende + len("\n---\n") :]
    dauer = kopf.get("duration_min")
    return Datei(
        insilo_id=str(kopf["insilo_id"]).strip(),
        titel=str(kopf.get("title") or "") or None,
        recorded_at=besprechungen._zeitpunkt(kopf.get("recorded_at")),
        dauer_sek=dauer * 60 if isinstance(dauer, int) and dauer > 0 else None,
        vorlage=str(kopf.get("template") or "") or None,
        schlagworte=[str(t) for t in kopf.get("tags") or [] if str(t).strip()],
        markdown=markdown,
        zusammenfassung=_zusammenfassung_aus(markdown),
    )


def _zusammenfassung_aus(markdown: str) -> dict[str, Any]:
    """Die Vorlagenfelder mit Menschen, zurückgelesen aus den Abschnitten.

    Insilo schreibt einen Text als Zeile, eine Liste als `- eintrag`, eine
    Liste von Objekten als `- erster Text` mit eingerückten Einzelheiten —
    gelesen werden nur die nicht eingerückten Zeilen.
    """
    felder: dict[str, list[str]] = {}
    aktuell: str | None = None
    for zeile in markdown.split("\n"):
        if zeile.startswith("## "):
            aktuell = ABSCHNITT_ZU_FELD.get(zeile[3:].strip().lower())
            continue
        if zeile.startswith("#"):
            aktuell = None
            continue
        if aktuell is None or not zeile.strip() or zeile.startswith(" "):
            continue
        eintrag = zeile[2:] if zeile.startswith("- ") else zeile
        if eintrag.startswith("[ ]") or eintrag.startswith("[x]"):
            continue
        felder.setdefault(aktuell, []).append(eintrag.strip())
    return dict(felder)


# ── Der Ordner ──────────────────────────────────────────────────────────


def _dateien(ordner: Path) -> dict[str, tuple[Path, str]]:
    """Name → (Pfad, Stand). Ein `.tmp` ist ein halb geschriebener Lauf."""
    if not ordner.is_dir():
        raise AblageFehlt(f"{ordner} ist nicht eingehängt")
    try:
        gefunden = {}
        for pfad in ordner.glob("*.md"):
            info = pfad.stat()
            gefunden[pfad.name] = (pfad, f"{info.st_mtime_ns}:{info.st_size}")
        return gefunden
    except OSError as exc:
        raise AblageFehlt(f"{ordner} ist nicht lesbar: {exc}") from exc


async def einlesen(conn: asyncpg.Connection, org_id: UUID) -> dict[str, Any]:
    """Liest neue und geänderte Dateien, entfernt, was Insilo gelöscht hat.

    Unverändert ist, was Name, Änderungszeit und Größe behalten hat — das
    wird nicht noch einmal gelesen. Gibt die Bilanz zurück und dazu die
    Besprechungen, die einen Vorschlag brauchen.
    """
    ordner = verzeichnis()
    if ordner is None:
        raise AblageFehlt("Kein Ordner eingehängt")
    dateien = _dateien(ordner)

    bekannt = {
        z["ablage_datei"]: z
        for z in await conn.fetch(
            "select id, external_id, ablage_datei, ablage_stand, deleted_at "
            "from public.besprechungen where org_id = $1 and ablage_datei is not null",
            org_id,
        )
    }

    bilanz: dict[str, Any] = {"dateien": len(dateien), "neu": 0, "geaendert": 0, "entfernt": 0, "unlesbar": 0}
    vorschlagen: list[UUID] = []

    # Älteste zuerst: Liegen nach einer geänderten Aufnahmezeit zwei Dateien
    # derselben Besprechung da, gewinnt die jüngere.
    for name, (pfad, stand) in sorted(dateien.items(), key=lambda e: e[1][1]):
        vorher = bekannt.get(name)
        if vorher is not None and vorher["ablage_stand"] == stand and vorher["deleted_at"] is None:
            continue
        try:
            datei = lesen(pfad.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError) as exc:
            log.warning("Insilo-Ablage: %s nicht lesbar: %s", name, exc)
            datei = None
        if datei is None:
            bilanz["unlesbar"] += 1
            continue

        ergebnis = await besprechungen.speichern(
            conn,
            org_id,
            None,
            datei.insilo_id,
            titel=datei.titel,
            recorded_at=datei.recorded_at,
            dauer_sek=datei.dauer_sek,
            vorlage=datei.vorlage,
            schlagworte=datei.schlagworte,
            markdown=datei.markdown,
            zusammenfassung=datei.zusammenfassung,
        )
        besprechung_id = UUID(ergebnis["besprechung_id"])
        await conn.execute(
            "update public.besprechungen set ablage_datei = $1, ablage_stand = $2 where id = $3",
            name,
            stand,
            besprechung_id,
        )
        bilanz["neu" if ergebnis["neu"] else "geaendert"] += 1
        if not ergebnis["zugeordnet"]:
            vorschlagen.append(besprechung_id)

    # Was nicht mehr im Ordner liegt, hat Insilo gelöscht. Ein **leerer**
    # Ordner löscht nichts: Das sieht genauso aus wie ein Ordner, der nach
    # einer Neuinstallation noch nicht gefüllt ist, und ein Archiv, das
    # dabei still verschwindet, ist der schlechtere Fehler.
    if dateien:
        weg = await conn.fetch(
            "select external_id from public.besprechungen "
            "where org_id = $1 and ablage_datei is not null and deleted_at is null "
            "and not (ablage_datei = any($2::text[]))",
            org_id,
            list(dateien),
        )
        for zeile in weg:
            if await besprechungen.entfernen(conn, zeile["external_id"]):
                bilanz["entfernt"] += 1

    bilanz["vorschlagen"] = vorschlagen
    return bilanz


def merken(org_id: UUID, bilanz: dict[str, Any] | None, fehler: str | None = None) -> None:
    STAND[str(org_id)] = {
        "zuletzt": datetime.now(UTC),
        "fehler": fehler,
        "bilanz": {k: v for k, v in (bilanz or {}).items() if k != "vorschlagen"},
    }


async def lesen_und_vorschlagen(nutzer_id: UUID, org_id: UUID) -> dict[str, Any]:
    """Ein ganzer Lauf für eine Organisation: lesen, dann vorschlagen.

    Der Vorschlag über Namen läuft gleich mit; wo er keine Firma findet,
    fragt das Modell im Hintergrund — wie beim Webhook.
    """
    from app.db import acquire_as

    try:
        async with acquire_as(nutzer_id) as conn:
            bilanz = await einlesen(conn, org_id)
            modell = []
            for besprechung_id in bilanz["vorschlagen"]:
                vorschlag = await besprechungen.vorschlagen(conn, besprechung_id)
                if besprechungen.braucht_modell(vorschlag):
                    modell.append(besprechung_id)
    except AblageFehlt as exc:
        merken(org_id, None, str(exc))
        raise
    for besprechung_id in modell:
        besprechungen.modell_im_hintergrund(nutzer_id, org_id, besprechung_id)
    merken(org_id, bilanz)
    return bilanz
