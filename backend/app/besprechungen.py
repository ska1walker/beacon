"""Besprechungen aus Insilo — empfangen, zuordnen vorschlagen, zuordnen.

Ein eigener Bereich und nicht der Eingang: Der Eingang ist eine
Warteschlange, die leer werden soll. Besprechungen sind ein Archiv, das
man durchsucht und nach Datum liest. Zuordnung ist hier eine Eigenschaft
der Besprechung, kein Zustand einer Warteschlange.

Zwei Regeln, beide mit Kai und Marc am 15.9.2026 festgelegt:

* **Protokoll ja, Wortlaut nein.** Beacon behält Insilos Markdown ohne den
  Abschnitt „## Volltranskript" und ohne die rohe Nutzlast. Der Wortlaut
  bleibt in Insilo, die Oberfläche verlinkt dorthin. Ein Vertrieb liest das
  Protokoll; wer den genauen Satz braucht, geht an die Quelle.
* **Nie automatisch zugeordnet.** Beacon schlägt vor, ein Mensch bestätigt.
  Insilo kennt von den Beteiligten nur Namen — keine E-Mail, keine Kennung
  —, und zwei Kontakte heißen Meyer. Ein Protokoll am falschen Kunden ist
  schlimmer als eines, das auf einen Klick wartet.
"""

from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime
from typing import Any
from uuid import UUID

import asyncpg
import httpx
import orjson

from app.einfuhr import firmenschluessel
from app.llm import LLMNichtEingerichtet, chat, json_aus_antwort, load_llm_config
from app.namen import namensteile

log = logging.getLogger(__name__)

# Wo Insilos Protokoll endet und der Wortlaut beginnt
# (insilo/backend/app/exports/markdown.py).
WORTLAUT = "\n## Volltranskript"

# Sprecher, die Insilo nicht erkannt hat, heißen SPEAKER_00 — kein Name.
ROHER_SPRECHER = re.compile(r"^speaker_\d+$", re.IGNORECASE)

# Vorlagenfelder, in denen Insilos Modell Menschen einträgt. Die
# eingebauten Vorlagen nennen sie `anwesende`, `kunde`, `mandantenname`;
# eigene Vorlagen dürfen anders heißen, deshalb die weitere Liste.
BETEILIGTEN_FELDER = (
    "anwesende", "teilnehmer", "teilnehmende", "kunde", "mandant",
    "mandantenname", "gespraechspartner", "gesprächspartner", "ansprechpartner",
)

# Höchstens so viele Kandidaten gehen an das Modell. Eine ganze Kundenliste
# wäre teuer, und das Modell wählte aus Namen, die im Gespräch nie fielen.
MODELL_KANDIDATEN = 40

HINTERGRUND: set[asyncio.Task[Any]] = set()


# ── Aus Insilos Nutzlast ────────────────────────────────────────────────


def _zeitpunkt(wert: object) -> datetime | None:
    if not isinstance(wert, str) or not wert.strip():
        return None
    try:
        return datetime.fromisoformat(wert.replace("Z", "+00:00"))
    except ValueError:
        return None


def _frontmatter(markdown: str) -> tuple[dict[str, list[str] | str], str]:
    """Insilos Frontmatter und der Rest.

    Insilo schreibt ein schlichtes YAML ohne Verschachtelung: `schluessel:
    wert` oder `schluessel:` gefolgt von `  - eintrag`. Mehr wird hier nicht
    gelesen — ein YAML-Parser für diese vier Formen wäre eine Abhängigkeit
    ohne Nutzen.
    """
    if not markdown.startswith("---\n"):
        return {}, markdown
    ende = markdown.find("\n---", 4)
    if ende == -1:
        return {}, markdown
    felder: dict[str, list[str] | str] = {}
    aktuell: str | None = None
    for zeile in markdown[4:ende].split("\n"):
        if zeile.startswith("  - ") and aktuell:
            liste = felder.setdefault(aktuell, [])
            if isinstance(liste, list):
                liste.append(_yaml_text(zeile[4:]))
        elif ":" in zeile:
            schluessel, _, wert = zeile.partition(":")
            aktuell = schluessel.strip()
            wert = wert.strip()
            felder[aktuell] = [] if wert in ("", "[]") else _yaml_text(wert)
    return felder, markdown[ende + 4 :].lstrip("\n")


