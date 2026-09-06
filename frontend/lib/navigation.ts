/**
 * Die Navigation als Daten — ohne React, damit sie sich prüfen lässt.
 *
 * Vier Gruppen mit Überschrift statt einer Liste von dreizehn: Verkauf,
 * Bestand, Post, Wissen. Kein Aufklappen — bei dreizehn Einträgen
 * versteckt es mehr, als es ordnet. Favoriten stehen darüber, in der
 * Reihenfolge, in der jemand sie gemerkt hat. Die Symbole hängen in der
 * Hülle an den Schlüsseln; hier steht nur, was wohin gehört.
 */

export type NavZeichen =
  | "start" | "leads" | "angebote" | "prognose" | "aufgaben"
  | "firmen" | "kontakte" | "listen"
  | "eingang" | "tickets" | "kampagnen"
  | "fragen" | "erkenntnisse" | "einstellungen";

export interface NavZiel {
  pfad: string;
  text: string;
  zeichen: NavZeichen;
}

export interface NavGruppe {
  titel: string;
  ziele: NavZiel[];
}

export const GRUPPEN: NavGruppe[] = [
  {
    titel: "Verkauf",
    ziele: [
      { pfad: "/", text: "Start", zeichen: "start" },
      { pfad: "/deals", text: "Leads", zeichen: "leads" },
      { pfad: "/angebote", text: "Angebote", zeichen: "angebote" },
      { pfad: "/prognose", text: "Prognose", zeichen: "prognose" },
      { pfad: "/aufgaben", text: "Aufgaben", zeichen: "aufgaben" },
    ],
  },
  {
    titel: "Bestand",
    ziele: [
      { pfad: "/firmen", text: "Firmen", zeichen: "firmen" },
      { pfad: "/kontakte", text: "Kontakte", zeichen: "kontakte" },
      { pfad: "/listen", text: "Listen", zeichen: "listen" },
    ],
  },
  {
    titel: "Post",
    ziele: [
      { pfad: "/eingang", text: "Eingang", zeichen: "eingang" },
      { pfad: "/tickets", text: "Tickets", zeichen: "tickets" },
      { pfad: "/kampagnen", text: "Kampagnen", zeichen: "kampagnen" },
    ],
  },
  {
    titel: "Wissen",
    ziele: [
      { pfad: "/fragen", text: "Fragen", zeichen: "fragen" },
      { pfad: "/erkenntnisse", text: "Erkenntnisse", zeichen: "erkenntnisse" },
    ],
  },
];

export const NACHRANGIG: NavZiel[] = [{ pfad: "/einstellungen", text: "Einstellungen", zeichen: "einstellungen" }];

export const ALLE_ZIELE: NavZiel[] = GRUPPEN.flatMap((g) => g.ziele);

/** Was die schmale Leiste unten zeigt, wenn niemand Favoriten hat. */
export const MOBIL_STANDARD = ["/", "/deals", "/firmen", "/kontakte"];
export const MOBIL_MAX = 4;

export function istAktiv(pfad: string, aktuell: string): boolean {
  if (pfad === "/") return aktuell === "/";
  return aktuell === pfad || aktuell.startsWith(`${pfad}/`);
}

const JE_PFAD = new Map([...ALLE_ZIELE, ...NACHRANGIG].map((z) => [z.pfad, z]));

/** Die Favoriten als Ziele — in gemerkter Reihenfolge; Unbekanntes und Doppeltes fällt weg. */
export function favoritenZiele(favoriten: string[]): NavZiel[] {
  const ergebnis: NavZiel[] = [];
  for (const pfad of favoriten) {
    const ziel = JE_PFAD.get(pfad);
    if (ziel && !ergebnis.includes(ziel)) ergebnis.push(ziel);
  }
  return ergebnis;
}

export function favoritUmschalten(favoriten: string[], pfad: string): string[] {
  return favoriten.includes(pfad) ? favoriten.filter((p) => p !== pfad) : [...favoriten, pfad];
}

/** Die Leiste unten: erst die Favoriten, aufgefüllt aus der Vorgabe bis vier. */
export function mobilZiele(favoriten: string[]): NavZiel[] {
  const ziele = favoritenZiele(favoriten).slice(0, MOBIL_MAX);
  for (const z of favoritenZiele(MOBIL_STANDARD)) {
    if (ziele.length >= MOBIL_MAX) break;
    if (!ziele.includes(z)) ziele.push(z);
  }
  return ziele;
}

/** Alles, was nicht auf der Leiste ist — für „Mehr“, inklusive Einstellungen. */
export function mobilRest(favoriten: string[]): NavZiel[] {
  const gezeigt = new Set(mobilZiele(favoriten).map((z) => z.pfad));
  return [...ALLE_ZIELE, ...NACHRANGIG].filter((z) => !gezeigt.has(z.pfad));
}
