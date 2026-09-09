"""Firmen und Kontakte aus öffentlichen Quellen anreichern.

Drei Quellen, in dieser Reihenfolge:

1. **Die Website der Firma.** Impressum, Kontakt- und Team-Seiten tragen
   Anschrift, Telefon, Ansprechpartner — und sind die einzige Quelle, die
   ohne Einrichtung geht. Ein Abruf dort verrät nur der Firma selbst,
   dass sich jemand für sie interessiert.
2. **Ein Suchdienst** (SearXNG auf der Box oder Brave Search), wenn unter
   Einstellungen einer steht. Er findet die Website, wenn keine bekannt
   ist, und liefert die Treffer für LinkedIn-Seiten.
3. **LinkedIn — über die Suchtreffer, nicht über LinkedIn selbst.**
   LinkedIn lässt keinen Abruf ohne Anmeldung zu und verbietet ihn in
   den Nutzungsbedingungen. Was Suchmaschinen von öffentlichen Profilen
   zeigen (Adresse, Titelzeile, Kurztext), reicht für Position,
   Profiladresse, Branche und Größe — und ist der Weg, der sich vor einem
   Kunden erklären lässt.

Das Modell liest, was gefunden wurde, und ordnet es Feldern zu. Es
erfindet nichts: Jeder Wert nennt seine Quelle, und Kontaktdaten müssen
wörtlich in der Quelle stehen, sonst fallen sie weg. Was am Datensatz
schon steht, wird nie überschrieben — höchstens zum Vorschlag.
"""

from __future__ import annotations

import asyncio
import html
import logging
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any
from urllib.parse import urljoin, urlparse
from uuid import UUID

import asyncpg
import httpx
import orjson

from app import audit, tresor
from app.llm import LLMConfig, LLMNichtEingerichtet, chat, json_aus_antwort, load_llm_config

if TYPE_CHECKING:
    from app.auth import CurrentUser

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Einrichtung
# ---------------------------------------------------------------------------

ZEITLIMIT_S = 12.0
SEITE_MAX_BYTES = 600_000
TEXT_MAX_ZEICHEN = 6_000
KENNUNG = "beacon/0.1 (+https://aimighty.de)"

# Welche Felder ein Lauf je Datensatz füllen darf. Was nicht hier steht,
# erreicht die Datenbank nicht — egal, was das Modell zurückgibt.
FIRMEN_FELDER = [
    "website", "linkedin_url", "industry", "employee_count",
    "street", "postal_code", "city", "country", "phone", "description",
]
KONTAKT_FELDER = ["job_title", "email", "phone", "mobile", "linkedin_url"]

# Felder, die nur mit wörtlichem Beleg in der Quelle übernommen werden.
# Eine erfundene Telefonnummer ist schlimmer als keine.
WOERTLICH = {
    "email", "phone", "mobile", "linkedin_url", "website",
    "postal_code", "street", "employee_count",
}

# Felder, die auch bei „leere Felder füllen" ein Vorschlag bleiben. Die
# Beschreibung ist der Platz für das, was ein Mensch über die Firma
# schreibt — dort schreibt die KI nur nach Freigabe.
NIE_VON_SELBST = {"description"}

FIRMEN_PFADE = ["/impressum", "/imprint", "/kontakt", "/contact", "/ueber-uns", "/about", "/about-us"]
KONTAKT_PFADE = [
    "/team", "/ueber-uns", "/about", "/about-us", "/kontakt", "/contact",
    "/ansprechpartner", "/management", "/geschaeftsfuehrung", "/impressum",
]
PFAD_WOERTER = ("impressum", "imprint", "kontakt", "contact", "team", "ueber", "about", "ansprechpartner", "management")


class SucheProblem(RuntimeError):  # noqa: N818
    """Der Suchdienst kann gerade nicht helfen — aus welchem Grund, sagt die Unterklasse."""


class SucheNichtEingerichtet(SucheProblem):
    """Kein Suchdienst hinterlegt — die Anreicherung kennt dann nur die Website."""


class SucheGestoert(SucheProblem):
    """Der Dienst antwortet, aber die Suchmaschinen dahinter sind gesperrt.

    SearXNG fragt Google, Bing, DuckDuckGo ohne Schlüssel — und die sperren
    einen Selbstbetreiber nach wenigen Anfragen für Stunden. Das Ergebnis
    ist dann leer, aber nicht, weil es nichts gäbe. Das muss die
    Oberfläche unterscheiden können, sonst heißt es „nichts gefunden“.
    """


# Länder, für die eine Region gesetzt werden darf. Zwei Buchstaben, und
# jeder Dienst versteht sie auf seine Weise: Brave als `country`, SearXNG
# über die Sprache `de-DE`, Tavily über den ausgeschriebenen Ländernamen.
REGIONEN = {"DE": "de-DE", "AT": "de-AT", "CH": "de-CH", "NL": "nl-NL", "FR": "fr-FR", "GB": "en-GB", "US": "en-US"}