def _yaml_text(wert: str) -> str:
    wert = wert.strip()
    if len(wert) >= 2 and wert[0] == wert[-1] == '"':
        return wert[1:-1].replace('\\"', '"').replace("\\\\", "\\")
    return wert


def protokoll_aus(markdown: str | None) -> str:
    """Das Protokoll ohne Frontmatter und ohne Wortlaut."""
    if not markdown:
        return ""
    _, rest = _frontmatter(markdown)
    return rest.split(WORTLAUT, 1)[0].rstrip()


def sprecher_aus(markdown: str | None) -> list[str]:
    """Die erkannten Sprecher — ohne die, die nur eine Nummer tragen."""
    if not markdown:
        return []
    felder, _ = _frontmatter(markdown)
    namen = felder.get("speakers")
    if not isinstance(namen, list):
        return []
    return [n for n in namen if n and not ROHER_SPRECHER.match(n.strip())]


def _ohne_zusatz(name: str) -> str:
    """„Frau Schäfer (HR-Leitung)" → „Frau Schäfer"."""
    return re.sub(r"\s*\([^)]*\)", "", name).strip()


def beteiligte_aus(sprecher: list[str], zusammenfassung: dict[str, Any]) -> list[str]:
    """Alle Menschen, die Insilo zu diesem Gespräch nennt, ohne Doppel."""
    gesehen: dict[str, str] = {}
    kandidaten: list[str] = list(sprecher)
    for feld in BETEILIGTEN_FELDER:
        wert = zusammenfassung.get(feld)
        if isinstance(wert, str):
            kandidaten.append(wert)
        elif isinstance(wert, list):
            kandidaten += [w for w in wert if isinstance(w, str)]
    for roh in kandidaten:
        name = _ohne_zusatz(roh)
        schluessel = " ".join(sorted(namensteile(name)))
        if schluessel and schluessel not in gesehen:
            gesehen[schluessel] = name
    return list(gesehen.values())


# ── Empfangen ───────────────────────────────────────────────────────────


async def empfangen(
    conn: asyncpg.Connection,
    org_id: UUID,
    source_id: UUID,
    ereignis: str,
    daten: dict[str, Any],
) -> dict[str, Any]:
    """Verarbeitet ein Insilo-Ereignis. Die Signatur ist schon geprüft.

    Nur `meeting.ready` legt etwas an. `created` und `failed` sind Zustände
    in Insilo, kein Gespräch — sie wurden bis 0.9.9 im Eingang abgelegt und
    blieben dort für immer „offen".
    """
    besprechung = daten.get("meeting") or {}
    extern = str(besprechung.get("id") or "").strip()

    if ereignis == "meeting.ready":
        if not extern:
            return {"status": "quittiert", "hinweis": "Ohne Besprechungskennung nichts angelegt."}
        return await _fertig(conn, org_id, source_id, extern, besprechung, daten)

    if ereignis == "meeting.updated" and extern:
        zeile = await conn.fetchrow(
            "update public.besprechungen set titel = coalesce($1, titel), "
            "schlagworte = coalesce($2, schlagworte), updated_at = now() "
            "where external_id = $3 and deleted_at is null returning id, activity_id",
            besprechung.get("title"),
            _schlagworte(besprechung),
            extern,
        )
        if zeile and zeile["activity_id"] and besprechung.get("title"):
            await conn.execute(
                "update public.activities set subject = $1, updated_at = now() where id = $2",
                besprechung["title"],
                zeile["activity_id"],
            )
        return {"status": "angenommen", "besprechung_id": str(zeile["id"]) if zeile else None}

    if ereignis == "meeting.deleted" and extern:
        zeile = await conn.fetchrow(
            "update public.besprechungen set deleted_at = now(), updated_at = now() "
            "where external_id = $1 and deleted_at is null returning id, activity_id",
            extern,
        )
        if zeile and zeile["activity_id"]:
            await conn.execute(
                "update public.activities set deleted_at = now() where id = $1",
                zeile["activity_id"],
            )
        return {"status": "angenommen", "besprechung_id": str(zeile["id"]) if zeile else None}

    return {"status": "quittiert"}


