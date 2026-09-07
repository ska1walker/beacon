// Was die Podcast-Bauteile rechnen, ohne DOM: Dauer als Text, Schritt als Satz.

import type { Podcast } from "@/lib/typen";

/** „ca. 3 Min" — die Dauer ist eine Schätzung aus der Wortzahl. */
export function dauerText(sekunden: number | null | undefined): string {
  if (!sekunden || sekunden <= 0) return "";
  if (sekunden < 60) return "unter 1 Min";
  return `ca. ${Math.max(1, Math.round(sekunden / 60))} Min`;
}

/** Der Satz, der während der Erzeugung steht. */
export function fortschrittText(f: Podcast["fortschritt"]): string {
  switch (f.schritt) {
    case "kontext":
      return "Liest den Bestand …";
    case "skript":
      return "Schreibt das Gespräch …";
    case "audio":
      return f.gesamt ? `Spricht Absatz ${f.segment ?? 0} von ${f.gesamt} …` : "Spricht …";
    case "fertig":
      return "Fertig.";
    default:
      return "Bereitet vor …";
  }
}

/** Ein lesbarer Name für ein Speaches-Modell: „Thorsten (high)" statt der Kennung. */
export function modellName(kennung: string): string {
  const m = kennung.match(/piper-([a-z]{2})_([A-Z]{2})-([a-z_]+)-([a-z_]+)$/);
  if (m) {
    const name = m[3].replace(/_/g, " ").replace(/^\w/, (c) => c.toUpperCase());
    return `${name} (${m[4]}, ${m[1].toUpperCase()})`;
  }
  return kennung.replace(/^speaches-ai\//, "");
}

export function istDeutsch(kennung: string): boolean {
  const k = kennung.toLowerCase();
  return k.includes("de_de") || k.includes("-de-") || k.endsWith("-de") || k.includes("german");
}