# Tavily nimmt kein Kürzel, sondern das Land als Wort. Ohne diese Tabelle
# würde die Region stillschweigend ignoriert — und „Baustoffhandel" läge
# wieder in Fürth statt in Tecklenburg.
TAVILY_LAENDER = {
    "DE": "germany", "AT": "austria", "CH": "switzerland",
    "NL": "netherlands", "FR": "france",
    "GB": "united kingdom", "US": "united states",
}


@dataclass(frozen=True)
class Suchdienst:
    endpoint_url: str
    api_key: str
    region: str = "DE"  # Länderkürzel oder leer für „keine Vorgabe“

    @property
    def eingerichtet(self) -> bool:
        return bool(self.endpoint_url.strip())

    @property
    def art(self) -> str:
        """Welcher Dienst am anderen Ende hängt — am Namen erkannt.

        Es gibt kein Auswahlfeld dafür. Die Adresse sagt es eindeutig,
        und ein Feld mehr wäre ein Feld, das falsch stehen kann.
        SearXNG ist der Rest: Es läuft auf der eigenen Box unter einem
        Namen, den niemand vorhersagen kann.
        """
        host = urlparse(self.endpoint_url).hostname or ""
        if host.endswith("search.brave.com"):
            return "brave"
        if host.endswith("tavily.com"):
            return "tavily"
        return "searxng"


@dataclass(frozen=True)
class Einrichtung:
    suche: Suchdienst
    automatisch: bool
    uebernahme: str  # 'leere_felder' | 'vorschlag'


async def load_einrichtung(conn: asyncpg.Connection, org_id: UUID) -> Einrichtung:
    row = await conn.fetchrow(
        "select suche_endpoint_url, suche_api_key, suche_region, anreicherung_automatisch, anreicherung_uebernahme "
        "from public.org_settings where org_id = $1",
        org_id,
    )
    return Einrichtung(
        suche=Suchdienst(
            endpoint_url=((row["suche_endpoint_url"] if row else None) or "").strip(),
            api_key=(tresor.entschluesseln(row["suche_api_key"] if row else None) or "").strip(),
            region=((row["suche_region"] if row else None) or "").strip().upper(),
        ),
        automatisch=bool(row["anreicherung_automatisch"]) if row else True,
        uebernahme=(row["anreicherung_uebernahme"] if row else None) or "leere_felder",
    )


def http_client() -> httpx.AsyncClient:
    """Ein Klient je Lauf. Tests tauschen diese Funktion aus."""
    return httpx.AsyncClient(
        timeout=ZEITLIMIT_S,
        follow_redirects=True,
        headers={"User-Agent": KENNUNG, "Accept": "text/html,application/json;q=0.9,*/*;q=0.5"},
    )


# ---------------------------------------------------------------------------
# Quellen
# ---------------------------------------------------------------------------


@dataclass
class Quelle:
    url: str
    titel: str
    text: str
    bytes: int
    art: str = "seite"  # 'seite' | 'suche'
    anfrage: str | None = None  # bei 'suche': was den Dienst verlassen hat
    # Adressen, die im HTML der Seite verlinkt sind, aber nicht im Text
    # stehen — das LinkedIn-Symbol im Fuß hat keinen Text, nur ein href.
    links: list[str] = field(default_factory=list)

    def als_json(self) -> dict[str, Any]:
        eintrag: dict[str, Any] = {"url": self.url, "titel": self.titel, "bytes": self.bytes, "art": self.art}
        if self.anfrage:
            eintrag["anfrage"] = self.anfrage
        return eintrag


_SCRIPT = re.compile(r"<(script|style|noscript|svg|head)\b.*?</\1>", re.S | re.I)
_TAG = re.compile(r"<[^>]+>")
_TITEL = re.compile(r"<title[^>]*>(.*?)</title>", re.S | re.I)
_HREF = re.compile(r"href=[\"']([^\"'#?]+)", re.I)
_LEER = re.compile(r"[ \t\r\f\v]+")
_LINKEDIN = re.compile(r"https?://(?:[a-z]{2,3}\.)?linkedin\.com/(?:company|in)/[A-Za-z0-9_\-%.]+", re.I)
_ZEILEN = re.compile(r"\n\s*\n+")


def text_aus_html(roh: str) -> tuple[str, str]:
    """Gibt (Titel, lesbarer Text) zurück. Kein Parser — Impressumsseiten sind simpel."""
    m = _TITEL.search(roh)
    titel = html.unescape(_TAG.sub("", m.group(1))).strip() if m else ""
    ohne = _SCRIPT.sub(" ", roh)
    ohne = re.sub(r"<br\s*/?>|</(p|div|li|tr|h[1-6]|section|article)>", "\n", ohne, flags=re.I)
    text = html.unescape(_TAG.sub(" ", ohne))
    text = _LEER.sub(" ", text)
    text = "\n".join(zeile.strip() for zeile in text.splitlines())
    text = _ZEILEN.sub("\n", text).strip()
    return titel[:200], text[:TEXT_MAX_ZEICHEN]


