"""Aus einem Patch-Modell ein UPDATE bauen.

Die Feldnamen kommen aus den Pydantic-Feldern, nicht aus der Anfrage —
ein Client kann hier also keinen eigenen Spaltennamen unterschieben. Was
nicht im Modell steht, erreicht die Datenbank nicht.
"""

import json
from typing import Any

from pydantic import BaseModel

# Spalten, die Postgres nicht selbst aus dem Parameter ableiten kann:
# Enum-Typen brauchen die Umwandlung ausdrücklich.
CASTS: dict[str, str] = {
    "lifecycle_stage": "::public.lifecycle_stage",
    "product": "::public.deal_product",
    "status": "::public.task_status",
}


def build_update(payload: BaseModel) -> tuple[str, list[Any]]:
    """Gibt „spalte = $1, spalte = $2" und die Werte zurück.

    Wirft ValueError, wenn nichts gesetzt ist — ein UPDATE ohne SET wäre
    ein Syntaxfehler, und ein stiller Erfolg wäre die falsche Antwort.
    """
    felder = payload.model_dump(exclude_unset=True)
    if not felder:
        raise ValueError("Keine Änderung übergeben")

    zuweisungen: list[str] = []
    args: list[Any] = []
    for name, wert in felder.items():
        if name == "custom":
            # Zusammenführen statt ersetzen: Wer eine Eigenschaft ändert,
            # schickt nur diese eine — die anderen sollen stehen bleiben.
            # Ein `null` im JSON überschreibt den alten Wert mit null und
            # ist damit der Weg, eine Eigenschaft wieder leer zu bekommen.
            args.append(json.dumps(wert or {}))
            zuweisungen.append(f"custom = custom || ${len(args)}::jsonb")
            continue
        args.append(wert)
        zuweisungen.append(f"{name} = ${len(args)}{CASTS.get(name, '')}")
    return ", ".join(zuweisungen), args
