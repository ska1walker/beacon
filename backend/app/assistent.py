"""Der Assistent — Aufträge in Worten, Handlungen mit Karte.

„Leg für Brinkmann eine Aufgabe an: Angebot nachfassen, Freitag.“ Das Modell
bekommt Beacons Funktionen als Werkzeuge und plant; Beacon führt aus.
Drei Regeln machen den Unterschied zwischen nützlich und gefährlich:

- **Lesen sofort, Schreiben mit Karte.** Suchen und Nachsehen läuft
  direkt. Alles, was anlegt oder ändert, kommt als Vorschlag zurück:
  Beacon baut die Anfrage fertig (Pfad, Körper), zeigt sie als Karte, und
  ein Mensch drückt „Ausführen“. Das Modell schreibt nie selbst.
- **Keine erfundenen Kennungen.** Das Modell nennt „Brinkmann“; ein
  Werkzeug sucht im Bestand. Ein Treffer wird verwendet, bei mehreren
  bekommt das Modell die Kandidaten und fragt zurück.
- **Er handelt als die Person.** Jede Suche läuft mit deren Nutzerkontext,
  jede Karte wird mit deren Rechten ausgeführt — wie ein Klick.

Ein Auftrag hat höchstens fünf Schritte: Ein Denkmodell auf der Box
braucht je Schritt rund zehn Sekunden.
"""

from __future__ import annotations

import json
import re
from datetime import date
from typing import Any

import asyncpg

from app.llm import LLMConfig, chat_werkzeuge
from app.routers.suche import ARTEN

SCHRITTE_HOECHSTENS = 5

SEITEN = {
    "start": "/", "leads": "/deals", "angebote": "/angebote", "prognose": "/prognose", "aufgaben": "/aufgaben",
    "firmen": "/firmen", "kontakte": "/kontakte", "listen": "/listen", "eingang": "/eingang", "tickets": "/tickets",
    "kampagnen": "/kampagnen", "fragen": "/fragen", "erkenntnisse": "/erkenntnisse", "einstellungen": "/einstellungen",
}

SYSTEM = (
    "Du bist der Assistent im CRM Beacon und hilfst einer Vertriebsperson. Du antwortest kurz, "
    "auf Deutsch, in der Sie-Form. Für alles, was im Bestand steht oder verändert werden soll, "
    "nutzt du Werkzeuge — du erfindest keine Firmen, Personen oder Kennungen. Nenne Datensätze "
    "beim Namen, wie das Werkzeug sie liefert. Änderungen legst du als Vorschlag an; sie werden "
    "erst ausgeführt, wenn die Person die Karte bestätigt — sag das nicht jedes Mal, es steht "
    "an der Karte. Findet ein Werkzeug mehrere Treffer, frage nach, welcher gemeint ist. "
    "Heute ist {heute}."
)

WERKZEUGE: list[dict[str, Any]] = [
    {"type": "function", "function": {
        "name": "suchen",
        "description": "Sucht im Bestand über Firmen, Kontakte, Leads, Tickets, Listen und Kampagnen. Liefert Treffer mit Art, Name und Pfad.",
        "parameters": {"type": "object", "properties": {"text": {"type": "string", "description": "Name, E-Mail, Ort oder Betreff"}}, "required": ["text"]},
    }},
    {"type": "function", "function": {
        "name": "aufgaben_offen",
        "description": "Die offenen Aufgaben der Person, überfällige zuerst.",
        "parameters": {"type": "object", "properties": {}},
    }},
    {"type": "function", "function": {
        "name": "seite_oeffnen",
        "description": "Öffnet einen Bereich von Beacon oder einen gefundenen Datensatz.",
        "parameters": {"type": "object", "properties": {
            "bereich": {"type": "string", "enum": sorted(SEITEN), "description": "Ein Bereich — oder leer, wenn ein Pfad gegeben ist"},
            "pfad": {"type": "string", "description": "Pfad eines Treffers aus `suchen`, z. B. /firmen/<id>"},
        }},
    }},
    {"type": "function", "function": {
        "name": "aufgabe_anlegen",
        "description": "Schlägt eine Aufgabe vor. Firma, Kontakt oder Lead beim Namen nennen, das Werkzeug löst sie auf.",
        "parameters": {"type": "object", "properties": {
            "titel": {"type": "string"},
            "faellig": {"type": "string", "description": "Datum als YYYY-MM-DD, aus Angaben wie „Freitag“ berechnet"},
            "notiz": {"type": "string"},
            "firma": {"type": "string"}, "kontakt": {"type": "string"}, "lead": {"type": "string"},
        }, "required": ["titel"]},
    }},
    {"type": "function", "function": {
        "name": "notiz_anlegen",
        "description": "Schlägt eine Notiz im Verlauf einer Firma, eines Kontakts oder Leads vor.",
        "parameters": {"type": "object", "properties": {
            "text": {"type": "string"},
            "art": {"type": "string", "enum": ["note", "call", "email", "meeting"], "description": "Notiz, Anruf, E-Mail, Termin"},
            "firma": {"type": "string"}, "kontakt": {"type": "string"}, "lead": {"type": "string"},
        }, "required": ["text"]},
    }},
    {"type": "function", "function": {
        "name": "kontakt_anlegen",
        "description": "Schlägt einen neuen Kontakt vor, optional bei einer Firma.",
        "parameters": {"type": "object", "properties": {
            "vorname": {"type": "string"}, "nachname": {"type": "string"}, "email": {"type": "string"},
            "telefon": {"type": "string"}, "position": {"type": "string"}, "firma": {"type": "string"},
        }, "required": ["nachname"]},
    }},
    {"type": "function", "function": {
        "name": "lead_verschieben",
        "description": "Schlägt vor, einen Lead auf eine andere Stufe seiner Pipeline zu setzen.",
        "parameters": {"type": "object", "properties": {
            "lead": {"type": "string", "description": "Name des Leads oder der Firma"},
            "stufe": {"type": "string", "description": "Name der Zielstufe, z. B. Angebot"},
        }, "required": ["lead", "stufe"]},
    }},
]