def links_aus_html(roh: str, basis: str) -> list[str]:
    """Interne Links, deren Pfad nach Impressum, Kontakt oder Team aussieht."""
    host = urlparse(basis).hostname
    gefunden: list[str] = []
    for href in _HREF.findall(roh):
        voll = urljoin(basis, href.strip())
        p = urlparse(voll)
        if p.hostname != host or p.scheme not in ("http", "https"):
            continue
        pfad = p.path.lower()
        if any(w in pfad for w in PFAD_WOERTER) and voll not in gefunden:
            gefunden.append(voll.rstrip("/"))
    return gefunden


async def seite_holen(client: httpx.AsyncClient, url: str) -> tuple[Quelle | None, str]:
    """Holt eine Seite. Gibt (Quelle, Roh-HTML) zurück, bei Fehlschlag (None, '')."""
    try:
        antwort = await client.get(url)
    except httpx.HTTPError as exc:
        log.info("Anreicherung: %s nicht erreichbar (%s)", url, exc)
        return None, ""
    if antwort.status_code != 200:
        return None, ""
    typ = antwort.headers.get("content-type", "")
    if "html" not in typ and "text/plain" not in typ:
        return None, ""
    roh = antwort.content[:SEITE_MAX_BYTES]
    try:
        seite = roh.decode(antwort.encoding or "utf-8", errors="replace")
    except LookupError:
        seite = roh.decode("utf-8", errors="replace")
    titel, text = text_aus_html(seite)
    if len(text) < 80:
        return None, ""
    links = sorted({m.group(0).rstrip("/") for m in _LINKEDIN.finditer(seite)})
    return Quelle(url=str(antwort.url), titel=titel or url, text=text, bytes=len(roh), links=links), seite


async def suchen(client: httpx.AsyncClient, suche: Suchdienst, anfrage: str, *, anzahl: int = 5) -> list[Quelle]:
    """Fragt den Suchdienst und gibt die Treffer als Quellen zurück.

    Jeder Treffer ist eine eigene Quelle: Titel und Kurztext, so wie die
    Suchmaschine sie zeigt. Mehr als das braucht die Anreicherung nicht —
    und mehr als das holt sie von LinkedIn auch nicht.

    Die Region geht mit, wenn eine gesetzt ist: „Baustoffhandel“ ohne
    Land liefert Fürth, wenn man Tecklenburg meint.
    """
    if not suche.eingerichtet:
        raise SucheNichtEingerichtet("Kein Suchdienst hinterlegt.")

    region = suche.region if suche.region in REGIONEN else ""
    if suche.art == "brave":
        params: dict[str, Any] = {"q": anfrage, "count": anzahl}
        if region:
            params["country"] = region
            params["search_lang"] = REGIONEN[region].split("-")[0]
        antwort = await client.get(
            suche.endpoint_url,
            params=params,
            headers={"X-Subscription-Token": suche.api_key, "Accept": "application/json"},
        )
        antwort.raise_for_status()
        treffer = (antwort.json().get("web") or {}).get("results") or []
        rohe = [(t.get("url"), t.get("title"), t.get("description")) for t in treffer]
    elif suche.art == "tavily":
        # Der einzige der drei, der POST spricht und den Schlüssel als
        # Bearer nimmt. `search_depth` bleibt auf der Vorgabe „basic":
        # Die Anreicherung will Titel und Kurztext, nicht den ganzen
        # Seiteninhalt — und „advanced" kostet das Doppelte je Anfrage.
        koerper: dict[str, Any] = {"query": anfrage, "max_results": anzahl, "topic": "general"}
        if region:
            koerper["country"] = TAVILY_LAENDER[region]
            koerper["language"] = REGIONEN[region].split("-")[0]
        antwort = await client.post(
            suche.endpoint_url,
            json=koerper,
            headers={"Authorization": f"Bearer {suche.api_key}", "Accept": "application/json"},
        )
        antwort.raise_for_status()
        treffer = antwort.json().get("results") or []
        rohe = [(t.get("url"), t.get("title"), t.get("content")) for t in treffer]
    else:
        basis = suche.endpoint_url.rstrip("/")
        url = basis if basis.endswith("/search") else basis + "/search"
        kopf = {"Accept": "application/json"}
        if suche.api_key:
            kopf["Authorization"] = f"Bearer {suche.api_key}"
        params = {"q": anfrage, "format": "json"}
        if region:
            params["language"] = REGIONEN[region]
        antwort = await client.get(url, params=params, headers=kopf)
        antwort.raise_for_status()
        daten = antwort.json()
        treffer = daten.get("results") or []
        if not treffer:
            gesperrt = [
                str(e[0]) for e in (daten.get("unresponsive_engines") or [])
                if isinstance(e, list | tuple) and e
            ]
            if gesperrt:
                raise SucheGestoert(
                    "Der Suchdienst ist gerade gesperrt — "
                    + ", ".join(sorted(set(gesperrt)))
                    + " lassen ihn nicht mehr suchen. Das gibt sich meist nach einigen Stunden."
                )
        rohe = [(t.get("url"), t.get("title"), t.get("content")) for t in treffer]

    quellen: list[Quelle] = []
    for url, titel, text in rohe[:anzahl]:
        if not url:
            continue
        inhalt = "\n".join(t for t in (titel, text) if t).strip()
        quellen.append(
            Quelle(url=str(url), titel=str(titel or url)[:200], text=inhalt[:1500], bytes=len(inhalt), art="suche", anfrage=anfrage)
        )
    return quellen


