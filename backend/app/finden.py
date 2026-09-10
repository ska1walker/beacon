"""Beschreiben statt tippen — aus „Baustoffhandel im Tecklenburger Land,
der Geschäftsführer heißt vermutlich Sebastian“ wird ein Datensatz.

Die Anreicherung (anreicherung.py) läuft, wenn ein Datensatz da ist. Hier
gibt es noch keinen — nur, was ein Mensch im Kopf hat. Drei Schritte,
jeder für sich beweisbar:

1. **Kandidaten.** Die Beschreibung geht an den Suchdienst; das Modell
   liest die Trefferliste und nennt, welche Firmen gemeint sein könnten —
   mit Website *aus den Treffern*, nie aus dem Kopf. Verzeichnisse (Gelbe
   Seiten, LinkedIn, Northdata) sind Hinweise, keine Kandidaten. Ein
   Mensch wählt.
2. **Firma.** Für die gewählte läuft dieselbe Anreicherung wie für einen
   bestehenden Datensatz: Impressum, Kontaktseite, LinkedIn-Treffer.
3. **Person.** Wer laut Beschreibung gemeint ist — Rolle, Vorname, was
   man eben weiß — wird auf Team- und Impressumsseiten und in
   Suchtreffern gesucht. Ohne Beleg für den Nachnamen keine Person:
   „vermutlich Sebastian“ wird nicht zu einem Kontakt, wenn ihn keine
   Quelle nennt.

Gespeichert wird nichts. Das Ergebnis füllt die Maske, Anlegen drückt
ein Mensch — dieselbe Regel wie beim Hineinwerfen einer Signatur.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

import httpx

from app import anreicherung as an
from app.anreicherung import Einrichtung, Ergebnis, Quelle, SucheProblem, ist_belegt
from app.llm import LLMConfig

# Hosts, die eine Firma beschreiben, aber nicht ihre sind. Sie dürfen im
# Quellenblock stehen — das Modell liest dort Name und Ort — aber nie als
# Website eines Kandidaten zurückkommen.
VERZEICHNISSE = (
    "linkedin.", "xing.", "facebook.", "instagram.", "wikipedia.", "northdata", "google.",
    "gelbeseiten", "dasoertliche", "11880", "yelp.", "kununu", "firmenwissen", "companyhouse",
    "unternehmensregister", "handelsregister", "creditreform", "wlw.de", "branchenbuch",
    "cylex", "golocal", "meinestadt", "bing.", "youtube.", "indeed.", "stepstone.",
)

PERSON_FELDER = ["first_name", "last_name", "job_title", "email", "phone", "mobile", "linkedin_url"]


@dataclass
class Personenfund(Ergebnis):
    # Wer sonst noch bei dieser Firma genannt wird — wenn die beschriebene
    # Person nicht (eindeutig) da ist. „Der Geschäftsführer heißt vermutlich
    # Sebastian“ trifft oft daneben; die drei, die das Impressum nennt,
    # sind dann die bessere Antwort als ein leeres Feld.
    alternativen: list[dict[str, Any]] = field(default_factory=list)

SYSTEM_KANDIDATEN = (
    "Du liest eine Beschreibung, die jemand über eine Firma im Kopf hat, und eine "
    "Liste von Suchtreffern. Du nennst, welche Firmen aus den Treffern gemeint sein "
    "könnten — nur solche, deren eigene Website in den Treffern steht. Du erfindest "
    "keine Firma und keine Adresse. Antworte ausschließlich als JSON-Objekt."
)


@dataclass
class Kandidat:
    name: str
    website: str
    ort: str | None
    grund: str
    quelle: str


@dataclass
class Kandidaten:
    kandidaten: list[Kandidat] = field(default_factory=list)
    # Was die Beschreibung über die gesuchte Person verrät — aus dem Text,
    # nicht aus den Quellen. Der dritte Schritt sucht damit.
    person: dict[str, str] = field(default_factory=dict)
    quellen: list[Quelle] = field(default_factory=list)
    hinweise: list[str] = field(default_factory=list)
    fehler: str | None = None


def _host(url: str) -> str:
    return (urlparse(url).hostname or "").lower()


def ist_verzeichnis(url: str) -> bool:
    host = _host(url)
    return any(v in host for v in VERZEICHNISSE)


def _wurzel(url: str) -> str | None:
    p = urlparse(url if "://" in url else "https://" + url)
    if not p.hostname or p.scheme not in ("http", "https"):
        return None
    return f"{p.scheme}://{p.netloc}"


def domain_aus(website: str) -> str | None:
    host = _host(website if "://" in website else "https://" + website)
    return host.removeprefix("www.") or None


def _text(wert: Any, laenge: int = 200) -> str | None:
    if wert is None:
        return None
    s = str(wert).strip()
    if not s or s.lower() in ("null", "none", "unbekannt", "-", "k. a."):
        return None
    return s[:laenge]


# ---------------------------------------------------------------------------
# 1. Kandidaten
# ---------------------------------------------------------------------------


async def kandidaten(client: httpx.AsyncClient, cfg: LLMConfig, einr: Einrichtung, beschreibung: str) -> Kandidaten:
    erg = Kandidaten()
    beschreibung = " ".join(beschreibung.split())[:300]
    if not einr.suche.eingerichtet:
        raise an.SucheNichtEingerichtet(
            "Ohne Suchdienst findet Beacon keine Firma, die es noch nicht kennt — "
            "unter Einstellungen → KI und Programme einen eintragen."
        )

    # Zwei Anfragen: die Beschreibung, wie sie ist, und dieselbe mit
    # „Impressum“ — das holt die eigenen Seiten der Firmen nach vorn, wo
    # Verzeichnisse sonst die erste Seite füllen.
    for anfrage, anzahl in ((beschreibung, 8), (f"{beschreibung} Impressum", 5)):
        try:
            for q in await an.suchen(client, einr.suche, anfrage, anzahl=anzahl):
                if not any(q.url == v.url for v in erg.quellen):
                    erg.quellen.append(q)
        except an.SucheGestoert:
            raise
        except SucheProblem as exc:
            erg.hinweise.append(str(exc))
            break
        except httpx.HTTPError as exc:
            erg.hinweise.append(f"Suchdienst nicht erreichbar: {exc}")
            break

    if not erg.quellen:
        if not erg.hinweise:
            erg.hinweise.append("Der Suchdienst hat zu dieser Beschreibung nichts gefunden.")
        return erg

    frage = (
        f"Beschreibung: {beschreibung}\n\n"
        "Welche Firmen aus den Quellen unten könnten gemeint sein? Höchstens vier, die "
        "wahrscheinlichste zuerst. Nimm nur Firmen, deren eigene Website als Quelle "
        "dasteht — keine Verzeichnisse, keine LinkedIn-Seiten als Website.\n"
        "Nenne außerdem, was die Beschreibung über eine gesuchte Person sagt — Vorname, "
        "Nachname, Rolle — nur was dasteht, nichts aus den Quellen.\n\n"
        'Antworte als {"kandidaten": [{"name": ..., "website": ..., "ort": ..., '
        '"grund": "ein Halbsatz, warum", "quelle": <Nummer der Quelle>}], '
        '"person": {"vorname": ..., "nachname": ..., "rolle": ...}}.\n'
        "Lass weg, was du nicht weißt.\n\n"
        f"{an._quellenblock(erg.quellen)}"
    )
    try:
        antwort = await an.chat(cfg, SYSTEM_KANDIDATEN, frage, temperature=0.0, max_tokens=6000)
        roh = an.json_aus_antwort(antwort) if antwort.strip() else {}
    except ValueError as exc:
        erg.fehler = f"Das Modell hat kein verwertbares Ergebnis geliefert: {exc}"
        return erg
    if not isinstance(roh, dict):
        roh = {}

    for eintrag in (roh.get("kandidaten") or [])[:6]:
        if not isinstance(eintrag, dict):
            continue
        name = _text(eintrag.get("name"))
        website = _text(eintrag.get("website"))
        if not name or not website:
            continue
        wurzel = _wurzel(website)
        if not wurzel or ist_verzeichnis(wurzel):
            continue
        try:
            quelle = erg.quellen[int(eintrag.get("quelle")) - 1]
        except (TypeError, ValueError, IndexError):
            # Vielleicht steht die Website in einer anderen Quelle.
            quelle = next((q for q in erg.quellen if ist_belegt("website", wurzel, q)), None)  # type: ignore[assignment]
            if quelle is None:
                continue
        if not ist_belegt("website", wurzel, quelle):
            andere = next((q for q in erg.quellen if ist_belegt("website", wurzel, q)), None)
            if andere is None:
                continue
            quelle = andere
        if any(k.website == wurzel for k in erg.kandidaten):
            continue
        erg.kandidaten.append(Kandidat(
            name=name, website=wurzel, ort=_text(eintrag.get("ort"), 100),
            grund=_text(eintrag.get("grund"), 200) or "", quelle=quelle.url,
        ))
        if len(erg.kandidaten) >= 4:
            break

    person = roh.get("person")
    if isinstance(person, dict):
        for schluessel in ("vorname", "nachname", "rolle"):
            wert = _text(person.get(schluessel), 80)
            if wert:
                erg.person[schluessel] = wert

    if not erg.kandidaten:
        erg.hinweise.append("In den Treffern stand keine Firma mit eigener Website. Genauer beschreiben — Ort, Branche, ein Name?")
    return erg


# ---------------------------------------------------------------------------
# 2. Firma
# ---------------------------------------------------------------------------


async def firma(client: httpx.AsyncClient, cfg: LLMConfig, einr: Einrichtung, name: str, website: str) -> Ergebnis:
    """Dieselbe Anreicherung wie am Datensatz — nur dass es ihn noch nicht gibt."""
    wurzel = _wurzel(website)
    erg = await an.firma_anreichern(client, cfg, einr, {"name": name, "website": wurzel})
    # Name und Website kommen vom Kandidaten, nicht aus dem Modell — die
    # stehen fest, sobald ein Mensch gewählt hat.
    erg.vorschlag.setdefault("name", {"wert": name, "quelle": wurzel, "belegt": True, "lage": "neu"})
    if wurzel:
        erg.vorschlag.setdefault("website", {"wert": wurzel, "quelle": wurzel, "belegt": True, "lage": "neu"})
        domain = domain_aus(wurzel)
        if domain:
            erg.vorschlag.setdefault("domain", {"wert": domain, "quelle": wurzel, "belegt": True, "lage": "neu"})
    return erg


# ---------------------------------------------------------------------------
# 3. Person
# ---------------------------------------------------------------------------


async def person(
    client: httpx.AsyncClient,
    cfg: LLMConfig,
    einr: Einrichtung,
    firmenname: str,
    website: str | None,
    hinweis: dict[str, str],
) -> Personenfund:
    """Sucht die beschriebene Person bei dieser Firma.

    `hinweis` trägt, was man weiß: vorname, nachname, rolle — jedes
    einzeln optional. Gefunden ist eine Person erst, wenn eine Quelle
    ihren Nachnamen nennt. Passt niemand, kommen die Personen zurück, die
    die Quellen bei dieser Firma nennen — als Wahl, nicht als Wert.
    """
    erg = Personenfund()
    vorname = (hinweis.get("vorname") or "").strip()
    nachname = (hinweis.get("nachname") or "").strip()
    rolle = (hinweis.get("rolle") or "").strip()
    if not (vorname or nachname or rolle):
        erg.hinweise.append("Ohne Namen oder Rolle lässt sich niemand finden.")
        return erg

    wurzel = _wurzel(website) if website else None
    if wurzel:
        # Gefiltert wird auf den Nachnamen, sonst den Vornamen — die
        # Rolle allein ist kein Filter: „Geschäftsführung“ steht auf jeder
        # Impressumsseite.
        erg.quellen.extend(
            await an._seiten_sammeln(client, wurzel, an.KONTAKT_PFADE, hoechstens=5, filter_wort=nachname or vorname or None)
        )

    if einr.suche.eingerichtet:
        personenteil = " ".join(t for t in (rolle, vorname, nachname) if t)
        anfragen = [f'"{firmenname}" {personenteil}']
        if vorname or nachname:
            anfragen.append(f'"{firmenname}" {vorname} {nachname} site:linkedin.com/in'.replace("  ", " "))
        for anfrage in anfragen:
            try:
                for q in await an.suchen(client, einr.suche, anfrage, anzahl=5):
                    if not any(q.url == v.url for v in erg.quellen):
                        erg.quellen.append(q)
            except SucheProblem as exc:
                erg.hinweise.append(str(exc))
                break
            except httpx.HTTPError as exc:
                erg.hinweise.append(f"Suchdienst nicht erreichbar: {exc}")
                break
    elif not wurzel:
        erg.hinweise.append("Die Firma hat keine Website, und es ist kein Suchdienst hinterlegt.")

    if not erg.quellen:
        erg.hinweise.append("Keine Quelle nennt eine passende Person.")
        return erg

    gesucht = ", ".join(t for t in (
        f"Rolle {rolle}" if rolle else "", f"Vorname {vorname}" if vorname else "", f"Nachname {nachname}" if nachname else ""
    ) if t)
    frage = (
        f"Firma: {firmenname}\nGesucht: {gesucht}\n\n"
        "Finde in den Quellen unten genau die eine Person bei dieser Firma, die dazu passt. "
        "Ordne ihr diese Felder zu, soweit sie dort stehen:\n"
        "  first_name, last_name, job_title (Position bei dieser Firma), email, phone (Festnetz), "
        "mobile, linkedin_url (öffentliches LinkedIn-Profil dieser Person).\n"
        "Nenne außerdem unter \"andere\" bis zu fünf weitere Personen, die die Quellen bei dieser "
        "Firma nennen — Geschäftsführung, Inhaber, Ansprechpartner — je mit first_name, last_name, "
        "job_title und quelle.\n\n"
        'Antworte als {"felder": {"<feld>": {"wert": ..., "quelle": <Nummer>}}, '
        '"andere": [{"first_name": ..., "last_name": ..., "job_title": ..., "quelle": <Nummer>}]}.\n'
        "Passt niemand eindeutig, lass \"felder\" leer. Namen, E-Mail und Telefon wörtlich abschreiben.\n\n"
        f"{an._quellenblock(erg.quellen)}"
    )
    try:
        antwort = await an.chat(cfg, an.SYSTEM, frage, temperature=0.0, max_tokens=6000)
        ganz = an.json_aus_antwort(antwort) if antwort.strip() else {}
    except ValueError as exc:
        erg.fehler = f"Das Modell hat kein verwertbares Ergebnis geliefert: {exc}"
        ganz = {}
    if not isinstance(ganz, dict):
        ganz = {}
    roh = ganz.get("felder") if isinstance(ganz.get("felder"), dict) else {}
    vorschlag = an._vorschlag_bauen(roh, erg.quellen, PERSON_FELDER, {})
    erg.alternativen = _andere_personen(ganz.get("andere"), erg.quellen)

    # Namen wie Kontaktdaten: Nennt die zitierte Quelle ihn nicht, tut es
    # vielleicht eine andere der gelesenen — das Modell verzählt sich bei
    # Nummern, nicht bei Namen.
    for feld in ("first_name", "last_name"):
        v = vorschlag.get(feld)
        if v and not v["belegt"]:
            andere = next((q for q in erg.quellen if ist_belegt(feld, v["wert"], q)), None)
            if andere is not None:
                v["quelle"], v["belegt"] = andere.url, True

    # Der Nachname muss belegt sein — das ist die Grenze zwischen „gefunden“
    # und „ausgedacht“. Der Vorname bleibt nur, wenn ihn dieselbe Welt nennt.
    nn = vorschlag.get("last_name")
    if not nn or not nn["belegt"]:
        erg.hinweise.append(
            "Keine Quelle nennt eine passende Person."
            + (" Genannt werden stattdessen:" if erg.alternativen else "")
        )
        erg.vorschlag = {}
        return erg
    # Wer gefunden wurde, steht nicht noch einmal unter den anderen.
    erg.alternativen = [
        a for a in erg.alternativen
        if a["last_name"].casefold() != str(nn["wert"]).casefold()
        or a.get("first_name", "").casefold() != str(vorschlag.get("first_name", {}).get("wert", "")).casefold()
    ]
    vn = vorschlag.get("first_name")
    if vn and not vn["belegt"]:
        vorschlag.pop("first_name")
    erg.vorschlag = vorschlag
    return erg


# ---------------------------------------------------------------------------
# 4. Personen bei einer Firma — ohne eine bestimmte zu meinen
# ---------------------------------------------------------------------------


async def personen(
    client: httpx.AsyncClient,
    cfg: LLMConfig,
    einr: Einrichtung,
    firmenname: str,
    website: str | None,
    wunsch: str | None = None,
) -> Personenfund:
    """Wer bei dieser Firma genannt wird — Geschäftsführung, Ansprechpartner,
    Team — als Wahl für „als Kontakte anlegen“.

    `wunsch` ist ein Halbsatz wie „Einkauf“ oder „Geschäftsführung“: Er
    lenkt die Suche und die Reihenfolge, schließt aber niemanden aus.
    Gefunden ist jede Person nur mit belegtem Nachnamen; E-Mail und
    Telefon nur, wenn sie wörtlich dastehen.
    """
    erg = Personenfund()
    wurzel = _wurzel(website) if website else None
    if wurzel:
        erg.quellen.extend(await an._seiten_sammeln(client, wurzel, an.KONTAKT_PFADE, hoechstens=6))
    if einr.suche.eingerichtet:
        anfragen = [f'"{firmenname}" {wunsch or "Geschäftsführung Ansprechpartner Team"}', f'"{firmenname}" site:linkedin.com/in']
        for anfrage in anfragen:
            try:
                for q in await an.suchen(client, einr.suche, anfrage, anzahl=5):
                    if not any(q.url == v.url for v in erg.quellen):
                        erg.quellen.append(q)
            except SucheProblem as exc:
                erg.hinweise.append(str(exc))
                break
            except httpx.HTTPError as exc:
                erg.hinweise.append(f"Suchdienst nicht erreichbar: {exc}")
                break
    elif not wurzel:
        erg.hinweise.append("Die Firma hat keine Website, und es ist kein Suchdienst hinterlegt.")
    if not erg.quellen:
        erg.hinweise.append("Keine Quelle nennt Personen bei dieser Firma.")
        return erg

    frage = (
        f"Firma: {firmenname}\n"
        + (f"Gesucht werden bevorzugt: {wunsch}\n" if wunsch else "")
        + "\nAlle Personen, die die Quellen unten bei dieser Firma nennen — Geschäftsführung, "
        "Inhaber, Ansprechpartner, Team — je mit first_name, last_name, job_title und, soweit "
        "wörtlich dort steht, email, phone, mobile, linkedin_url. Die wichtigsten zuerst, "
        "höchstens zehn. Keine Personen anderer Firmen.\n\n"
        'Antworte als {"andere": [{"first_name": ..., "last_name": ..., "job_title": ..., '
        '"email": ..., "phone": ..., "quelle": <Nummer der Quelle>}]}.\n\n'
        f"{an._quellenblock(erg.quellen)}"
    )
    try:
        antwort = await an.chat(cfg, an.SYSTEM, frage, temperature=0.0, max_tokens=6000)
        ganz = an.json_aus_antwort(antwort) if antwort.strip() else {}
    except ValueError as exc:
        erg.fehler = f"Das Modell hat kein verwertbares Ergebnis geliefert: {exc}"
        ganz = {}
    if not isinstance(ganz, dict):
        ganz = {}
    erg.alternativen = _andere_personen(ganz.get("andere"), erg.quellen, hoechstens=10)
    if not erg.alternativen:
        erg.hinweise.append("Keine Quelle nennt Personen bei dieser Firma.")
    return erg


def _andere_personen(roh: Any, quellen: list[Quelle], *, hoechstens: int = 5) -> list[dict[str, Any]]:
    """Die Genannten — nur mit belegtem Nachnamen, ohne Dubletten."""
    ergebnis: list[dict[str, Any]] = []
    for eintrag in (roh or [])[: hoechstens + 4] if isinstance(roh, list) else []:
        if not isinstance(eintrag, dict):
            continue
        nachname = _text(eintrag.get("last_name"), 80)
        if not nachname:
            continue
        vorname = _text(eintrag.get("first_name"), 80) or ""
        try:
            quelle = quellen[int(eintrag.get("quelle")) - 1]
        except (TypeError, ValueError, IndexError):
            quelle = None  # type: ignore[assignment]
        if quelle is None or not ist_belegt("last_name", nachname, quelle):
            quelle = next((q for q in quellen if ist_belegt("last_name", nachname, q)), None)  # type: ignore[assignment]
        if quelle is None:
            continue
        if vorname and not ist_belegt("first_name", vorname, quelle):
            vorname = ""
        if any(a["last_name"].casefold() == nachname.casefold() and a["first_name"].casefold() == vorname.casefold() for a in ergebnis):
            continue
        person: dict[str, Any] = {
            "first_name": vorname, "last_name": nachname,
            "job_title": _text(eintrag.get("job_title"), 120) or "", "quelle": quelle.url,
        }
        # Kontaktdaten nur wörtlich — aus irgendeiner gelesenen Quelle.
        for feld in ("email", "phone", "mobile", "linkedin_url"):
            wert = an._normalisiert(feld, eintrag.get(feld))
            if wert and any(ist_belegt(feld, wert, q) for q in quellen):
                person[feld] = wert
        ergebnis.append(person)
        if len(ergebnis) >= hoechstens:
            break
    return ergebnis
