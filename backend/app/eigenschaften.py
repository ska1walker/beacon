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
ARTEN = ("text", "number", "date", "bool", "select")


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
                optionen = _optionen(d["options"])
                if str(wert) not in optionen:
                    raise Ungueltig(
                        f"„{label}“ erlaubt nur: {', '.join(optionen) or 'nichts'}."
                    )
                ergebnis[key] = str(wert)
            else:
                raise Ungueltig(f"„{label}“ hat einen unbekannten Typ.")
        except Ungueltig:
            raise
        except (TypeError, ValueError):
            erwartet = {"number": "eine Zahl", "date": "ein Datum (JJJJ-MM-TT)",
                        "bool": "ja oder nein"}.get(art, "einen Text")
            raise Ungueltig(f"„{label}“ erwartet {erwartet}.") from None

    return ergebnis


def _optionen(roh: Any) -> list[str]:
    """asyncpg liefert jsonb als Text; hier kommt beides an."""
    import json

    if isinstance(roh, str):
        try:
            roh = json.loads(roh)
        except json.JSONDecodeError:
            return []
    return [str(o) for o in roh] if isinstance(roh, list) else []