# ---------------------------------------------------------------------------
# Belege
# ---------------------------------------------------------------------------


def _ziffern(s: str) -> str:
    return re.sub(r"\D", "", s)


def _telefonformen(wert: str) -> list[str]:
    """Dieselbe Nummer in den Schreibweisen, die auf Webseiten vorkommen.

    „+49 (0)40 123 45-67" und „040 1234567" sind eine Nummer. Die Ziffern
    allein sagen das nicht — die Landesvorwahl und die eingeklammerte
    Null müssen austauschbar sein.
    """
    z = _ziffern(wert.replace("(0)", ""))
    formen = {z}
    if z.startswith("00"):
        z = z[2:]
        formen.add(z)
    if z.startswith("49"):
        formen.add("0" + z[2:])
    elif z.startswith("0"):
        formen.add("49" + z[1:])
    return [f for f in formen if len(f) >= 6]


def _url_kern(s: str) -> str:
    s = s.strip().lower()
    s = re.sub(r"^https?://", "", s)
    s = re.sub(r"^www\.", "", s)
    return s.rstrip("/")


def ist_belegt(feld: str, wert: Any, quelle: Quelle) -> bool:
    """Steht der Wert wörtlich in der Quelle?"""
    text = quelle.text
    if feld in ("phone", "mobile"):
        im_text = _ziffern(text.replace("(0)", ""))
        return any(form in im_text for form in _telefonformen(str(wert)))
    if feld == "email":
        return str(wert).lower() in text.lower()
    if feld in ("linkedin_url", "website"):
        kern = _url_kern(str(wert))
        if not kern:
            return False
        if kern in _url_kern(quelle.url) or kern in text.lower().replace("www.", ""):
            return True
        return any(kern == _url_kern(link) for link in quelle.links)
    if feld == "employee_count":
        return str(int(wert)) in text
    return str(wert).casefold() in text.casefold()


def _normalisiert(feld: str, wert: Any) -> Any:
    """Bringt einen Wert des Modells in die Form der Spalte — oder wirft ihn weg."""
    if wert is None:
        return None
    if feld == "employee_count":
        z = _ziffern(str(wert))
        return int(z) if z and int(z) > 0 else None
    s = str(wert).strip()
    if not s or s.lower() in ("null", "none", "unbekannt", "-", "k. a.", "k.a."):
        return None
    if feld == "website":
        if not re.match(r"^https?://", s, re.I):
            s = "https://" + s
        return s.rstrip("/")
    if feld == "linkedin_url":
        if "linkedin.com/" not in s.lower():
            return None
        if not re.match(r"^https?://", s, re.I):
            s = "https://" + s
        return s.rstrip("/")
    if feld == "email":
        return s.lower() if re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", s) else None
    if feld == "country":
        s = s.upper()
        return s if re.match(r"^[A-Z]{2}$", s) else None
    if feld == "description":
        return s[:600]
    return s[:200]


def _gleich(a: Any, b: Any) -> bool:
    if a is None or b is None:
        return a is b
    if isinstance(a, int) or isinstance(b, int):
        return str(a) == str(b)
    return str(a).strip().casefold() == str(b).strip().casefold()


# ---------------------------------------------------------------------------
# Das Modell
# ---------------------------------------------------------------------------

SYSTEM = (
    "Du liest Texte von Webseiten und Suchtreffern und ordnest Fakten Feldern zu. "
    "Du erfindest nichts und ergänzt nichts aus eigenem Wissen: Was nicht in den "
    "Quellen steht, lässt du weg. Antworte ausschließlich als JSON-Objekt."
)


def _quellenblock(quellen: list[Quelle]) -> str:
    teile = []
    for i, q in enumerate(quellen, start=1):
        teile.append(f"[{i}] {q.url}\n{q.titel}\n{q.text}")
    return "\n\n".join(teile)


