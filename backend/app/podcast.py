"""Gespräch vorbereiten — der Bestand als kurzer Podcast.

Vor einem Kundengespräch liest niemand dreißig Verlaufseinträge, drei
Tickets und die Aussagen aus dem letzten Quartal. Gehört auf dem Weg
dorthin, sind es acht Minuten: Eine Moderatorin fragt, ein Kollege aus
dem Vertrieb antwortet aus dem Bestand — wer die Firma ist, was zuletzt
geschah, was offen ist, was Kunden gesagt haben, und mit welchen drei
Fragen man ins Gespräch geht.

Drei Schritte, alle auf der Box:

1. **Kontext.** Dieselbe Zusammenstellung wie für die KI-Zusammenfassung
   (`routers/ki._kontext_firma`), dazu Tickets, Aussagen aus den
   Erkenntnissen, offene Aufgaben und Angebote.
2. **Skript.** Das Sprachmodell schreibt ein Gespräch in Segmenten mit
   Sprecherwechsel. Es erfindet nichts: Was im Bestand fehlt, wird als
   offene Frage benannt.
3. **Stimme.** Jedes Segment geht an die Sprachausgabe (Speaches,
   OpenAI-kompatibel) — je Sprecher ein Modell. Die Teile werden zu einer
   MP3-Datei zusammengefügt und unter /app/data abgelegt.

Nichts verlässt die Box: Modell und Sprachausgabe laufen dort, die Datei
liegt dort, abgespielt wird sie in Beacon.
"""

from __future__ import annotations

import asyncio
import logging
import os
import pathlib
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any
from uuid import UUID

import asyncpg
import httpx
import orjson

from app.config import settings
from app.llm import LLMConfig, chat, json_aus_antwort, load_llm_config

if TYPE_CHECKING:
    from app.auth import CurrentUser

log = logging.getLogger(__name__)

SPRECHER = ("moderatorin", "kollege")
# Ein Denkmodell überlegt erst und schreibt dann; das Skript selbst hat um
# die tausend Token, das Überlegen darf ein Mehrfaches davon haben.
SKRIPT_TOKENS = 16000
WOERTER_JE_SEKUNDE = 2.4
STUNDEN_VORAUS = 24

# ── Einrichtung ──────────────────────────────────────────────────────────


class TTSNichtEingerichtet(RuntimeError):  # noqa: N818
    """Keine Sprachausgabe hinterlegt — kein Grund für einen Netzwerkversuch."""


@dataclass(frozen=True)
class TTSConfig:
    endpoint_url: str
    api_key: str
    # Stimme 1: der Kollege aus dem Vertrieb. Stimme 2: die Moderatorin.
    modell: str
    stimme: str
    modell_2: str
    stimme_2: str

    @property
    def eingerichtet(self) -> bool:
        return bool(self.endpoint_url.strip())

    @property
    def auth_header(self) -> dict[str, str]:
        key = self.api_key.strip()
        return {"Authorization": f"Bearer {key}"} if key else {}

    def fuer(self, sprecher: str) -> tuple[str, str]:
        """Modell und Stimme für einen Sprecher des Skripts."""
        if sprecher == "moderatorin":
            return (self.modell_2 or self.modell, self.stimme_2)
        return (self.modell, self.stimme)


async def load_tts_config(conn: asyncpg.Connection, org_id: UUID) -> TTSConfig:
    row = await conn.fetchrow(
        "select tts_endpoint_url, tts_api_key, tts_modell, tts_stimme, tts_modell_2, tts_stimme_2 "
        "from public.org_settings where org_id = $1",
        org_id,
    )
    return TTSConfig(
        endpoint_url=((row["tts_endpoint_url"] if row else None) or "").strip(),
        api_key=((row["tts_api_key"] if row else None) or "").strip(),
        modell=((row["tts_modell"] if row else None) or "").strip(),
        stimme=((row["tts_stimme"] if row else None) or "").strip(),
        modell_2=((row["tts_modell_2"] if row else None) or "").strip(),
        stimme_2=((row["tts_stimme_2"] if row else None) or "").strip(),
    )


def http_client(timeout: float = 120.0) -> httpx.AsyncClient:
    """Ein Klient für die Sprachausgabe. Die Tests tauschen ihn aus."""
    return httpx.AsyncClient(timeout=timeout)


# ── Kontext ──────────────────────────────────────────────────────────────


