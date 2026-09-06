"""Erkenntnisse — aus Gesprächsnotizen lernen, was am Produkt zu tun ist.

Was Kunden sagen, steht im Verlauf: „das Diarisieren verwechselt Sprecher“,
„gern, wenn es die Zusammenfassung auch auf Englisch gäbe“, „zu teuer für
drei Leute“. Einzeln sind das Notizen. Zusammen sind es Themen — und ein
Thema, das fünfmal vorkommt, ist eine Aufgabe fürs Produkt.

Zwei Schritte, beide vom Modell, beide nachprüfbar:

1. **Aussagen ziehen.** Jede noch nicht gelesene Notiz wird in einzelne
   Aussagen zerlegt: Art (Lob, Kritik, Wunsch, Einwand, Frage), Produkt,
   ein Satz, und das Zitat aus der Notiz. Gelesen wird jede Notiz genau
   einmal (`auswertungen`); was sie hergab, bleibt (`aussagen`).
2. **Themen bilden.** Alle Aussagen des Zeitraums gehen gebündelt ans
   Modell; es nennt Themen, ordnet die Aussagen zu und sagt je Thema, was
   das fürs Produkt heißt. Der Lauf wird gespeichert, samt Zuordnung —
   jedes Thema zeigt auf die Firmen und Notizen dahinter.

Das Modell erfindet nichts: Eine Aussage ohne Zitat aus der Notiz fällt
weg, ein Thema ohne zugeordnete Aussagen auch.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any
from uuid import UUID

import asyncpg
import orjson

from app.llm import LLMConfig, chat, json_aus_antwort, load_llm_config

if TYPE_CHECKING:
    from app.auth import CurrentUser

log = logging.getLogger(__name__)

ARTEN = ("lob", "kritik", "wunsch", "einwand", "frage")
NOTIZEN_JE_ANFRAGE = 6
AUSSAGEN_HOECHSTENS = 300

SYSTEM = (
    "Du liest Gesprächsnotizen eines Vertriebsteams und ziehst daraus heraus, was "
    "Kunden über die Produkte sagen. Du erfindest nichts und deutest nichts hinein: "
    "Jede Aussage trägt ein wörtliches Zitat aus der Notiz. Antworte ausschließlich "
    "als JSON-Objekt."
)

QUELLEN_SQL = """
select a.id, a.subject, a.body, a.occurred_at, a.company_id, f.name as firma
  from public.activities a
  left join public.companies f on f.id = a.company_id
 where a.org_id = $1
   and a.kind in ('note', 'call', 'email', 'meeting')
   and a.body is not null and length(a.body) >= 40
   and a.occurred_at >= now() - ($2::int || ' days')::interval