async def _extrahieren(cfg: LLMConfig, frage: str) -> dict[str, Any]:
    # Reichlich Platz: Ein Modell, das vor der Antwort nachdenkt, rechnet
    # das Nachdenken auf dasselbe Budget. Mit 1.800 Token kam auf der Box
    # nur die Überlegung an und keine einzige Klammer der Antwort.
    antwort = await chat(cfg, SYSTEM, frage, temperature=0.0, max_tokens=6000)
    if not antwort.strip():
        raise ValueError(
            "leere Antwort — ein nachdenkendes Modell hat sein Budget vermutlich vor der Antwort verbraucht"
        )
    roh = json_aus_antwort(antwort)
    felder = roh.get("felder") if isinstance(roh, dict) else None
    return felder if isinstance(felder, dict) else {}


def _vorschlag_bauen(
    roh: dict[str, Any],
    quellen: list[Quelle],
    erlaubt: list[str],
    aktuell: dict[str, Any],
    *,
    direkt: dict[str, tuple[Any, Quelle]] | None = None,
) -> dict[str, dict[str, Any]]:
    """Aus der Modellantwort wird ein geprüfter Vorschlag.

    `direkt` sind Werte, die ohne Modell feststehen — etwa eine
    LinkedIn-Adresse aus der Trefferliste. Sie gehen vor.
    """
    vorschlag: dict[str, dict[str, Any]] = {}

    for feld, (wert, quelle) in (direkt or {}).items():
        wert = _normalisiert(feld, wert)
        if wert is None:
            continue
        lage = _lage(aktuell.get(feld), wert)
        if lage:
            vorschlag[feld] = {"wert": wert, "quelle": quelle.url, "belegt": True, "lage": lage}

    for feld in erlaubt:
        if feld in vorschlag:
            continue
        eintrag = roh.get(feld)
        if not isinstance(eintrag, dict):
            continue
        wert = _normalisiert(feld, eintrag.get("wert"))
        if wert is None:
            continue
        nummer = eintrag.get("quelle")
        try:
            quelle = quellen[int(nummer) - 1]
        except (TypeError, ValueError, IndexError):
            # Ohne Quelle kein Wert. Das ist die Regel, nicht die Ausnahme.
            continue
        belegt = ist_belegt(feld, wert, quelle)
        if feld in WOERTLICH and not belegt:
            # Vielleicht steht es in einer anderen der gelesenen Quellen.
            andere = next((q for q in quellen if ist_belegt(feld, wert, q)), None)
            if andere is None:
                continue
            quelle, belegt = andere, True
        lage = _lage(aktuell.get(feld), wert)
        if lage:
            vorschlag[feld] = {"wert": wert, "quelle": quelle.url, "belegt": belegt, "lage": lage}

    return vorschlag


def _lage(alt: Any, neu: Any) -> str | None:
    if alt is None or (isinstance(alt, str) and not alt.strip()):
        return "neu"
    return None if _gleich(alt, neu) else "abweichend"


# ---------------------------------------------------------------------------
# Läufe
# ---------------------------------------------------------------------------


@dataclass
class Ergebnis:
    quellen: list[Quelle] = field(default_factory=list)
    vorschlag: dict[str, dict[str, Any]] = field(default_factory=dict)
    hinweise: list[str] = field(default_factory=list)
    # Ein Fehler des Modells. Die Quellen bleiben trotzdem im Ergebnis —
    # was gelesen wurde, wurde gelesen, und das gehört in den Nachweis.
    fehler: str | None = None


async def _zuordnen(erg: Ergebnis, cfg: LLMConfig, frage: str) -> dict[str, Any]:
    try:
        return await _extrahieren(cfg, frage)
    except ValueError as exc:
        erg.fehler = f"Das Modell hat kein verwertbares Ergebnis geliefert: {exc}"
        return {}


def _website_von(firma: dict[str, Any]) -> str | None:
    if firma.get("website"):
        return _normalisiert("website", firma["website"])
    if firma.get("domain"):
        return _normalisiert("website", firma["domain"])
    return None


async def _seiten_sammeln(
    client: httpx.AsyncClient, basis: str, pfade: list[str], *, hoechstens: int, filter_wort: str | None = None
) -> list[Quelle]:
    """Startseite plus die Unterseiten, die etwas hergeben."""
    start, roh = await seite_holen(client, basis)
    quellen: list[Quelle] = [start] if start else []
    kandidaten = [basis.rstrip("/") + p for p in pfade]
    for link in links_aus_html(roh, basis):
        if link not in kandidaten:
            kandidaten.append(link)
    gesehen = {basis.rstrip("/")}
    offen = [k for k in kandidaten if k not in gesehen]
    ergebnisse = await asyncio.gather(*(seite_holen(client, k) for k in offen[:12]))
    for quelle, _ in ergebnisse:
        if quelle is None or any(q.url == quelle.url for q in quellen):
            continue
        if filter_wort and filter_wort.casefold() not in quelle.text.casefold():
            continue
        quellen.append(quelle)
        if len(quellen) >= hoechstens:
            break
    return quellen