async def _bloecke(conn: asyncpg.Connection, company_id: UUID | None, deal_id: UUID | None) -> list[str]:
    """Was die KI-Zusammenfassung nicht kennt: Tickets, Aussagen, Aufgaben, Angebote."""
    if company_id is None and deal_id is None:
        return []
    tickets = await conn.fetch(
        """
        select t.nummer, t.betreff, t.prioritaet, s.name as stufe, t.created_at
          from public.tickets t
          join public.ticket_stages s on s.id = t.stage_id
         where (t.company_id = $1 or t.deal_id = $2) and t.deleted_at is null and t.geschlossen_am is null
         order by t.created_at desc limit 10
        """,
        company_id, deal_id,
    )
    aussagen = await conn.fetch(
        """
        select s.art, s.produkt, s.text, s.zitat, a.occurred_at
          from public.aussagen s
          join public.activities a on a.id = s.activity_id
         where s.company_id = $1 or a.deal_id = $2
         order by a.occurred_at desc limit 15
        """,
        company_id, deal_id,
    )
    aufgaben = await conn.fetch(
        """
        select t.title, t.art, t.due_at
          from public.tasks t
         where (t.company_id = $1 or t.deal_id = $2) and t.status = 'open'
         order by t.due_at nulls last limit 10
        """,
        company_id, deal_id,
    )
    angebote = await conn.fetch(
        """
        select q.title, q.status, q.valid_until, q.sent_at,
               (select coalesce(sum(round(i.quantity * i.unit_price_cents * (1 - i.discount_percent / 100))), 0) from public.quote_items i where i.quote_id = q.id) as netto
          from public.quotes q
         where q.deal_id = $2
            or ($1::uuid is not null and q.deal_id in (select id from public.deals where company_id = $1 and deleted_at is null))
         order by q.created_at desc limit 5
        """,
        company_id, deal_id,
    )
    zeilen: list[str] = []
    if tickets:
        zeilen += ["", "Offene Tickets:"] + [
            f"- T-{t['nummer']} {t['betreff']} ({t['prioritaet']}, {t['stufe']}, seit {t['created_at']:%d.%m.%Y})" for t in tickets
        ]
    if aussagen:
        zeilen += ["", "Was Kunden dieser Firma gesagt haben (aus Notizen, mit Zitat):"] + [
            f"- {a['occurred_at']:%d.%m.%Y} [{a['art']}{', ' + a['produkt'] if a['produkt'] else ''}] {a['text']}"
            + (f' — „{a["zitat"]}“' if a["zitat"] else "")
            for a in aussagen
        ]
    if aufgaben:
        zeilen += ["", "Offene Aufgaben:"] + [
            f"- {t['title']} ({t['art']}{', fällig ' + t['due_at'].strftime('%d.%m.%Y %H:%M') if t['due_at'] else ''})" for t in aufgaben
        ]
    if angebote:
        zeilen += ["", "Angebote:"] + [
            f"- {q['title']}: {q['netto'] / 100:.0f} € netto, {q['status']}"
            + (f", gültig bis {q['valid_until']:%d.%m.%Y}" if q["valid_until"] else "")
            for q in angebote
        ]
    return zeilen


async def kontext(user: CurrentUser, entity: str, entity_id: UUID) -> tuple[str, str, UUID | None, UUID | None]:
    """Der ganze Bestand zu Firma oder Lead als Text.

    Gibt (Text, Name, company_id, deal_id) zurück. Die Firma kommt aus
    derselben Zusammenstellung wie die KI-Zusammenfassung — ein Bestand,
    eine Sicht, egal wer ihn liest.
    """
    from app.db import acquire_as
    from app.routers.ki import _kontext_firma

    company_id: UUID | None = None
    deal_id: UUID | None = None
    kopf: list[str] = []
    if entity == "deals":
        async with acquire_as(user.user_id) as conn:
            deal = await conn.fetchrow(
                "select d.*, s.name as stufe, s.probability from public.deals d "
                "join public.pipeline_stages s on s.id = d.stage_id "
                "where d.id = $1 and d.deleted_at is null",
                entity_id,
            )
        if deal is None:
            raise LookupError("Lead nicht gefunden")
        deal_id = deal["id"]
        company_id = deal["company_id"]
        name = deal["name"]
        kopf = [
            f"Lead: {deal['name']}",
            f"Produkt: {deal['product']}",
            f"Betrag: {deal['amount_cents'] / 100:.0f} €",
            f"Stufe: {deal['stufe']} (Wahrscheinlichkeit {float(deal['probability']):.0%})",
            f"Abschluss geplant: {deal['close_date'] or 'offen'}",
            f"Notierter nächster Schritt: {deal['next_step'] or '—'}",
            "",
        ]
    else:
        company_id = entity_id

    firma = ""
    if company_id is not None:
        firma = await _kontext_firma(user, company_id)
        if entity != "deals":
            name = firma.splitlines()[0].removeprefix("Firma: ").strip()
    async with acquire_as(user.user_id) as conn:
        mehr = await _bloecke(conn, company_id, deal_id)
    return "\n".join([*kopf, firma, *mehr]).strip(), name, company_id, deal_id