def _schlagworte(besprechung: dict[str, Any]) -> list[str] | None:
    roh = besprechung.get("tags")
    if not isinstance(roh, list):
        return None
    return [str(t.get("name") if isinstance(t, dict) else t) for t in roh if t]


async def _fertig(
    conn: asyncpg.Connection,
    org_id: UUID,
    source_id: UUID,
    extern: str,
    besprechung: dict[str, Any],
    daten: dict[str, Any],
) -> dict[str, Any]:
    markdown = daten.get("markdown") or ""
    zusammenfassung = (daten.get("summary") or {}).get("content") or {}
    if not isinstance(zusammenfassung, dict):
        zusammenfassung = {}
    sprecher = sprecher_aus(markdown)

    zeile = await conn.fetchrow(
        """
        insert into public.besprechungen
          (org_id, source_id, external_id, titel, recorded_at, dauer_sek, vorlage,
           schlagworte, sprecher, beteiligte, zusammenfassung, protokoll)
        values ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11::jsonb,$12)
        on conflict (org_id, external_id) do update set
          source_id = excluded.source_id,
          titel = excluded.titel,
          recorded_at = coalesce(excluded.recorded_at, public.besprechungen.recorded_at),
          dauer_sek = coalesce(excluded.dauer_sek, public.besprechungen.dauer_sek),
          vorlage = excluded.vorlage,
          schlagworte = excluded.schlagworte,
          sprecher = excluded.sprecher,
          beteiligte = excluded.beteiligte,
          zusammenfassung = excluded.zusammenfassung,
          protokoll = excluded.protokoll,
          deleted_at = null,
          updated_at = now()
        returning id, status, activity_id, titel, protokoll, recorded_at, (xmax = 0) as neu
        """,
        org_id,
        source_id,
        extern,
        besprechung.get("title"),
        _zeitpunkt(besprechung.get("recorded_at")),
        besprechung.get("duration_sec") if isinstance(besprechung.get("duration_sec"), int) else None,
        besprechung.get("template_name"),
        _schlagworte(besprechung) or [],
        sprecher,
        beteiligte_aus(sprecher, zusammenfassung),
        orjson.dumps(zusammenfassung).decode(),
        protokoll_aus(markdown),
    )

    # Eine neu erzeugte Zusammenfassung kommt als zweites `meeting.ready`.
    # Hängt die Besprechung schon am Kunden, bekommt dessen Zeitleiste den
    # neuen Text — sonst stünde dort das alte Protokoll.
    if zeile["activity_id"]:
        await conn.execute(
            "update public.activities set subject = $1, body = $2, "
            "occurred_at = coalesce($3, occurred_at), updated_at = now() where id = $4",
            zeile["titel"] or "Besprechung",
            zeile["protokoll"],
            zeile["recorded_at"],
            zeile["activity_id"],
        )

    return {
        "status": "angenommen",
        "besprechung_id": str(zeile["id"]),
        "neu": zeile["neu"],
        "zugeordnet": zeile["status"] == "zugeordnet",
    }


# ── Vorschlagen ─────────────────────────────────────────────────────────


def _voller_name(k: asyncpg.Record | dict[str, Any]) -> str:
    return " ".join(p for p in (k["first_name"], k["last_name"]) if p).strip()


def _passung(genannt: str, kontakt: asyncpg.Record | dict[str, Any]) -> int:
    """Wie gut ein genannter Name auf einen Kontakt passt: 0, 1 oder 2.

    Der **Nachname** muss stimmen. Ein Abgleich auf irgendeinen Namensteil
    hätte „Katrin" auf jede Katrin im Bestand gelegt. Stimmt zusätzlich der
    Vorname, ist es ein besserer Treffer — so gewinnt „Anna Meyer" gegen
    Klaus Meyer, und nur ein nacktes „Herr Meyer" bleibt mehrdeutig.
    """
    teile = namensteile(genannt)
    nachname = namensteile(kontakt["last_name"] or kontakt["first_name"] or "")
    if not teile or not nachname or not nachname <= teile:
        return 0
    vorname = namensteile(kontakt["first_name"] or "") if kontakt["last_name"] else set()
    return 2 if vorname and vorname <= teile else 1