LESEND = {"suchen", "aufgaben_offen", "seite_oeffnen"}


class Nachfrage(Exception):  # noqa: N818 — Hausstil: deutsch, kein Error-Suffix
    """Das Werkzeug kann nicht eindeutig handeln — das Modell soll fragen."""


# ---------------------------------------------------------------------------
# Auflösen: Name → Datensatz
# ---------------------------------------------------------------------------

_SQL_JE_ART = {art: sql for art, _pfad, sql in ARTEN}
_PFAD_JE_ART = {art: pfad for art, pfad, _sql in ARTEN}


async def _finden(conn: asyncpg.Connection, art: str, text: str) -> dict[str, Any]:
    """Genau ein Datensatz — sonst eine Nachfrage mit den Kandidaten."""
    text = (text or "").strip()
    if not text:
        raise Nachfrage(f"Welche{'r' if art == 'kontakt' else ''} {art.capitalize()} ist gemeint?")
    zeilen = [dict(z) for z in await conn.fetch(_SQL_JE_ART[art], f"%{text}%", 6)]
    genau = [z for z in zeilen if (z["titel"] or "").casefold() == text.casefold()]
    if len(genau) == 1:
        zeilen = genau
    if len(zeilen) == 1:
        return zeilen[0]
    if not zeilen:
        raise Nachfrage(f"Im Bestand gibt es keine {art.capitalize()} „{text}“.")
    namen = "; ".join(f"{z['titel']}" + (f" ({z['untertitel']})" if z.get("untertitel") else "") for z in zeilen[:5])
    raise Nachfrage(f"Mehrere Treffer für „{text}“: {namen}. Welche ist gemeint?")


async def _bezug(conn: asyncpg.Connection, args: dict[str, Any]) -> tuple[dict[str, Any], list[list[str]]]:
    """Firma, Kontakt oder Lead aus den Argumenten — Kennungen und Anzeigezeilen."""
    koerper: dict[str, Any] = {}
    zeilen: list[list[str]] = []
    for schluessel, art, spalte, label in (("firma", "firma", "company_id", "Firma"), ("kontakt", "kontakt", "contact_id", "Kontakt"), ("lead", "geschaeft", "deal_id", "Lead")):
        if args.get(schluessel):
            z = await _finden(conn, art, str(args[schluessel]))
            koerper[spalte] = str(z["id"])
            zeilen.append([label, z["titel"]])
    return koerper, zeilen


def _datum(wert: Any) -> str | None:
    if not wert:
        return None
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})", str(wert))
    if not m:
        return None
    try:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3))).isoformat()
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Werkzeuge
# ---------------------------------------------------------------------------


async def w_suchen(conn: asyncpg.Connection, args: dict[str, Any]) -> Any:
    text = str(args.get("text") or "").strip()
    if len(text) < 2:
        return {"treffer": []}
    treffer = []
    for art, pfad, sql in ARTEN:
        for z in await conn.fetch(sql, f"%{text}%", 4):
            treffer.append({"art": art, "name": z["titel"], "info": z["untertitel"], "pfad": pfad.format(id=z["id"])})
    return {"treffer": treffer[:16]}