# ── Skript ───────────────────────────────────────────────────────────────

SYSTEM_PODCAST = (
    "Du schreibst kurze Gesprächsvorbereitungen als Podcast für den Vertrieb von AImighty. "
    "AImighty liefert lokal betriebene KI-Systeme an den deutschen Mittelstand — Hardware, "
    "Software und Einführung aus einer Hand, ohne Cloud. Zwei Stimmen: die MODERATORIN führt "
    "durch die Folge, stellt die Fragen und fasst zusammen; der KOLLEGE aus dem Vertrieb kennt "
    "den Bestand und antwortet daraus. Beide sprechen den Hörer als „Sie“ an, wenn sie ihn "
    "direkt meinen, und nennen sich nicht mit Namen. Kurzweilig, aber ohne Werbesprache. "
    "Du erfindest nichts: Was nicht in den übergebenen Daten steht, wird als offene Frage "
    "benannt. Antworte ausschließlich als JSON-Objekt."
)


def _frage(bestand: str, anlass: str) -> str:
    return (
        f"Anlass: {anlass}\n\n"
        "Schreibe das Gespräch für die Vorbereitung. Aufbau:\n"
        "1. Aufhänger — die Moderatorin sagt in zwei Sätzen, worum es geht.\n"
        "2. Wer sie sind — Firma, Branche, Größe, die Ansprechpartner und ihre Rollen.\n"
        "3. Was zuletzt geschah — die letzten Berührungen, in Reihenfolge.\n"
        "4. Was offen ist — Leads, Angebote, Tickets, Aufgaben.\n"
        "5. Was Kunden gesagt haben — ein wörtliches Zitat, wenn eines vorliegt.\n"
        "6. Ziel und drei Fragen für das Gespräch — der Kollege schlägt vor, die Moderatorin fasst zusammen.\n"
        "7. Schluss — ein Satz.\n\n"
        "Regeln: Etwa fünf Minuten gesprochen — ungefähr fünfhundert Wörter, nicht nachzählen. "
        "Um die zehn Segmente, Sprecherwechsel nach jedem Segment. Kurze Sätze, gesprochene "
        "Sprache. Keine Ziffern — Zahlen in Worten oder gerundet („rund zehntausend Euro“, "
        "„vor drei Wochen“). Keine Aufzählungszeichen, kein Markdown. Nichts erfinden: Fehlt "
        "etwas im Bestand, sagt der Kollege das und macht eine Frage daraus. Schreib das "
        "Gespräch in einem Zug, ohne Entwürfe.\n\n"
        'Antworte als {"titel": "...", "segmente": [{"sprecher": "moderatorin", "text": "..."}, '
        '{"sprecher": "kollege", "text": "..."}]}.\n\n'
        f"Bestand:\n{bestand}"
    )


def _segmente_pruefen(roh: Any, rueckfall: str) -> tuple[str | None, list[dict[str, str]]]:
    """Titel und Segmente aus der Modellantwort — oder der ganze Text als
    ein Segment des Kollegen, wenn das Modell kein JSON lieferte."""
    if not isinstance(roh, dict):
        text = rueckfall.strip()
        return None, [{"sprecher": "kollege", "text": text}] if text else []
    segmente: list[dict[str, str]] = []
    for eintrag in roh.get("segmente") or []:
        if not isinstance(eintrag, dict):
            continue
        text = " ".join(str(eintrag.get("text") or "").split())
        if not text:
            continue
        sprecher = str(eintrag.get("sprecher") or "").strip().lower()
        if sprecher not in SPRECHER:
            sprecher = "kollege" if not segmente or segmente[-1]["sprecher"] == "moderatorin" else "moderatorin"
        segmente.append({"sprecher": sprecher, "text": text[:2000]})
    titel = str(roh.get("titel") or "").strip()[:160] or None
    return titel, segmente


