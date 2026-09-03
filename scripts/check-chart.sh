#!/usr/bin/env bash
# Prüft das Olares-Chart vor jedem Commit und in der CI.
#
# Jede Regel hier steht für einen Fehler, der auf der Box Geld gekostet
# hat — bei Insilo, nicht hier, und genau deshalb steht sie hier.
set -euo pipefail

cd "$(dirname "$0")/.."
FEHLER=0

melde() { echo "  FEHLER: $*"; FEHLER=1; }

echo "→ Versionen im Gleichschritt"
CHART_VERSION=$(grep -E '^version:' olares/Chart.yaml | awk '{print $2}')
CHART_APPVERSION=$(grep -E '^appVersion:' olares/Chart.yaml | awk '{print $2}' | tr -d '"')
MANIFEST_VERSION=$(grep -E '^  version:' olares/OlaresManifest.yaml | awk '{print $2}')
MANIFEST_VERSIONNAME=$(grep -E '^  versionName:' olares/OlaresManifest.yaml | awk '{print $2}' | tr -d "'")

[ "$CHART_VERSION" = "$CHART_APPVERSION" ] || melde "Chart.yaml: version ($CHART_VERSION) != appVersion ($CHART_APPVERSION)"
[ "$CHART_VERSION" = "$MANIFEST_VERSION" ] || melde "OlaresManifest metadata.version ($MANIFEST_VERSION) != Chart-version ($CHART_VERSION)"
[ "$CHART_APPVERSION" = "$MANIFEST_VERSIONNAME" ] || melde "OlaresManifest spec.versionName ($MANIFEST_VERSIONNAME) != appVersion ($CHART_APPVERSION)"

echo "→ Namen identisch (Ordner, Chart, metadata.name, appid)"
for wert in \
  "$(basename "$(pwd)")" \
  "$(grep -E '^name:' olares/Chart.yaml | awk '{print $2}')" \
  "$(grep -E '^  name: ' olares/OlaresManifest.yaml | head -1 | awk '{print $2}')" \
  "$(grep -E '^  appid:' olares/OlaresManifest.yaml | awk '{print $2}')"
do
  [ "$wert" = "aicrm" ] || melde "Name weicht ab: '$wert' (erwartet: aicrm)"
done

# Kommentarzeilen zählen nicht: Dieselben Wörter stehen in den Templates
# als Begründung, warum es sie dort nicht gibt.
ohne_kommentare() { grep -rhvE '^[[:space:]]*#' olares/templates/; }

suche_verboten() {
  local muster="$1" was="$2"
  if ohne_kommentare | grep -qE "$muster"; then
    melde "$was gefunden"
    ohne_kommentare | grep -nE "$muster" | head -3
  fi
}

echo "→ Kein .Files.Get (der Markt-Linter lehnt es ab)"
suche_verboten '\.Files\.Get' ".Files.Get"

echo "→ Keine Helm-Hooks (laufen vor dem ns-owner-Label und kommen nie durch)"
suche_verboten 'helm\.sh/hook' "Helm-Hook"

echo "→ Kein NodePort, LoadBalancer oder hostNetwork"
suche_verboten 'NodePort|LoadBalancer|hostNetwork' "verbotener Netzwerktyp"

echo "→ Image-Tags hängen an Chart.AppVersion, nicht an values.yaml"
if grep -qE '^\s+tag: "[^"]+"' olares/values.yaml; then
  echo "  Hinweis: values.yaml pinnt einen Tag. Das ist nur für ein Release"
  echo "  ohne neue Abbilder richtig — sonst friert es beim Upgrade fest."
fi
grep -q 'default .Chart.AppVersion' olares/templates/deployment-backend.yaml \
  || melde "deployment-backend liest den Tag nicht aus Chart.AppVersion"

echo "→ Migrations-ConfigMap ist aktuell"
python3 scripts/regen-migrations.py > /dev/null
if ! git diff --quiet -- olares/templates/configmap-migrations.yaml 2>/dev/null; then
  melde "configmap-migrations.yaml weicht von supabase/migrations/ ab — regen-migrations.py laufen lassen und committen"
fi

echo "→ helm lint und helm template"
helm lint olares -f olares/values-olares-stub.yaml > /dev/null || melde "helm lint fehlgeschlagen"
helm template aicrm olares -f olares/values-olares-stub.yaml > /dev/null || melde "helm template fehlgeschlagen"

if [ "$FEHLER" -eq 0 ]; then
  echo "Alles in Ordnung."
else
  echo "Prüfung fehlgeschlagen."
  exit 1
fi