def _linkedin_in(quellen: list[Quelle], muster: str) -> tuple[str, Quelle] | None:
    regex = re.compile(r"https?://(?:[a-z]{2,3}\.)?linkedin\.com/" + muster + r"[A-Za-z0-9_\-%]+", re.I)
    for q in quellen:
        if q.art == "suche" and regex.match(q.url):
            return q.url.rstrip("/"), q
    for q in quellen:
        m = regex.search(q.text)
        if m:
            return m.group(0).rstrip("/"), q
        for link in q.links:
            if regex.match(link):
                return link, q
    return None


async def firma_anreichern(
    client: httpx.AsyncClient, cfg: LLMConfig, einrichtung: Einrichtung, firma: dict[str, Any]
) -> Ergebnis:
    erg = Ergebnis()
    name = str(firma.get("name") or "").strip()
    website = _website_von(firma)
    direkt: dict[str, tuple[Any, Quelle]] = {}

    # Ohne Website erst suchen — ohne Suchdienst ist dann Schluss.
    if not website:
        if not einrichtung.suche.eingerichtet:
            erg.hinweise.append(
                "Weder Website noch Domain bekannt, und kein Suchdienst hinterlegt — nichts zu lesen."
            )
            return erg
        try:
            treffer = await suchen(client, einrichtung.suche, f'"{name}" {firma.get("city") or ""}'.strip())
        except (httpx.HTTPError, SucheProblem) as exc:
            erg.hinweise.append(f"Suchdienst nicht erreichbar: {exc}")
            treffer = []
        for t in treffer:
            host = (urlparse(t.url).hostname or "").lower()
            if any(s in host for s in ("linkedin.", "xing.", "facebook.", "wikipedia.", "northdata", "google.")):
                continue
            website = _normalisiert("website", f"{urlparse(t.url).scheme}://{host}")
            direkt["website"] = (website, t)
            break
        erg.quellen.extend(treffer)
        if not website:
            erg.hinweise.append("Kein Suchtreffer sah nach der Website der Firma aus.")

    if website:
        seiten = await _seiten_sammeln(client, website, FIRMEN_PFADE, hoechstens=5)
        if not seiten:
            erg.hinweise.append(f"{website} war nicht lesbar.")
        erg.quellen.extend(seiten)

    if einrichtung.suche.eingerichtet:
        try:
            erg.quellen.extend(await suchen(client, einrichtung.suche, f'"{name}" site:linkedin.com/company', anzahl=3))
        except (httpx.HTTPError, SucheProblem) as exc:
            erg.hinweise.append(f"Suchdienst nicht erreichbar: {exc}")

    gefunden = _linkedin_in(erg.quellen, "company/")
    if gefunden:
        direkt["linkedin_url"] = gefunden

    if not erg.quellen:
        return erg

    frage = (
        f"Firma: {name}\n"
        f"Bekannt: Ort {firma.get('city') or '—'}, Website {website or '—'}\n\n"
        "Ordne den Quellen unten Werte für diese Felder zu, soweit sie dort stehen:\n"
        "  website (Adresse der eigenen Website), linkedin_url (LinkedIn-Unternehmensseite),\n"
        "  industry (Branche, zwei bis fünf Wörter), employee_count (Zahl der Beschäftigten),\n"
        "  street (Straße und Hausnummer), postal_code, city, country (ISO-Kürzel wie DE),\n"
        "  phone (Zentrale), description (zwei bis drei Sätze, was die Firma tut).\n\n"
        'Antworte als {"felder": {"<feld>": {"wert": ..., "quelle": <Nummer der Quelle>}}}.\n'
        "Lass jedes Feld weg, das in keiner Quelle steht. Kontaktdaten wörtlich abschreiben.\n\n"
        f"{_quellenblock(erg.quellen)}"
    )
    roh = await _zuordnen(erg, cfg, frage)
    erg.vorschlag = _vorschlag_bauen(roh, erg.quellen, FIRMEN_FELDER, firma, direkt=direkt)
    return erg


