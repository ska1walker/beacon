#!/usr/bin/env python3
"""Erzeugt olares/templates/configmap-migrations.yaml aus supabase/migrations/.

Warum eingebettet und nicht `.Files.Get`: Der Markt-Linter lehnt Charts ab,
die zur Renderzeit Dateien aus dem Paket lesen. Das SQL muss also im
Template stehen — und damit es nicht auseinanderläuft, wird es erzeugt und
nie von Hand nachgebessert.

    python3 scripts/regen-migrations.py
"""

import pathlib
import sys

WURZEL = pathlib.Path(__file__).resolve().parent.parent
QUELLE = WURZEL / "supabase" / "migrations"
ZIEL = WURZEL / "olares" / "templates" / "configmap-migrations.yaml"

KOPF = """# ============================================================================
# ERZEUGT — nicht von Hand ändern.
#
# Quelle: supabase/migrations/*.sql
# Neu erzeugen: python3 scripts/regen-migrations.py
#
# Das SQL steht hier eingebettet, weil der Markt-Linter `.Files.Get`
# ablehnt. Der Vorlauf-Container des Backends hängt diese ConfigMap unter
# /sql ein und spielt die Dateien in Namensreihenfolge ein.
# ============================================================================
apiVersion: v1
kind: ConfigMap
metadata:
  name: aicrm-migrations
  namespace: {{ .Release.Namespace }}
  labels:
    app: aicrm
data:
"""


def main() -> int:
    dateien = sorted(QUELLE.glob("*.sql"))
    if not dateien:
        print(f"Keine Migrationen in {QUELLE}", file=sys.stderr)
        return 1

    teile = [KOPF]
    for datei in dateien:
        text = datei.read_text()
        # Helm rendert den Inhalt als Go-Template mit. Doppelte geschweifte
        # Klammern in SQL gäbe es bei uns nur versehentlich — aber wenn,
        # dann bricht das Rendern, und zwar erst auf der Box.
        if "{{" in text:
            print(f"FEHLER: {datei.name} enthält '{{{{' — Helm würde das auswerten.", file=sys.stderr)
            return 1
        teile.append(f"  {datei.name}: |\n")
        teile.extend(f"    {zeile}\n" if zeile.strip() else "\n" for zeile in text.splitlines())

    ZIEL.write_text("".join(teile))
    print(f"{ZIEL.relative_to(WURZEL)} erzeugt aus {len(dateien)} Datei(en)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