"""


async def offene_notizen(conn: asyncpg.Connection, org_id: UUID, tage: int) -> list[dict[str, Any]]:
    zeilen = await conn.fetch(
        QUELLEN_SQL + " and not exists (select 1 from public.auswertungen w where w.activity_id = a.id)"
        " order by a.occurred_at",
        org_id, tage,
    )
    return [dict(z) for z in zeilen]


def _im_text(zitat: str, text: str) -> bool:
    """Steht das Zitat (bis auf Leerraum und Groß-/Kleinschreibung) in der Notiz?"""
    z = " ".join(zitat.split()).casefold()
    t = " ".join(text.split()).casefold()
    return bool(z) and len(z) >= 8 and z in t


async def aussagen_ziehen(cfg: LLMConfig, notizen: list[dict[str, Any]]) -> dict[UUID, list[dict[str, Any]]]:
    """Schritt 1 für einen Stapel Notizen. Gibt je Notiz die geprüften Aussagen zurück."""
    block = "\n\n".join(
        f"[{i}] Firma: {n.get('firma') or '—'} · {n['occurred_at']:%d.%m.%Y}\n"
        + (f"{n['subject'].strip()}\n" if (n.get("subject") or "").strip() else "")
        + n["body"].strip()
        for i, n in enumerate(notizen, start=1)
    )
    frage = (
        "Welche Aussagen über unsere Produkte stehen in diesen Notizen? Je Aussage:\n"
        '  "notiz": Nummer der Notiz, "art": eines von lob, kritik, wunsch, einwand, frage,\n'
        '  "produkt": Name des Produkts, wenn genannt, sonst null,\n'
        '  "text": ein neutraler Satz, was der Kunde sagt,\n'
        '  "zitat": die Stelle aus der Notiz, wörtlich.\n'
        "Nur, was der Kunde über das Produkt, den Preis, die Bedienung oder den Nutzen sagt — "
        "keine Termine, keine Aufgaben, keine internen Bemerkungen. Sagt eine Notiz nichts "
        "dergleichen, liefert sie keine Aussage.\n\n"
        'Antworte als {"aussagen": [{"notiz": 1, "art": "...", "produkt": ..., "text": "...", "zitat": "..."}]}.\n\n'
        f"{block}"
    )
    antwort = await chat(cfg, SYSTEM, frage, temperature=0.0, max_tokens=6000)
    roh = json_aus_antwort(antwort) if antwort.strip() else {}
    ergebnis: dict[UUID, list[dict[str, Any]]] = {n["id"]: [] for n in notizen}
    for eintrag in (roh.get("aussagen") or []) if isinstance(roh, dict) else []:
        if not isinstance(eintrag, dict):
            continue
        try:
            notiz = notizen[int(eintrag.get("notiz")) - 1]
        except (TypeError, ValueError, IndexError):
            continue
        art = str(eintrag.get("art") or "").strip().lower()
        text = str(eintrag.get("text") or "").strip()
        zitat = str(eintrag.get("zitat") or "").strip()
        if art not in ARTEN or not text or not _im_text(zitat, notiz["body"]):
            continue
        produkt = str(eintrag.get("produkt") or "").strip()[:80] or None
        if produkt and produkt.lower() in ("null", "none", "unbekannt", "-", "allgemein"):
            produkt = None
        ergebnis[notiz["id"]].append({"art": art, "produkt": produkt, "text": text[:400], "zitat": zitat[:400]})
    return ergebnis


async def aussagen_ablegen(conn: asyncpg.Connection, org_id: UUID, notiz: dict[str, Any], aussagen: list[dict[str, Any]], modell: str) -> None:
    async with conn.transaction():
        for a in aussagen:
            await conn.execute(
                "insert into public.aussagen (org_id, activity_id, company_id, art, produkt, text, zitat) "
                "values ($1, $2, $3, $4, $5, $6, $7)",
                org_id, notiz["id"], notiz.get("company_id"), a["art"], a["produkt"], a["text"], a["zitat"],
            )
        await conn.execute(
            "insert into public.auswertungen (activity_id, org_id, modell, anzahl) values ($1, $2, $3, $4) "
            "on conflict (activity_id) do update set ausgewertet_am = now(), modell = excluded.modell, anzahl = excluded.anzahl",
            notiz["id"], org_id, modell, len(aussagen),
        )


async def aussagen_laden(conn: asyncpg.Connection, org_id: UUID, tage: int) -> list[dict[str, Any]]:
    zeilen = await conn.fetch(
        """
        select s.id, s.activity_id, s.company_id, f.name as firma, s.art, s.produkt, s.text, s.zitat,
               a.occurred_at, a.deal_id, a.contact_id
          from public.aussagen s
          join public.activities a on a.id = s.activity_id
          left join public.companies f on f.id = s.company_id
         where s.org_id = $1 and a.occurred_at >= now() - ($2::int || ' days')::interval
         order by a.occurred_at desc
         limit $3
        """,
        org_id, tage, AUSSAGEN_HOECHSTENS,
    )
    return [dict(z) for z in zeilen]


async def themen_bilden(cfg: LLMConfig, aussagen: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Schritt 2: Aus den Aussagen werden Themen — mit Zuordnung und Folgerung."""
    if not aussagen:
        return []
    block = "\n".join(
        f"[{i}] ({a['art']}{', ' + a['produkt'] if a.get('produkt') else ''}; {a.get('firma') or '—'}) {a['text']}"
        for i, a in enumerate(aussagen, start=1)
    )
    frage = (
        "Bündle diese Kundenaussagen zu Themen. Ein Thema fasst zusammen, was mehrere Kunden "
        "in der Sache meinen — auch wenn sie es verschieden sagen. Je Thema:\n"
        '  "titel": drei bis acht Wörter, "produkt": das betroffene Produkt oder null,\n'
        '  "art": die überwiegende Art (lob, kritik, wunsch, einwand, frage),\n'
        '  "aussagen": die Nummern der Aussagen, die dazugehören,\n'
        '  "bedeutung": ein bis zwei Sätze, was das fürs Produkt heißt,\n'
        '  "vorschlag": eine konkrete Verbesserung, ein Satz — oder null, wenn es nichts zu tun gibt.\n'
        "Die wichtigsten Themen zuerst (viele Aussagen, viele Firmen). Jede Aussage höchstens "
        "einem Thema. Kein Thema ohne Aussage.\n\n"
        'Antworte als {"themen": [{"titel": "...", "produkt": ..., "art": "...", "aussagen": [1, 4], '
        '"bedeutung": "...", "vorschlag": ...}]}.\n\n'
        f"{block}"
    )
    antwort = await chat(cfg, SYSTEM, frage, temperature=0.0, max_tokens=6000)
    roh = json_aus_antwort(antwort) if antwort.strip() else {}
    themen: list[dict[str, Any]] = []
    vergeben: set[int] = set()
    for eintrag in (roh.get("themen") or []) if isinstance(roh, dict) else []:
        if not isinstance(eintrag, dict):
            continue
        nummern: list[int] = []
        for n in eintrag.get("aussagen") or []:
            try:
                k = int(n)
            except (TypeError, ValueError):
                continue
            if 1 <= k <= len(aussagen) and k not in vergeben:
                nummern.append(k)
                vergeben.add(k)
        titel = str(eintrag.get("titel") or "").strip()
        if not nummern or not titel:
            continue
        art = str(eintrag.get("art") or "").strip().lower()
        if art not in ARTEN:
            arten = [aussagen[k - 1]["art"] for k in nummern]
            art = max(set(arten), key=arten.count)
        produkt = str(eintrag.get("produkt") or "").strip()[:80] or None
        vorschlag = str(eintrag.get("vorschlag") or "").strip() or None
        themen.append({
            "titel": titel[:120],
            "produkt": None if produkt and produkt.lower() in ("null", "none") else produkt,
            "art": art,
            "aussagen": [str(aussagen[k - 1]["id"]) for k in nummern],
            "firmen": sorted({aussagen[k - 1]["firma"] for k in nummern if aussagen[k - 1].get("firma")}),
            "bedeutung": str(eintrag.get("bedeutung") or "").strip()[:600],
            "vorschlag": vorschlag[:400] if vorschlag else None,
        })
    return themen