async def kontakt_anreichern(
    client: httpx.AsyncClient,
    cfg: LLMConfig,
    einrichtung: Einrichtung,
    kontakt: dict[str, Any],
    firma: dict[str, Any] | None,
) -> Ergebnis:
    erg = Ergebnis()
    vorname = str(kontakt.get("first_name") or "").strip()
    nachname = str(kontakt.get("last_name") or "").strip()
    name = f"{vorname} {nachname}".strip()
    if not nachname:
        erg.hinweise.append("Ohne Nachnamen lässt sich niemand finden.")
        return erg
    firmenname = str((firma or {}).get("name") or "").strip()
    website = _website_von(firma) if firma else None
    direkt: dict[str, tuple[Any, Quelle]] = {}

    if website:
        erg.quellen.extend(
            await _seiten_sammeln(client, website, KONTAKT_PFADE, hoechstens=4, filter_wort=nachname)
        )

    if einrichtung.suche.eingerichtet:
        anfragen = [f'"{name}" "{firmenname}" site:linkedin.com/in' if firmenname else f'"{name}" site:linkedin.com/in']
        if firmenname:
            anfragen.append(f'"{name}" "{firmenname}"')
        for anfrage in anfragen:
            try:
                erg.quellen.extend(await suchen(client, einrichtung.suche, anfrage, anzahl=4))
            except (httpx.HTTPError, SucheProblem) as exc:
                erg.hinweise.append(f"Suchdienst nicht erreichbar: {exc}")
                break
    elif not website:
        erg.hinweise.append("Die Firma hat keine Website, und es ist kein Suchdienst hinterlegt.")

    # Nur Treffer, in denen die Person auch vorkommt — die Suche liefert
    # sonst Namensvettern.
    erg.quellen = [q for q in erg.quellen if nachname.casefold() in (q.text + q.titel).casefold()]

    gefunden = _linkedin_in(erg.quellen, "in/")
    if gefunden:
        direkt["linkedin_url"] = gefunden

    if not erg.quellen:
        erg.hinweise.append("Keine Quelle nennt diese Person.")
        return erg

    frage = (
        f"Person: {name}\nFirma: {firmenname or '—'}\n\n"
        "Ordne den Quellen unten Werte für diese Felder zu, soweit sie dort stehen:\n"
        "  job_title (Position bei dieser Firma), email, phone (Festnetz), mobile,\n"
        "  linkedin_url (öffentliches LinkedIn-Profil dieser Person).\n\n"
        'Antworte als {"felder": {"<feld>": {"wert": ..., "quelle": <Nummer der Quelle>}}}.\n'
        "Nur Angaben zu genau dieser Person bei genau dieser Firma. Lass jedes Feld weg, das in "
        "keiner Quelle steht. E-Mail und Telefon wörtlich abschreiben.\n\n"
        f"{_quellenblock(erg.quellen)}"
    )
    roh = await _zuordnen(erg, cfg, frage)
    erg.vorschlag = _vorschlag_bauen(roh, erg.quellen, KONTAKT_FELDER, kontakt, direkt=direkt)
    return erg


# ---------------------------------------------------------------------------
# Ablage und Übernahme
# ---------------------------------------------------------------------------

SPALTEN = {"companies": FIRMEN_FELDER, "contacts": KONTAKT_FELDER}


async def _datensatz(conn: asyncpg.Connection, entity: str, entity_id: UUID) -> dict[str, Any] | None:
    row = await conn.fetchrow(
        f"select * from public.{entity} where id = $1 and deleted_at is null", entity_id
    )
    return dict(row) if row else None


async def _firma_des_kontakts(conn: asyncpg.Connection, kontakt: dict[str, Any]) -> dict[str, Any] | None:
    firma_id = kontakt.get("company_id")
    if not firma_id:
        firma_id = await conn.fetchval(
            "select company_id from public.contact_companies where contact_id = $1 "
            "order by created_at limit 1",
            kontakt["id"],
        )
    return await _datensatz(conn, "companies", firma_id) if firma_id else None


async def anwenden(
    conn: asyncpg.Connection,
    user: CurrentUser,
    entity: str,
    entity_id: UUID,
    werte: dict[str, Any],
    *,
    quellen: int,
) -> dict[str, Any]:
    """Schreibt Werte an den Datensatz — nur erlaubte Spalten, mit Protokoll."""
    werte = {k: v for k, v in werte.items() if k in SPALTEN[entity] and v is not None}
    if not werte:
        return {}
    zuweisungen = ", ".join(f"{k} = ${i + 1}" for i, k in enumerate(werte))
    args: list[Any] = list(werte.values())
    args.append(entity_id)
    await conn.execute(
        f"update public.{entity} set {zuweisungen}, updated_at = now() "
        f"where id = ${len(args)} and deleted_at is null",
        *args,
    )
    await audit.log_fuer(
        conn, user, action="enrich", entity=entity, entity_id=entity_id, diff=werte
    )
    bezug = "company_id" if entity == "companies" else "contact_id"
    felder = ", ".join(werte)
    await conn.execute(
        f"""
        insert into public.activities (org_id, kind, subject, body, {bezug}, payload, created_by)
        values ($1, 'ai', $2, $3, $4, $5::jsonb, $6)
        """,
        user.org_id,
        "Aus öffentlichen Quellen ergänzt",
        f"{len(werte)} Felder aus {quellen} Quellen: {felder}.",
        entity_id,
        orjson.dumps({"quelle": "anreicherung", "felder": werte}).decode(),
        user.user_id,
    )
    return werte