async def w_aufgaben_offen(conn: asyncpg.Connection, args: dict[str, Any]) -> Any:
    zeilen = await conn.fetch(
        """
        select t.id, t.title, t.due_at::date::text as faellig, f.name as firma
          from public.tasks t left join public.companies f on f.id = t.company_id
         where t.deleted_at is null and t.completed_at is null
         order by t.due_at nulls last limit 15
        """
    )
    heute = date.today().isoformat()
    return {"aufgaben": [{"titel": z["title"], "faellig": z["faellig"], "ueberfaellig": bool(z["faellig"] and z["faellig"] < heute), "firma": z["firma"], "pfad": "/aufgaben"} for z in zeilen]}


async def w_seite_oeffnen(conn: asyncpg.Connection, args: dict[str, Any]) -> Any:
    pfad = str(args.get("pfad") or "").strip()
    if not pfad:
        pfad = SEITEN.get(str(args.get("bereich") or "").lower(), "")
    if not re.match(r"^/[a-z0-9\-/]*$", pfad or "x"):
        raise Nachfrage("Diesen Pfad kenne ich nicht.")
    return {"navigation": pfad}


async def w_aufgabe_anlegen(conn: asyncpg.Connection, args: dict[str, Any]) -> dict[str, Any]:
    bezug, zeilen = await _bezug(conn, args)
    titel = str(args.get("titel") or "").strip()
    if not titel:
        raise Nachfrage("Wie soll die Aufgabe heißen?")
    faellig = _datum(args.get("faellig"))
    koerper: dict[str, Any] = {"title": titel, "body": (str(args.get("notiz") or "").strip() or None), **bezug}
    if faellig:
        koerper["due_at"] = f"{faellig}T09:00:00"
    anzeige = [["Titel", titel]] + ([["Fällig", f"{faellig[8:10]}.{faellig[5:7]}.{faellig[:4]}"]] if faellig else []) + zeilen
    return {"art": "aufgabe", "titel": "Aufgabe anlegen", "zeilen": anzeige,
            "anfrage": {"methode": "POST", "pfad": "/api/tasks", "koerper": koerper}, "danach": "/aufgaben"}


async def w_notiz_anlegen(conn: asyncpg.Connection, args: dict[str, Any]) -> dict[str, Any]:
    bezug, zeilen = await _bezug(conn, args)
    if not bezug:
        raise Nachfrage("Zu welcher Firma, welchem Kontakt oder Lead gehört die Notiz?")
    text = str(args.get("text") or "").strip()
    if not text:
        raise Nachfrage("Was soll in der Notiz stehen?")
    art = args.get("art") if args.get("art") in ("note", "call", "email", "meeting") else "note"
    wort = {"note": "Notiz", "call": "Anruf", "email": "E-Mail", "meeting": "Termin"}[art]
    return {"art": "notiz", "titel": f"{wort} festhalten", "zeilen": [["Text", text[:300]]] + zeilen,
            "anfrage": {"methode": "POST", "pfad": "/api/activities", "koerper": {"kind": art, "body": text, **bezug}},
            "danach": next((f"/firmen/{v}" if k == "company_id" else f"/kontakte/{v}" if k == "contact_id" else f"/deals/{v}" for k, v in bezug.items()), None)}


async def w_kontakt_anlegen(conn: asyncpg.Connection, args: dict[str, Any]) -> dict[str, Any]:
    nachname = str(args.get("nachname") or "").strip()
    if not nachname:
        raise Nachfrage("Wie heißt die Person mit Nachnamen?")
    koerper: dict[str, Any] = {"last_name": nachname, "first_name": (str(args.get("vorname") or "").strip() or None),
                               "email": (str(args.get("email") or "").strip().lower() or None),
                               "phone": (str(args.get("telefon") or "").strip() or None),
                               "job_title": (str(args.get("position") or "").strip() or None)}
    zeilen = [["Name", " ".join(t for t in (koerper["first_name"], nachname) if t)]]
    for label, k in (("E-Mail", "email"), ("Telefon", "phone"), ("Position", "job_title")):
        if koerper[k]:
            zeilen.append([label, koerper[k]])
    if args.get("firma"):
        f = await _finden(conn, "firma", str(args["firma"]))
        koerper["company_id"] = str(f["id"])
        zeilen.append(["Firma", f["titel"]])
    return {"art": "kontakt", "titel": "Kontakt anlegen", "zeilen": zeilen,
            "anfrage": {"methode": "POST", "pfad": "/api/contacts", "koerper": koerper}, "danach": "/kontakte/{id}"}