async def skript_schreiben(cfg: LLMConfig, bestand: str, anlass: str) -> tuple[str | None, list[dict[str, str]]]:
    antwort = await chat(cfg, SYSTEM_PODCAST, _frage(bestand, anlass), temperature=0.7, max_tokens=SKRIPT_TOKENS)
    roh: Any = None
    if antwort.strip():
        try:
            roh = json_aus_antwort(antwort)
        except Exception:  # noqa: BLE001 — kein JSON heißt: der Text ist das Skript
            roh = None
    titel, segmente = _segmente_pruefen(roh, antwort)
    if not segmente:
        raise RuntimeError("Das Modell hat kein Skript geliefert.")
    return titel, segmente


# ── Stimme ───────────────────────────────────────────────────────────────

ABKUERZUNGEN = [
    (r"\bz\.\s?B\.", "zum Beispiel"),
    (r"\bu\.\s?a\.", "unter anderem"),
    (r"\bbzw\.", "beziehungsweise"),
    (r"\bca\.", "circa"),
    (r"\bggf\.", "gegebenenfalls"),
    (r"\bvgl\.", "vergleiche"),
    (r"\busw\.", "und so weiter"),
    (r"\bevtl\.", "eventuell"),
    (r"\bMio\.", "Millionen"),
    (r"\bTsd\.", "Tausend"),
    (r"\bNr\.", "Nummer"),
    (r"\bStr\.", "Straße"),
    (r"\bGmbH\b", "G m b H"),
    (r"\bKI\b", "K I"),
    (r"\bIT\b", "I T"),
    (r"\bCRM\b", "C R M"),
]