async def vorschlag_ueber_namen(conn: asyncpg.Connection, besprechung_id: UUID) -> dict[str, Any]:
    """Stufe 1: Namen und Firmen, die im Gespräch fallen, gegen den Bestand.

    Kostet nichts, ist erklärbar und läuft sofort beim Empfang.
    """
    b = await conn.fetchrow(
        "select titel, schlagworte, beteiligte, zusammenfassung from public.besprechungen where id = $1",
        besprechung_id,
    )
    kontakte = await conn.fetch(
        "select c.id, c.first_name, c.last_name, c.company_id, f.name as company_name "
        "from public.contacts c left join public.companies f on f.id = c.company_id "
        "where c.deleted_at is null"
    )
    firmen = await conn.fetch("select id, name from public.companies where deleted_at is null")

    zusammenfassung = orjson.loads(b["zusammenfassung"]) if isinstance(b["zusammenfassung"], str) else (b["zusammenfassung"] or {})
    firmentext = " ".join(
        [b["titel"] or "", *(b["schlagworte"] or [])]
        + [str(zusammenfassung.get(f)) for f in ("kunde", "mandant", "mandantenname", "firma", "unternehmen") if zusammenfassung.get(f)]
    ).lower()

    # Firmen, deren Name im Titel, in den Schlagworten oder im Kundenfeld
    # steht. Zu kurze Schlüssel treffen zufällig — „ag" steckt überall.
    direkt = {
        f["id"]: f["name"]
        for f in firmen
        if len(schluessel := firmenschluessel(f["name"])) >= 4
        and re.search(r"(?<![\w])" + re.escape(schluessel) + r"(?![\w])", firmentext)
    }

    eindeutig: dict[UUID, asyncpg.Record] = {}
    mehrdeutig: list[tuple[str, list[asyncpg.Record]]] = []
    for genannt in b["beteiligte"] or []:
        bewertet = [(k, _passung(genannt, k)) for k in kontakte]
        beste = max((p for _, p in bewertet), default=0)
        if beste == 0:
            continue
        treffer = [k for k, p in bewertet if p == beste]
        if len(treffer) == 1:
            eindeutig[treffer[0]["id"]] = treffer[0]
        else:
            mehrdeutig.append((genannt, treffer))

    firma_ids = set(direkt) | {k["company_id"] for k in eindeutig.values() if k["company_id"]}

    # Ein mehrdeutiger Name lässt sich manchmal auflösen: Stehen die übrigen
    # Hinweise auf genau einer Firma, zählt nur der Meyer dieser Firma.
    offen_mehrdeutig: list[tuple[str, list[asyncpg.Record]]] = []
    for genannt, treffer in mehrdeutig:
        passend = [k for k in treffer if len(firma_ids) == 1 and k["company_id"] in firma_ids]
        if len(passend) == 1:
            eindeutig[passend[0]["id"]] = passend[0]
        else:
            offen_mehrdeutig.append((genannt, treffer))

    kandidaten = [
        {"contact_id": str(k["id"]), "name": _voller_name(k), "company_id": str(k["company_id"]) if k["company_id"] else None,
         "company_name": k["company_name"], "genannt": genannt}
        for genannt, treffer in offen_mehrdeutig
        for k in treffer
    ]

    if offen_mehrdeutig:
        genannt, treffer = offen_mehrdeutig[0]
        grund = f"{len(treffer)} Kontakte passen zu „{genannt}“ — bitte wählen"
        return {"quelle": "namen", "company_id": None, "contact_ids": [], "deal_id": None,
                "grund": grund, "mehrdeutig": True, "kandidaten": kandidaten}

    if len(firma_ids) != 1:
        if not firma_ids:
            grund = "Kein genannter Name passt zu einem Kontakt oder einer Firma"
        else:
            namen = sorted({direkt.get(i) or next((k["company_name"] for k in eindeutig.values() if k["company_id"] == i), "?") for i in firma_ids})
            grund = f"Mehrere Firmen kommen in Frage: {', '.join(namen)}"
        return {"quelle": "namen", "company_id": None, "contact_ids": [], "deal_id": None,
                "grund": grund, "mehrdeutig": bool(firma_ids), "kandidaten": kandidaten}

    firma_id = next(iter(firma_ids))
    kontakt_ids = [str(k["id"]) for k in eindeutig.values() if k["company_id"] in (firma_id, None)]
    offene = await conn.fetch(
        "select d.id from public.deals d join public.pipeline_stages s on s.id = d.stage_id "
        "where d.company_id = $1 and d.deleted_at is null and s.kind = 'open'",
        firma_id,
    )
    deal_id = str(offene[0]["id"]) if len(offene) == 1 else None

    firmenname = direkt.get(firma_id) or next(k["company_name"] for k in eindeutig.values() if k["company_id"] == firma_id)
    teile = [f"{firmenname} {'im Titel' if firma_id in direkt else 'über die Beteiligten'}"]
    if kontakt_ids:
        teile.append(f"{len(kontakt_ids)} {'Kontakt' if len(kontakt_ids) == 1 else 'Kontakte'} erkannt")
    if deal_id:
        teile.append("ein offener Lead")
    return {"quelle": "namen", "company_id": str(firma_id), "contact_ids": kontakt_ids, "deal_id": deal_id,
            "grund": ", ".join(teile), "mehrdeutig": False, "kandidaten": []}