async def lauf(conn: asyncpg.Connection, user: CurrentUser, entity: str, entity_id: UUID) -> dict[str, Any]:
    """Ein vollständiger Lauf: lesen, zuordnen, ablegen, ggf. übernehmen.

    Gibt die Zeile aus `anreicherungen` zurück. Fehler landen dort mit
    Status 'fehler' — außer dem fehlenden Sprachmodell, das der Aufrufer
    als 409 melden soll, weil es keine Störung ist, sondern eine fehlende
    Einrichtung.
    """
    if entity not in SPALTEN:
        raise ValueError(entity)
    datensatz = await _datensatz(conn, entity, entity_id)
    if datensatz is None:
        raise LookupError(entity)

    cfg = await load_llm_config(conn, user.org_id)
    if not cfg.eingerichtet:
        raise LLMNichtEingerichtet(
            "Es ist kein Sprachmodell hinterlegt. Ohne Modell ordnet niemand die Fundstellen den Feldern zu."
        )
    einrichtung = await load_einrichtung(conn, user.org_id)

    zeile_id = await conn.fetchval(
        "insert into public.anreicherungen (org_id, entity, entity_id, created_by, modell) "
        "values ($1, $2, $3, $4, $5) returning id",
        user.org_id, entity, entity_id, user.user_id, cfg.model,
    )

    status = "leer"
    fehler: str | None = None
    erg = Ergebnis()
    try:
        async with http_client() as client:
            if entity == "companies":
                erg = await firma_anreichern(client, cfg, einrichtung, datensatz)
            else:
                firma = await _firma_des_kontakts(conn, datensatz)
                erg = await kontakt_anreichern(client, cfg, einrichtung, datensatz, firma)
    except httpx.HTTPStatusError as exc:
        status, fehler = "fehler", f"Der Endpunkt hat mit {exc.response.status_code} geantwortet."
    except httpx.RequestError as exc:
        status, fehler = "fehler", f"Nicht erreichbar: {exc}"

    if erg.fehler and fehler is None:
        # Die LinkedIn-Adresse aus der Trefferliste braucht kein Modell —
        # die bleibt als Vorschlag, auch wenn das Modell versagt hat.
        status, fehler = ("vorschlag" if erg.vorschlag else "fehler"), erg.fehler

    uebernommen: dict[str, Any] = {}
    if fehler is None:
        if erg.vorschlag:
            status = "vorschlag"
            if einrichtung.uebernahme == "leere_felder":
                von_selbst = {
                    feld: v["wert"]
                    for feld, v in erg.vorschlag.items()
                    if v["lage"] == "neu" and feld not in NIE_VON_SELBST and (v["belegt"] or feld not in WOERTLICH)
                }
                uebernommen = await anwenden(
                    conn, user, entity, entity_id, von_selbst, quellen=len(erg.quellen)
                )
                for feld in uebernommen:
                    erg.vorschlag.pop(feld, None)
                if not erg.vorschlag:
                    status = "uebernommen"
        elif erg.hinweise:
            fehler = " ".join(erg.hinweise)

    await conn.execute(
        """
        update public.anreicherungen
           set status = $1, quellen = $2::jsonb, vorschlag = $3::jsonb, uebernommen = $4::jsonb,
               fehler = $5, updated_at = now()
         where id = $6
        """,
        status,
        orjson.dumps([q.als_json() for q in erg.quellen]).decode(),
        orjson.dumps(erg.vorschlag).decode(),
        orjson.dumps(uebernommen).decode(),
        fehler or (" ".join(erg.hinweise) if erg.hinweise else None),
        zeile_id,
    )
    row = await conn.fetchrow("select * from public.anreicherungen where id = $1", zeile_id)
    return dict(row)


# Laufende Hintergrundläufe — damit ein Test (oder ein sauberer Stopp) auf
# sie warten kann, statt dass sie im Nichts verschwinden.
HINTERGRUND: set[asyncio.Task[Any]] = set()


def im_hintergrund(user: CurrentUser, entity: str, entity_id: UUID) -> None:
    """Startet einen Lauf, ohne die Antwort aufzuhalten.

    Wer eine Firma anlegt, wartet nicht auf drei Webseiten und ein
    Modell. Der Vorschlag steht beim nächsten Blick auf den Datensatz.
    """
    from app.db import acquire_as

    async def _arbeit() -> None:
        try:
            async with acquire_as(user.user_id) as conn:
                einrichtung = await load_einrichtung(conn, user.org_id)
                if not einrichtung.automatisch:
                    return
                cfg = await load_llm_config(conn, user.org_id)
                if not cfg.eingerichtet:
                    return
                await lauf(conn, user, entity, entity_id)
        except Exception:  # noqa: BLE001 — ein Hintergrundlauf darf nichts mitreißen
            log.exception("Anreicherung im Hintergrund fehlgeschlagen (%s %s)", entity, entity_id)

    aufgabe = asyncio.create_task(_arbeit())
    HINTERGRUND.add(aufgabe)
    aufgabe.add_done_callback(HINTERGRUND.discard)


async def hintergrund_abwarten() -> None:
    """Wartet auf alle laufenden Hintergrundläufe. Für Tests und den Stopp."""
    if HINTERGRUND:
        await asyncio.gather(*list(HINTERGRUND), return_exceptions=True)
