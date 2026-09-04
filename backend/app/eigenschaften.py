"""Prüfung eigener Eigenschaften gegen ihre Definition.

Die Datenbank sieht nur JSON. Dass in „Wartungsvertrag bis" ein Datum
steht und in „Serverraum vorhanden" ja oder nein, prüft nur diese Datei —
und zwar beim Schreiben, denn beim Lesen ist es zu spät.
"""

import re
from datetime import date
from typing import Any

import asyncpg

ENTITAETEN = ("companies", "contacts", "deals")
ARTEN = ("text", "number", "date", "bool", "select", "multiselect")


def schluessel_aus(label: str) -> str:
    """Aus „Wartungsvertrag bis" wird „wartungsvertrag_bis".

    Klein, ASCII, Unterstrich. Der Schlüssel steht danach fest — im JSON
    der Datensätze, und dort soll ihn eine spätere Umbenennung der
    Beschriftung nicht mehr erreichen.
    """
    klein = label.strip().lower()
    klein = klein.replace("ä", "ae").replace("ö", "oe").replace("ü", "ue").replace("ß", "ss")
    klein = re.sub(r"[^a-z0-9]+", "_", klein).strip("_")
    return klein or "eigenschaft"


class Ungueltig(ValueError):  # noqa: N818
    """Ein Wert passt nicht zu seiner Definition — mit Nennung des Feldes."""


async def definitionen(conn: asyncpg.Connection, entity: str) -> list[asyncpg.Record]:
    return await conn.fetch(
        "select id, key, label, kind, options from public.property_definitions "
        "where entity = $1 and is_active order by position, label",
        entity,
    )


def pruefen(werte: dict[str, Any], defs: list[asyncpg.Record]) -> dict[str, Any]:
    """Gibt die geprüften Werte zurück oder wirft `Ungueltig`.

    Unbekannte Schlüssel werden abgelehnt, nicht verschluckt: Ein
    Tippfehler im Client landete sonst als stiller Fremdschlüssel im JSON
    und tauchte nirgends mehr auf. `None` löscht den Wert — das ist der
    einzige Weg, eine Eigenschaft wieder leer zu bekommen.
    """
    nach_key = {d["key"]: d for d in defs}
    ergebnis: dict[str, Any] = {}

    for key, wert in werte.items():
        d = nach_key.get(key)
        if d is None:
            raise Ungueltig(f"Unbekannte Eigenschaft „{key}“.")
        if wert is None or wert == "":
            ergebnis[key] = None
            continue

        art = d["kind"]
        label = d["label"]
        try:
            if art == "text":
                ergebnis[key] = str(wert)
            elif art == "number":
                if isinstance(wert, bool):
                    raise ValueError
                ergebnis[key] = float(wert)
            elif art == "date":
                ergebnis[key] = date.fromisoformat(str(wert)).isoformat()
            elif art == "bool":
                if isinstance(wert, bool):
                    ergebnis[key] = wert
                elif str(wert).lower() in ("true", "ja", "1", "yes"):
                    ergebnis[key] = True
                elif str(wert).lower() in ("false", "nein", "0", "no"):
                    ergebnis[key] = False
                else:
                    raise ValueError
            elif art == "select":
                erlaubt = optionswerte(d["options"])
                if str(wert) not in erlaubt:
                    raise Ungueltig(
                        f"„{label}“ erlaubt nur: {', '.join(optionstexte(d['options'])) or 'nichts'}."
                    )
                ergebnis[key] = str(wert)
            elif art == "multiselect":
                ergebnis[key] = _mehrfach(wert, d, label)
            else:
                raise Ungueltig(f"„{label}“ hat einen unbekannten Typ.")
        except Ungueltig:
            raise
        except (TypeError, ValueError):
            erwartet = {"number": "eine Zahl", "date": "ein Datum (JJJJ-MM-TT)",
                        "bool": "ja oder nein"}.get(art, "einen Text")
            raise Ungueltig(f"„{label}“ erwartet {erwartet}.") from None

    return ergebnis


def _mehrfach(wert: Any, d: Any, label: str) -> list[str] | None:
    """Eine Mehrfachauswahl prüfen: Liste, bekannte Werte, feste Reihenfolge.

    Drei Entscheidungen stecken darin:

    - **Ein einzelner Text wird zur einelementigen Liste.** Ein Import
      oder die Erfassung aus einer Signatur liefert selten schon ein
      Array; das hier abzulehnen wäre Formalismus.
    - **Doppelte fallen weg.** Zweimal „ISO 9001“ ist keine Aussage.
    - **Sortiert wird nach der Definition, nicht nach dem Anklicken.**
      Sonst zeigen zwei Datensätze mit derselben Auswahl verschiedene
      Reihenfolgen, und jeder Vergleich zweier Zeilen wird zur Suche.

    Eine leere Auswahl ist kein leeres Array, sondern `None` — dieselbe
    Bedeutung wie bei jedem anderen Feld, und nur so greift „ist leer“.
    """
    erlaubt = optionswerte(d["options"])
    if isinstance(wert, str):
        roh = [wert]
    elif isinstance(wert, (list, tuple)):
        roh = list(wert)
    else:
        raise Ungueltig(f"„{label}“ erwartet eine Liste von Werten.")

    gewaehlt = {str(w) for w in roh if str(w).strip()}
    unbekannt = sorted(gewaehlt - set(erlaubt))
    if unbekannt:
        raise Ungueltig(
            f"„{label}“ kennt {', '.join(chr(8222) + u + chr(8220) for u in unbekannt)} nicht. "
            f"Erlaubt ist: {', '.join(optionstexte(d['options'])) or 'nichts'}."
        )
    geordnet = [o for o in erlaubt if o in gewaehlt]
    return geordnet or None


def optionen(roh: Any) -> list[dict[str, Any]]:
    """Die Optionsliste in einheitlicher Form: `wert`, `text`, `verborgen`.

    Zwei Formen kommen hier an. Die alte war eine Liste von Texten, in
    der Anzeige und Speicherwert dasselbe waren; die neue trennt beide,
    damit sich eine Beschriftung ändern lässt, ohne die Datensätze zu
    entwerten. 0015 stellt den Bestand um — diese Funktion nimmt trotzdem
    weiter beides an, denn eine Migration, die einmal nicht durchlief,
    soll nicht die Anwendung mitnehmen.

    `verborgen` heißt archiviert: nicht mehr wählbar, aber weiterhin
    gültig. Ein Wert, der an dreihundert Firmen steht, verschwindet nicht
    dadurch, dass ihn niemand mehr vergeben soll.
    """
    import json

    if isinstance(roh, str):
        try:
            roh = json.loads(roh)
        except json.JSONDecodeError:
            return []
    if not isinstance(roh, list):
        return []

    fertig: list[dict[str, Any]] = []
    for o in roh:
        if isinstance(o, dict):
            wert = str(o.get("wert") or "").strip()
            if not wert:
                continue
            fertig.append({
                "wert": wert,
                "text": str(o.get("text") or wert),
                "verborgen": bool(o.get("verborgen")),
            })
        elif str(o).strip():
            fertig.append({"wert": str(o), "text": str(o), "verborgen": False})
    return fertig


def optionswerte(roh: Any, *, auch_verborgene: bool = True) -> list[str]:
    """Nur die Speicherwerte — das, wogegen geprüft wird."""
    return [o["wert"] for o in optionen(roh) if auch_verborgene or not o["verborgen"]]


def optionstexte(roh: Any) -> list[str]:
    """Nur die Beschriftungen — das, was in einer Fehlermeldung steht."""
    return [o["text"] for o in optionen(roh)]