async def vorschlagen(conn: asyncpg.Connection, besprechung_id: UUID) -> dict[str, Any]:
    """Legt den Vorschlag über Namen ab. Eine zugeordnete Besprechung bleibt, wie sie ist."""
    status = await conn.fetchval("select status from public.besprechungen where id = $1", besprechung_id)
    if status != "offen":
        return {}
    vorschlag = await vorschlag_ueber_namen(conn, besprechung_id)
    await conn.execute(
        "update public.besprechungen set vorschlag = $1::jsonb, updated_at = now() where id = $2",
        orjson.dumps(vorschlag).decode(),
        besprechung_id,
    )
    return vorschlag


def braucht_modell(vorschlag: dict[str, Any]) -> bool:
    """Das Modell fragt Beacon nur, wenn die Namen gar nichts ergaben.

    Bei einer Mehrdeutigkeit hilft es nicht: Es sähe dieselben zwei Meyers
    und müsste raten.
    """
    return bool(vorschlag) and not vorschlag.get("company_id") and not vorschlag.get("mehrdeutig")


async def vorschlag_ueber_modell(conn: asyncpg.Connection, org_id: UUID, besprechung_id: UUID) -> dict[str, Any] | None:
    """Stufe 2: das Modell, mit der Zusammenfassung und einer kurzen Kandidatenliste.

    Das Modell bekommt **nicht** den ganzen Bestand und nicht den Wortlaut
    (den hat Beacon gar nicht), sondern höchstens `MODELL_KANDIDATEN`
    Firmen, deren Namen mit dem Gespräch ein Wort teilen, und deren
    Kontakte. Jede Kennung in der Antwort muss aus dieser Liste stammen —
    sonst wäre ein erfundener Datensatz nur eine Kennung entfernt.
    """
    cfg = await load_llm_config(conn, org_id)
    if not cfg.eingerichtet:
        return None

    b = await conn.fetchrow(
        "select titel, beteiligte, zusammenfassung, protokoll, status from public.besprechungen where id = $1",
        besprechung_id,
    )
    if b is None or b["status"] != "offen":
        return None

    gespraech = " ".join([b["titel"] or "", " ".join(b["beteiligte"] or []), (b["protokoll"] or "")[:4000]])
    worte = set(re.findall(r"\w{4,}", gespraech.lower()))
    firmen = [
        f for f in await conn.fetch("select id, name from public.companies where deleted_at is null")
        if worte & set(re.findall(r"\w{4,}", firmenschluessel(f["name"])))
    ][:MODELL_KANDIDATEN]
    if not firmen:
        return None
    kontakte = await conn.fetch(
        "select id, first_name, last_name, company_id from public.contacts "
        "where deleted_at is null and company_id = any($1::uuid[])",
        [f["id"] for f in firmen],
    )

    liste = "\n".join(
        f"- Firma {f['id']}: {f['name']}"
        + "".join(f"\n    - Kontakt {k['id']}: {_voller_name(k)}" for k in kontakte if k["company_id"] == f["id"])
        for f in firmen
    )
    frage = (
        "Zu welchem Kunden gehört dieses Gespräch?\n\n"
        "Antworte ausschließlich als JSON-Objekt:\n"
        '  "company_id": die Kennung einer Firma aus der Liste, oder null,\n'
        '  "contact_ids": Kennungen von Kontakten dieser Firma, die am Gespräch beteiligt waren,\n'
        '  "grund": ein Satz, woran du es erkennst.\n\n'
        "Nur Kennungen aus der Liste. Passt keine Firma sicher, antworte mit null — "
        "ein falscher Kunde ist schlimmer als keiner.\n\n"
        f"Kandidaten:\n{liste}\n\n"
        f"Gespräch:\n{gespraech}"
    )

    from app.routers.ki import SYSTEM

    try:
        antwort = await chat(cfg, SYSTEM, frage, temperature=0.1, max_tokens=400)
        roh = json_aus_antwort(antwort)
    except (LLMNichtEingerichtet, httpx.HTTPError, ValueError) as exc:
        log.info("Kein Modellvorschlag für Besprechung %s: %s", besprechung_id, exc)
        return None

    firma_ids = {str(f["id"]) for f in firmen}
    firma = str(roh.get("company_id") or "")
    if firma not in firma_ids:
        return None
    erlaubte_kontakte = {str(k["id"]) for k in kontakte if str(k["company_id"]) == firma}
    kontakt_ids = [str(k) for k in (roh.get("contact_ids") or []) if str(k) in erlaubte_kontakte]

    offene = await conn.fetch(
        "select d.id from public.deals d join public.pipeline_stages s on s.id = d.stage_id "
        "where d.company_id = $1 and d.deleted_at is null and s.kind = 'open'",
        UUID(firma),
    )
    vorschlag = {
        "quelle": "modell",
        "company_id": firma,
        "contact_ids": kontakt_ids,
        "deal_id": str(offene[0]["id"]) if len(offene) == 1 else None,
        "grund": str(roh.get("grund") or "vom Modell vorgeschlagen")[:240],
        "mehrdeutig": False,
        "kandidaten": [],
        "modell": cfg.model,
    }
    await conn.execute(
        "update public.besprechungen set vorschlag = $1::jsonb, updated_at = now() "
        "where id = $2 and status = 'offen'",
        orjson.dumps(vorschlag).decode(),
        besprechung_id,
    )
    return vorschlag


