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

echo "→ Root-Manifest ist eine Kopie des Chart-Manifests"
# Marcs Regel für den AImighty-Markt: Repo-Wurzel und Chart tragen
# dasselbe Manifest. Zwei Fassungen driften, eine Kopie nicht.
cmp -s OlaresManifest.yaml olares/OlaresManifest.yaml \
  || melde "OlaresManifest.yaml (Wurzel) weicht von olares/OlaresManifest.yaml ab — cp olares/OlaresManifest.yaml ."

echo "→ Namen identisch (Ordner, Chart, metadata.name, appid)"
for wert in \
  "$(basename "$(pwd)")" \
  "$(grep -E '^name:' olares/Chart.yaml | awk '{print $2}')" \
  "$(grep -E '^  name: ' olares/OlaresManifest.yaml | head -1 | awk '{print $2}')" \
  "$(grep -E '^  appid:' olares/OlaresManifest.yaml | awk '{print $2}')"
do
  [ "$wert" = "beacon" ] || melde "Name weicht ab: '$wert' (erwartet: beacon)"
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

echo "→ Manifest v3: Olares-Abhängigkeit, kein runAsInternal, kein OLARES_USER"
API_VERSION=$(grep -E '^apiVersion:' olares/OlaresManifest.yaml | awk '{print $2}' | tr -d "'\"")
DEP_VERSION=$(awk '/^[[:space:]]*-[[:space:]]*name:[[:space:]]*olares[[:space:]]*$/{f=1} f&&/^[[:space:]]*version:/{gsub(/.*version:[[:space:]]*/,""); gsub(/['"'"'"]/,""); print; exit}' olares/OlaresManifest.yaml)
if [ "$API_VERSION" = "v3" ]; then
  # Insilo v0.1.61–0.1.76: ein geschlossenes Intervall sperrte genau die
  # Version aus, auf der die Box lief. v3 verlangt '>=1.12.6-0'.
  [ "$DEP_VERSION" = ">=1.12.6-0" ] || melde "options.dependencies[olares].version muss bei v3 '>=1.12.6-0' sein, ist '$DEP_VERSION'"
else
  melde "OlaresManifest ohne apiVersion v3 — der Markt-Linter der Box prüft gegen v3"
fi
# runAsInternal ist ein Studio-Merkmal und bricht den Envoy-Sidecar.
grep -qE '^[[:space:]]*runAsInternal:[[:space:]]*true' olares/OlaresManifest.yaml && melde "runAsInternal: true im Manifest"
# v3 lehnt das Präfix OLARES_USER in Chart-Dateien ab — auch in Kommentaren.
grep -rq 'OLARES_USER' olares/ && melde "OLARES_USER kommt in olares/ vor (v3 verbietet das Präfix)"
# Jedes Deployment muss seine Replikate aus .Values.workloads lesen —
# Olares steuert Installation, Anhalten und Fortsetzen darüber.
for tpl in olares/templates/deployment-*.yaml; do
  grep -q 'index .Values.workloads' "$tpl" || melde "$tpl liest replicas nicht aus .Values.workloads"
done

echo "→ Image-Tags hängen an Chart.AppVersion, nicht an values.yaml"
if grep -qE '^\s+tag: "[^"]+"' olares/values.yaml; then
  echo "  Hinweis: values.yaml pinnt einen Tag. Das ist nur für ein Release"
  echo "  ohne neue Abbilder richtig — sonst friert es beim Upgrade fest."
fi
grep -q 'default .Chart.AppVersion' olares/templates/deployment-backend.yaml \
  || melde "deployment-backend liest den Tag nicht aus Chart.AppVersion"

echo "→ Migrations-ConfigMap passt zur Quelle"
# Verglichen wird der Inhalt, nicht der Git-Zustand: Ein Vergleich gegen
# HEAD schlüge bei jeder noch nicht committeten Migration an und wäre als
# Torwächter vor dem Commit damit unbrauchbar.
VORHER=$(cat olares/templates/configmap-migrations.yaml 2>/dev/null || true)
python3 scripts/regen-migrations.py > /dev/null
if [ "$VORHER" != "$(cat olares/templates/configmap-migrations.yaml)" ]; then
  melde "configmap-migrations.yaml war nicht aktuell — sie wurde soeben neu erzeugt, bitte mit committen"
fi

echo "→ helm lint und helm template"
helm lint olares -f olares/values-olares-stub.yaml > /dev/null || melde "helm lint fehlgeschlagen"
helm template beacon olares -f olares/values-olares-stub.yaml > /dev/null || melde "helm template fehlgeschlagen"

if [ "$FEHLER" -eq 0 ]; then
  echo "Alles in Ordnung."
else
  echo "Prüfung fehlgeschlagen."
  exit 1
fi