def fuer_stimme(text: str) -> str:
    """Macht aus geschriebenem Text etwas, das eine Stimme lesen kann.

    Markdown-Zeichen raus, Symbole in Worte, gängige Abkürzungen
    ausgeschrieben, Leerraum gebündelt. Das Skript selbst bleibt, wie das
    Modell es schrieb — das hier ist nur die Fassung für die Stimme.
    """
    t = re.sub(r"[*_`#>]+", "", text)
    t = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", t)
    t = t.replace("€", " Euro").replace("%", " Prozent").replace("&", " und ").replace("§", " Paragraf ")
    t = t.replace("–", ", ").replace("—", ", ").replace("/", " ")
    for muster, ersatz in ABKUERZUNGEN:
        t = re.sub(muster, ersatz, t)
    t = re.sub(r"(\d)\.(\d{3})\b", r"\1\2", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t


def dauer_schaetzen(segmente: list[dict[str, str]]) -> int:
    woerter = sum(len(s["text"].split()) for s in segmente)
    return int(round(woerter / WOERTER_JE_SEKUNDE))


def _synchsafe(b: bytes) -> int:
    return (b[0] << 21) | (b[1] << 14) | (b[2] << 7) | b[3]


_BITRATEN = {
    # (Version, Layer) → Tabelle in kbit/s, Index 1..14
    ("1", 3): [0, 32, 40, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320],
    ("2", 3): [0, 8, 16, 24, 32, 40, 48, 56, 64, 80, 96, 112, 128, 144, 160],
}
_ABTASTRATEN = {"1": [44100, 48000, 32000], "2": [22050, 24000, 16000], "2.5": [11025, 12000, 8000]}


def _rahmenlaenge(kopf: bytes) -> int | None:
    """Länge des MPEG-Layer-III-Rahmens, dessen Kopf hier beginnt — oder None."""
    if len(kopf) < 4 or kopf[0] != 0xFF or (kopf[1] & 0xE0) != 0xE0:
        return None
    version = {0: "2.5", 2: "2", 3: "1"}.get((kopf[1] >> 3) & 0x03)
    layer = {1: 3, 2: 2, 3: 1}.get((kopf[1] >> 1) & 0x03)
    if version is None or layer != 3:
        return None
    bitrate_index = kopf[2] >> 4
    rate_index = (kopf[2] >> 2) & 0x03
    if bitrate_index in (0, 15) or rate_index == 3:
        return None
    bitrate = _BITRATEN[("1" if version == "1" else "2", 3)][bitrate_index] * 1000
    abtast = _ABTASTRATEN[version][rate_index]
    padding = (kopf[2] >> 1) & 0x01
    proben = 1152 if version == "1" else 576
    return int(proben / 8 * bitrate / abtast) + padding


def _mp3_kern(daten: bytes, *, erster: bool) -> bytes:
    """Ein MP3-Teil ohne ID3-Kopf und — ab dem zweiten Teil — ohne den
    Xing/Info-Rahmen, der sonst mitten in der Datei als Stille läge."""
    d = daten
    if d[:3] == b"ID3" and len(d) >= 10:
        d = d[10 + _synchsafe(d[6:10]) :]
    # Zum ersten Rahmen springen.
    start = 0
    while start + 4 <= len(d) and _rahmenlaenge(d[start : start + 4]) is None:
        start += 1
    d = d[start:]
    if not erster:
        laenge = _rahmenlaenge(d[:4])
        if laenge and (b"Xing" in d[:laenge] or b"Info" in d[:laenge]):
            d = d[laenge:]
    return d


def mp3_zusammenfuegen(teile: list[bytes]) -> bytes:
    """Hängt MP3-Teile aneinander. Kopfdaten kommen nur einmal."""
    return b"".join(_mp3_kern(t, erster=(i == 0)) for i, t in enumerate([t for t in teile if t]))


# Je Modell die Stimme, die der Dienst angenommen hat — einmal ermittelt,
# dann gemerkt. Piper-Modelle bei Speaches tragen ihre Stimme im Namen,
# Kokoro hat Dutzende; wer keine einträgt, bekommt die erste passende.
STIMMEN_ERMITTELT: dict[str, str] = {}


async def _stimme_ermitteln(client: httpx.AsyncClient, tts: TTSConfig, modell: str) -> str:
    """Die Stimme eines Modells, wenn keine eingetragen ist.

    Speaches führt die Stimmen je Modell in `GET /v1/models` (Feld
    `voices`, gemessen auf der Box am 7.9.2026: Kokoro mit `af_heart` …);
    einen eigenen Stimmen-Endpunkt gibt es dort nicht. Deutsche Stimme
    zuerst, sonst die erste. Kennt der Dienst das Feld nicht, werden
    naheliegende Kennungen durchprobiert — die erste, die er annimmt, gilt.
    """
    if modell in STIMMEN_ERMITTELT:
        return STIMMEN_ERMITTELT[modell]
    basis = tts.endpoint_url.rstrip("/")
    try:
        r = await client.get(f"{basis}/v1/models", headers=tts.auth_header)
        if r.status_code == 200:
            daten = r.json()
            for m in (daten.get("data") if isinstance(daten, dict) else daten) or []:
                if not isinstance(m, dict) or m.get("id") != modell:
                    continue
                stimmen = [v for v in (m.get("voices") or []) if isinstance(v, dict) and v.get("id")]
                deutsch = [v for v in stimmen if str(v.get("language") or "").lower().startswith("de")]
                for v in deutsch + stimmen:
                    STIMMEN_ERMITTELT[modell] = str(v["id"])
                    return STIMMEN_ERMITTELT[modell]
    except (httpx.HTTPError, ValueError):
        pass
    kandidaten = [modell.rsplit("piper-", 1)[-1], modell, "0", ""]
    for k in kandidaten:
        r = await client.post(
            f"{basis}/v1/audio/speech",
            json={"model": modell, "input": "Test.", "voice": k, "response_format": "mp3"},
            headers=tts.auth_header,
        )
        if r.status_code == 200:
            STIMMEN_ERMITTELT[modell] = k
            return k
    raise RuntimeError(f"Keine Stimme für {modell} gefunden — bitte in den Einstellungen eintragen.")


async def sprechen_einzeln(client: httpx.AsyncClient, tts: TTSConfig, sprecher: str, text: str) -> bytes:
    modell, stimme = tts.fuer(sprecher)
    if not modell:
        raise TTSNichtEingerichtet("Für die Sprachausgabe ist kein Modell eingetragen.")
    if not stimme:
        stimme = await _stimme_ermitteln(client, tts, modell)
    r = await client.post(
        f"{tts.endpoint_url.rstrip('/')}/v1/audio/speech",
        json={"model": modell, "input": fuer_stimme(text), "voice": stimme, "response_format": "mp3"},
        headers=tts.auth_header,
    )
    r.raise_for_status()
    return r.content


async def sprechen(tts: TTSConfig, segmente: list[dict[str, str]], stand: Any = None) -> bytes:
    """Alle Segmente, je Sprecher mit seiner Stimme, als eine MP3-Datei."""
    if not tts.eingerichtet:
        raise TTSNichtEingerichtet("Es ist keine Sprachausgabe hinterlegt. Die Adresse steht unter Einstellungen.")
    teile: list[bytes] = []
    async with http_client() as client:
        for i, s in enumerate(segmente, start=1):
            if stand is not None:
                await stand(schritt="audio", segment=i, gesamt=len(segmente))
            teile.append(await sprechen_einzeln(client, tts, s["sprecher"], s["text"]))
    return mp3_zusammenfuegen(teile)


# ── Ablage ───────────────────────────────────────────────────────────────


def ablage() -> pathlib.Path:
    ordner = pathlib.Path(settings.app_data_dir) / "podcasts"
    ordner.mkdir(parents=True, exist_ok=True)
    return ordner


def datei_schreiben(org_id: UUID, podcast_id: UUID, daten: bytes) -> str:
    """Schreibt die Folge und gibt den Pfad relativ zu app_data zurück."""
    ordner = ablage() / str(org_id)
    ordner.mkdir(parents=True, exist_ok=True)
    ziel = ordner / f"{podcast_id}.mp3"
    vorlaeufig = ziel.with_suffix(".mp3.teil")
    vorlaeufig.write_bytes(daten)
    os.chmod(vorlaeufig, 0o600)
    vorlaeufig.rename(ziel)
    return f"podcasts/{org_id}/{podcast_id}.mp3"


def datei_pfad(relativ: str | None) -> pathlib.Path | None:
    """Der absolute Pfad — nur innerhalb der Ablage, sonst nichts."""
    if not relativ:
        return None
    wurzel = pathlib.Path(settings.app_data_dir).resolve()
    pfad = (wurzel / relativ).resolve()
    if wurzel not in pfad.parents:
        return None
    return pfad


def datei_loeschen(relativ: str | None) -> None:
    pfad = datei_pfad(relativ)
    if pfad is not None:
        pfad.unlink(missing_ok=True)


# ── Der Lauf ─────────────────────────────────────────────────────────────


async def _stand(user: CurrentUser, podcast_id: UUID, **felder: Any) -> None:
    """Fortschritt in die Zeile — in einer eigenen, kurzen Transaktion,
    damit die Seite ihn sieht, während der Lauf noch arbeitet."""
    from app.db import acquire_as

    async with acquire_as(user.user_id) as conn:
        await conn.execute(
            "update public.podcasts set fortschritt = $1::jsonb, updated_at = now() where id = $2",
            orjson.dumps(felder).decode(), podcast_id,
        )


async def erzeugen(user: CurrentUser, podcast_id: UUID) -> None:
    from app.db import acquire_as

    async with acquire_as(user.user_id) as conn:
        zeile = await conn.fetchrow("select * from public.podcasts where id = $1", podcast_id)
        if zeile is None:
            raise LookupError("Podcast nicht gefunden")
        cfg = await load_llm_config(conn, user.org_id)
        tts = await load_tts_config(conn, user.org_id)
        termin = await conn.fetchrow("select title, due_at from public.tasks where id = $1", zeile["task_id"]) if zeile["task_id"] else None

    anlass = zeile["anlass"] or (
        f"{termin['title']}" + (f" am {termin['due_at']:%d.%m.%Y um %H:%M Uhr}" if termin["due_at"] else "")
        if termin else "das nächste Gespräch"
    )

    await _stand(user, podcast_id, schritt="kontext")
    bestand, name, company_id, deal_id = await kontext(user, zeile["entity"], zeile["entity_id"])

    await _stand(user, podcast_id, schritt="skript")
    titel, segmente = await skript_schreiben(cfg, bestand, anlass)
    titel = titel or f"Gespräch vorbereiten: {name}"
    skript = "\n\n".join(f"{'Moderatorin' if s['sprecher'] == 'moderatorin' else 'Kollege'}: {s['text']}" for s in segmente)

    async def stand(**f: Any) -> None:
        await _stand(user, podcast_id, **f)

    daten = await sprechen(tts, segmente, stand)
    relativ = datei_schreiben(user.org_id, podcast_id, daten)
    dauer = dauer_schaetzen(segmente)

    async with acquire_as(user.user_id) as conn:
        await conn.execute(
            """
            update public.podcasts
               set status = 'fertig', titel = $1, skript = $2, segmente = $3::jsonb, dauer_s = $4,
                   datei = $5, bytes = $6, modell = $7, stimme = $8, llm_modell = $9, anlass = $10,
                   fortschritt = $11::jsonb, updated_at = now()
             where id = $12
            """,
            titel, skript, orjson.dumps(segmente).decode(), dauer, relativ, len(daten),
            tts.modell, f"{tts.stimme or '-'} / {tts.stimme_2 or '-'}", cfg.model, anlass,
            orjson.dumps({"schritt": "fertig", "segment": len(segmente), "gesamt": len(segmente)}).decode(),
            podcast_id,
        )
        await conn.execute(
            """
            insert into public.activities (org_id, kind, subject, body, company_id, deal_id, payload, created_by)
            values ($1, 'ai', 'Gesprächsvorbereitung als Podcast', $2, $3, $4, $5::jsonb, $6)
            """,
            user.org_id, f"{titel} — etwa {max(1, round(dauer / 60))} Minuten. Anlass: {anlass}",
            company_id if zeile["entity"] == "companies" else None,
            deal_id, orjson.dumps({"podcast_id": str(podcast_id), "modell": cfg.model, "stimme": tts.modell}).decode(),
            user.user_id,
        )


HINTERGRUND: set[asyncio.Task[Any]] = set()


def im_hintergrund(user: CurrentUser, podcast_id: UUID) -> None:
    """Startet den Lauf, ohne die Antwort aufzuhalten — Skript und zwölf
    Segmente Sprache sind auf der Box Minuten, keine Sekunden."""
    from app.db import acquire_as

    async def _arbeit() -> None:
        try:
            await erzeugen(user, podcast_id)
        except Exception as exc:  # noqa: BLE001 — der Fehler gehört in die Zeile, nicht in den Absturz
            log.exception("Podcast fehlgeschlagen (%s)", podcast_id)
            try:
                async with acquire_as(user.user_id) as conn:
                    await conn.execute(
                        "update public.podcasts set status = 'fehler', fehler = $1, updated_at = now() where id = $2",
                        f"{type(exc).__name__}: {exc}"[:500], podcast_id,
                    )
            except Exception:  # noqa: BLE001
                log.exception("Fehler am Podcast konnte nicht abgelegt werden (%s)", podcast_id)

    aufgabe = asyncio.create_task(_arbeit())
    HINTERGRUND.add(aufgabe)
    aufgabe.add_done_callback(HINTERGRUND.discard)


async def hintergrund_abwarten() -> None:
    if HINTERGRUND:
        await asyncio.gather(*list(HINTERGRUND), return_exceptions=True)


# ── Automatik ────────────────────────────────────────────────────────────


async def automatisch_vorbereiten() -> int:
    """Für jeden Termin der nächsten 24 Stunden mit Firma oder Lead eine
    Folge — einmal je Termin, im Namen dessen, dem der Termin gehört.

    Gibt zurück, wie viele Läufe gestartet wurden.
    """
    from app.auth import CurrentUser
    from app.db import acquire, acquire_as

    # org_settings steht unter FORCE ROW LEVEL SECURITY: Ohne Nutzerkontext
    # ist die Tabelle leer. Erst die Organisationen mit ihrem Eigentümer
    # (wie bei der Sicherung), dann je Organisation unter dessen Kennung.
    async with acquire() as conn:
        kandidaten = await conn.fetch(
            """
            select o.id as org_id, r.user_id as owner_id
              from public.orgs o
              join public.user_org_roles r on r.org_id = o.id and r.role = 'owner'
             where o.deleted_at is null
            """
        )
    orgs = []
    for k in kandidaten:
        async with acquire_as(k["owner_id"]) as conn:
            an = await conn.fetchval(
                "select podcast_automatisch and coalesce(tts_endpoint_url, '') <> '' from public.org_settings where org_id = $1",
                k["org_id"],
            )
        if an:
            orgs.append(k)
    gestartet = 0
    for org in orgs:
        async with acquire_as(org["owner_id"]) as conn:
            termine = await conn.fetch(
                """
                select t.id, t.company_id, t.deal_id, t.assigned_to, t.created_by
                  from public.tasks t
                 where t.org_id = $1 and t.status = 'open' and t.art = 'termin'
                   and t.due_at between now() and now() + make_interval(hours => $2)
                   and (t.company_id is not null or t.deal_id is not null)
                   and not exists (select 1 from public.podcasts p where p.task_id = t.id and p.deleted_at is null)
                 order by t.due_at
                """,
                org["org_id"], STUNDEN_VORAUS,
            )
            if not termine:
                continue
            mitglieder = {
                m["id"]: m for m in await conn.fetch(
                    "select u.id, u.olares_username, u.display_name from public.users u "
                    "join public.user_org_roles r on r.user_id = u.id where r.org_id = $1",
                    org["org_id"],
                )
            }
        for t in termine:
            person = mitglieder.get(t["assigned_to"]) or mitglieder.get(t["created_by"]) or mitglieder.get(org["owner_id"])
            if person is None:
                continue
            user = CurrentUser(
                olares_username=person["olares_username"], user_id=person["id"], org_id=org["org_id"],
                display_name=person["display_name"],
            )
            entity, entity_id = ("deals", t["deal_id"]) if t["deal_id"] else ("companies", t["company_id"])
            try:
                async with acquire_as(user.user_id) as conn:
                    row = await conn.fetchrow(
                        "insert into public.podcasts (org_id, entity, entity_id, task_id, created_by) "
                        "values ($1, $2, $3, $4, $5) returning id",
                        org["org_id"], entity, entity_id, t["id"], user.user_id,
                    )
            except asyncpg.UniqueViolationError:
                continue
            im_hintergrund(user, row["id"])
            gestartet += 1
    return gestartet


# ── Speaches: Modelle und Stimmen ────────────────────────────────────────

# Stand laufender Modell-Downloads je Modellkennung.
INSTALLATIONEN: dict[str, str] = {}


def _deutsch(kennung: str) -> bool:
    k = kennung.lower()
    return "de_de" in k or "-de-" in k or k.endswith("-de") or "german" in k


async def modelle(tts: TTSConfig) -> dict[str, Any]:
    """Installierte und verfügbare Sprachmodelle des Dienstes, deutsch zuerst."""
    basis = tts.endpoint_url.rstrip("/")
    async with http_client(timeout=20) as client:
        r = await client.get(f"{basis}/v1/models", headers=tts.auth_header)
        r.raise_for_status()
        daten = r.json()
        installiert = [
            m["id"] for m in (daten.get("data") if isinstance(daten, dict) else daten) or []
            if isinstance(m, dict) and m.get("id") and (m.get("task") in (None, "text-to-speech"))
        ]
        verfuegbar: list[str] = []
        try:
            r2 = await client.get(f"{basis}/v1/registry", params={"task": "text-to-speech"}, headers=tts.auth_header)
            if r2.status_code == 200:
                d2 = r2.json()
                verfuegbar = [
                    m["id"] for m in (d2.get("data") if isinstance(d2, dict) else d2) or []
                    if isinstance(m, dict) and m.get("id")
                ]
        except httpx.HTTPError:
            pass
    sortiert = lambda liste: sorted(liste, key=lambda k: (not _deutsch(k), k))  # noqa: E731
    return {
        "installiert": sortiert(installiert),
        "verfuegbar": sortiert([m for m in verfuegbar if m not in installiert]),
        "installationen": dict(INSTALLATIONEN),
    }


def installieren(tts: TTSConfig, kennung: str) -> None:
    """Lädt ein Modell im Dienst — im Hintergrund, der Download dauert."""
    if INSTALLATIONEN.get(kennung) == "laeuft":
        return
    INSTALLATIONEN[kennung] = "laeuft"

    async def _arbeit() -> None:
        try:
            async with http_client(timeout=1800) as client:
                r = await client.post(f"{tts.endpoint_url.rstrip('/')}/v1/models/{kennung}", headers=tts.auth_header)
                if r.status_code >= 400:
                    raise RuntimeError(f"{r.status_code}: {r.text[:200]}")
            INSTALLATIONEN[kennung] = "fertig"
        except Exception as exc:  # noqa: BLE001
            INSTALLATIONEN[kennung] = f"fehler: {type(exc).__name__}: {exc}"[:300]

    aufgabe = asyncio.create_task(_arbeit())
    HINTERGRUND.add(aufgabe)
    aufgabe.add_done_callback(HINTERGRUND.discard)


async def probe(tts: TTSConfig, sprecher: str) -> bytes:
    text = (
        "Guten Tag. Ich bin die Moderatorin dieser Vorbereitung."
        if sprecher == "moderatorin"
        else "Guten Tag. Ich kenne den Bestand und erzähle, was vor dem Gespräch zählt."
    )
    async with http_client() as client:
        return mp3_zusammenfuegen([await sprechen_einzeln(client, tts, sprecher, text)])