def modell_im_hintergrund(nutzer_id: UUID, org_id: UUID, besprechung_id: UUID) -> None:
    """Fragt das Modell, ohne Insilo warten zu lassen.

    Insilo gibt einer Auslieferung zehn Sekunden. Ein Modell auf der Box
    braucht oft länger — die Antwort an Insilo darf daran nicht hängen.
    """
    from app.db import acquire_as

    async def _arbeit() -> None:
        try:
            async with acquire_as(nutzer_id) as conn:
                await vorschlag_ueber_modell(conn, org_id, besprechung_id)
        except Exception:  # noqa: BLE001 — ein Hintergrundlauf darf nichts mitreißen
            log.exception("Modellvorschlag für Besprechung %s fehlgeschlagen", besprechung_id)

    aufgabe = asyncio.create_task(_arbeit())
    HINTERGRUND.add(aufgabe)
    aufgabe.add_done_callback(HINTERGRUND.discard)


# ── Zuordnen ────────────────────────────────────────────────────────────


class NichtGefunden(LookupError):  # noqa: N818
    """Besprechung, Firma, Kontakt oder Lead gibt es in dieser Organisation nicht."""


async def zuordnen(
    conn: asyncpg.Connection,
    nutzer_id: UUID,
    org_id: UUID,
    besprechung_id: UUID,
    company_id: UUID | None,
    contact_ids: list[UUID],
    deal_id: UUID | None,
) -> UUID:
    """Hängt eine Besprechung an Firma, Kontakte und Lead — als **eine** Aktivität.

    Eine Aktivität, nicht eine je Kontakt: Die Zeitleiste der Firma zeigt
    auch die Aktivitäten ihrer Kontakte, und drei Beteiligte ergäben dort
    dreimal dasselbe Gespräch. Die Aktivität trägt den ersten Kontakt; an
    den übrigen steht sie über `besprechung_kontakte`.
    """
    b = await conn.fetchrow(
        "select id, titel, protokoll, recorded_at, activity_id, external_id "
        "from public.besprechungen where id = $1 and deleted_at is null",
        besprechung_id,
    )
    if b is None:
        raise NichtGefunden("Besprechung nicht gefunden")

    if deal_id:
        deal_firma = await conn.fetchval(
            "select company_id from public.deals where id = $1 and deleted_at is null", deal_id
        )
        if deal_firma is None and not await conn.fetchval(
            "select 1 from public.deals where id = $1 and deleted_at is null", deal_id
        ):
            raise NichtGefunden("Lead nicht gefunden")
        company_id = company_id or deal_firma
    if company_id and not await conn.fetchval(
        "select 1 from public.companies where id = $1 and deleted_at is null", company_id
    ):
        raise NichtGefunden("Firma nicht gefunden")
    gefunden = await conn.fetch(
        "select id from public.contacts where id = any($1::uuid[]) and deleted_at is null",
        contact_ids,
    )
    if len(gefunden) != len(set(contact_ids)):
        raise NichtGefunden("Kontakt nicht gefunden")
    if not (company_id or contact_ids or deal_id):
        raise ValueError("Firma, Kontakt oder Lead angeben.")

    erster = contact_ids[0] if contact_ids else None
    payload = orjson.dumps({"quelle": "insilo", "besprechung_id": str(besprechung_id)}).decode()

    aktivitaet = await conn.fetchval(
        """
        insert into public.activities
          (org_id, kind, subject, body, occurred_at, company_id, contact_id, deal_id,
           payload, external_source, external_id, created_by)
        values ($1, 'meeting', $2, $3, coalesce($4, now()), $5, $6, $7, $8::jsonb, 'insilo', $9, $10)
        on conflict (org_id, external_source, external_id)
          where external_source is not null and external_id is not null
        do update set
          subject = excluded.subject, body = excluded.body, occurred_at = excluded.occurred_at,
          company_id = excluded.company_id, contact_id = excluded.contact_id,
          deal_id = excluded.deal_id, payload = excluded.payload,
          deleted_at = null, updated_at = now()
        returning id
        """,
        org_id,
        b["titel"] or "Besprechung",
        b["protokoll"],
        b["recorded_at"],
        company_id,
        erster,
        deal_id,
        payload,
        b["external_id"],
        nutzer_id,
    )

    await conn.execute("delete from public.besprechung_kontakte where besprechung_id = $1", besprechung_id)
    for kontakt in dict.fromkeys(contact_ids):
        await conn.execute(
            "insert into public.besprechung_kontakte (besprechung_id, contact_id, org_id) values ($1,$2,$3)",
            besprechung_id,
            kontakt,
            org_id,
        )

    await conn.execute(
        "update public.besprechungen set status = 'zugeordnet', company_id = $1, deal_id = $2, "
        "activity_id = $3, updated_at = now() where id = $4",
        company_id,
        deal_id,
        aktivitaet,
        besprechung_id,
    )
    return aktivitaet


async def loesen(conn: asyncpg.Connection, besprechung_id: UUID) -> None:
    """Nimmt eine Zuordnung zurück; die Besprechung wartet wieder."""
    b = await conn.fetchrow(
        "select activity_id from public.besprechungen where id = $1 and deleted_at is null",
        besprechung_id,
    )
    if b is None:
        raise NichtGefunden("Besprechung nicht gefunden")
    if b["activity_id"]:
        await conn.execute(
            "update public.activities set deleted_at = now() where id = $1", b["activity_id"]
        )
    await conn.execute("delete from public.besprechung_kontakte where besprechung_id = $1", besprechung_id)
    await conn.execute(
        "update public.besprechungen set status = 'offen', company_id = null, deal_id = null, "
        "activity_id = null, updated_at = now() where id = $1",
        besprechung_id,
    )