async def lauf(conn: asyncpg.Connection, user: CurrentUser, lauf_id: UUID, tage: int) -> None:
    """Der ganze Lauf: offene Notizen lesen, dann Themen bilden. Schreibt
    den Fortschritt in die Zeile, damit die Seite ihn zeigen kann."""
    cfg = await load_llm_config(conn, user.org_id)
    offen = await offene_notizen(conn, user.org_id, tage)
    gelesen = 0

    async def stand(**mehr: Any) -> None:
        await conn.execute(
            "update public.themenlaeufe set fortschritt = $1::jsonb, updated_at = now() where id = $2",
            orjson.dumps({"gelesen": gelesen, "gesamt": len(offen), **mehr}).decode(), lauf_id,
        )

    await stand(schritt="notizen")
    for i in range(0, len(offen), NOTIZEN_JE_ANFRAGE):
        stapel = offen[i : i + NOTIZEN_JE_ANFRAGE]
        ergebnis = await aussagen_ziehen(cfg, stapel)
        for notiz in stapel:
            await aussagen_ablegen(conn, user.org_id, notiz, ergebnis.get(notiz["id"], []), cfg.model)
        gelesen += len(stapel)
        await stand(schritt="notizen")

    await stand(schritt="themen")
    aussagen = await aussagen_laden(conn, user.org_id, tage)
    themen = await themen_bilden(cfg, aussagen)
    await conn.execute(
        """
        update public.themenlaeufe
           set status = 'fertig', themen = $1::jsonb, aussagen_anzahl = $2, modell = $3,
               fortschritt = $4::jsonb, updated_at = now()
         where id = $5
        """,
        orjson.dumps(themen).decode(), len(aussagen), cfg.model,
        orjson.dumps({"gelesen": gelesen, "gesamt": len(offen), "schritt": "fertig"}).decode(), lauf_id,
    )


HINTERGRUND: set[asyncio.Task[Any]] = set()


def im_hintergrund(user: CurrentUser, lauf_id: UUID, tage: int) -> None:
    """Startet den Lauf, ohne die Antwort aufzuhalten — vierzig Notizen und
    ein Denkmodell sind Minuten, keine Sekunden."""
    from app.db import acquire_as

    async def _arbeit() -> None:
        try:
            async with acquire_as(user.user_id) as conn:
                await lauf(conn, user, lauf_id, tage)
        except Exception as exc:  # noqa: BLE001 — der Fehler gehört in die Zeile, nicht in den Absturz
            log.exception("Erkenntnisse-Lauf fehlgeschlagen (%s)", lauf_id)
            try:
                async with acquire_as(user.user_id) as conn:
                    await conn.execute(
                        "update public.themenlaeufe set status = 'fehler', fehler = $1, updated_at = now() where id = $2",
                        f"{type(exc).__name__}: {exc}"[:500], lauf_id,
                    )
            except Exception:  # noqa: BLE001
                log.exception("Fehler am Lauf konnte nicht abgelegt werden (%s)", lauf_id)

    aufgabe = asyncio.create_task(_arbeit())
    HINTERGRUND.add(aufgabe)
    aufgabe.add_done_callback(HINTERGRUND.discard)


async def hintergrund_abwarten() -> None:
    if HINTERGRUND:
        await asyncio.gather(*list(HINTERGRUND), return_exceptions=True)