async def w_lead_verschieben(conn: asyncpg.Connection, args: dict[str, Any]) -> dict[str, Any]:
    lead = await _finden(conn, "geschaeft", str(args.get("lead") or ""))
    stufen = [dict(z) for z in await conn.fetch(
        "select s.id, s.name from public.pipeline_stages s join public.deals d on d.pipeline_id = s.pipeline_id "
        "where d.id = $1 order by s.position", lead["id"])]
    wunsch = str(args.get("stufe") or "").strip().casefold()
    passend = [s for s in stufen if s["name"].casefold() == wunsch] or [s for s in stufen if wunsch and wunsch in s["name"].casefold()]
    if len(passend) != 1:
        raise Nachfrage("Die Stufen dieser Pipeline heißen: " + ", ".join(s["name"] for s in stufen) + ". Welche ist gemeint?")
    return {"art": "lead_stufe", "titel": "Lead verschieben", "zeilen": [["Lead", lead["titel"]], ["Neue Stufe", passend[0]["name"]]],
            "anfrage": {"methode": "POST", "pfad": f"/api/deals/{lead['id']}/stage", "koerper": {"stage_id": str(passend[0]["id"])}},
            "danach": f"/deals/{lead['id']}"}


AUSFUEHRER = {
    "suchen": w_suchen, "aufgaben_offen": w_aufgaben_offen, "seite_oeffnen": w_seite_oeffnen,
    "aufgabe_anlegen": w_aufgabe_anlegen, "notiz_anlegen": w_notiz_anlegen,
    "kontakt_anlegen": w_kontakt_anlegen, "lead_verschieben": w_lead_verschieben,
}


# ---------------------------------------------------------------------------
# Die Schleife
# ---------------------------------------------------------------------------


def _args(aufruf: dict[str, Any]) -> dict[str, Any]:
    roh = (aufruf.get("function") or {}).get("arguments")
    if isinstance(roh, dict):
        return roh
    try:
        daten = json.loads(roh or "{}")
    except ValueError:
        return {}
    return daten if isinstance(daten, dict) else {}


async def auftrag(
    conn: asyncpg.Connection, cfg: LLMConfig, nachricht: str, verlauf: list[dict[str, str]]
) -> dict[str, Any]:
    """Ein Auftrag: Modell fragen, Werkzeuge ausführen, bis eine Antwort steht."""
    nachrichten: list[dict[str, Any]] = [{"role": "system", "content": SYSTEM.format(heute=date.today().isoformat())}]
    for eintrag in verlauf[-10:]:
        if eintrag.get("rolle") in ("nutzer", "assistent") and eintrag.get("inhalt"):
            nachrichten.append({"role": "user" if eintrag["rolle"] == "nutzer" else "assistant", "content": str(eintrag["inhalt"])[:2000]})
    nachrichten.append({"role": "user", "content": nachricht.strip()[:2000]})

    karten: list[dict[str, Any]] = []
    navigation: str | None = None
    schritte: list[str] = []
    antwort = ""
    for _ in range(SCHRITTE_HOECHSTENS):
        m = await chat_werkzeuge(cfg, nachrichten, WERKZEUGE)
        aufrufe = m.get("tool_calls") or []
        nachrichten.append({"role": "assistant", "content": m.get("content") or "", "tool_calls": aufrufe} if aufrufe else {"role": "assistant", "content": m.get("content") or ""})
        if not aufrufe:
            antwort = (m.get("content") or "").strip()
            break
        for aufruf in aufrufe:
            name = (aufruf.get("function") or {}).get("name") or ""
            schritte.append(name)
            werkzeug = AUSFUEHRER.get(name)
            try:
                if werkzeug is None:
                    raise Nachfrage(f"Das Werkzeug {name} gibt es nicht.")
                ergebnis = await werkzeug(conn, _args(aufruf))
                if name in LESEND:
                    if isinstance(ergebnis, dict) and ergebnis.get("navigation"):
                        navigation = ergebnis["navigation"]
                    inhalt = json.dumps(ergebnis, ensure_ascii=False)
                else:
                    ergebnis["id"] = f"k{len(karten) + 1}"
                    karten.append(ergebnis)
                    inhalt = json.dumps({"vorschlag": ergebnis["titel"], "zeilen": ergebnis["zeilen"], "hinweis": "Als Karte zur Bestätigung vorgelegt."}, ensure_ascii=False)
            except Nachfrage as exc:
                inhalt = json.dumps({"nachfrage": str(exc)}, ensure_ascii=False)
            nachrichten.append({"role": "tool", "tool_call_id": aufruf.get("id") or name, "name": name, "content": inhalt})
    else:
        antwort = antwort or "Das wurde mir zu lang — bitte den Auftrag in kleinere Schritte teilen."

    if not antwort and karten:
        antwort = "Bitte prüfen und ausführen." if len(karten) == 1 else "Bitte prüfen — jede Karte lässt sich einzeln ausführen."
    return {"antwort": antwort, "karten": karten, "navigation": navigation, "schritte": schritte}
