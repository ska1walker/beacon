// Wohin Daten gehen — gemessen, nicht behauptet.
//
// Die Regel steht in docs/DESIGN.md §5: Der Nachweis am Fuß der Navigation
// trägt gemessene Werte oder gar nichts, denn „eine Zusage ohne Beleg ist
// schlechter als keine". Gemessen wird an dem, was eingetragen ist: Was
// nicht nachweislich auf dieser Box liegt, gilt als außerhalb — dieselbe
// Richtung wie Insilos egress.py, lieber einmal zu viel warnen als einmal
// zu wenig.
//
// „Auf dieser Box" heißt: Kubernetes-Dienstname, localhost oder ein
// privates Netz. Kais LiteLLM und Speaches sprechen genau so an und zählen
// deshalb richtig als intern — eine Adresse über die Olares-Zone verließe
// dagegen das Haus und wird benannt.

import type { OrgSettings } from "@/lib/typen";

export interface Datenziel {
  was: string;
  host: string;
}

const PRIVAT = /^(10\.|127\.|192\.168\.|172\.(1[6-9]|2\d|3[01])\.)/;

/** Der Host einer eingetragenen Adresse — ohne Schema, Pfad und Port. */
export function host(adresse: string | null | undefined): string {
  const roh = (adresse ?? "").trim();
  if (!roh) return "";
  const ohneSchema = roh.replace(/^[a-z][a-z0-9+.-]*:\/\//i, "");
  return ohneSchema.split(/[/?#]/)[0].split("@").pop()!.replace(/:\d+$/, "").toLowerCase();
}

/** Liegt diese Adresse nachweislich auf dieser Box? */
export function istIntern(adresse: string | null | undefined): boolean {
  const h = host(adresse);
  if (!h) return true; // nichts eingetragen heißt: es geht nichts hinaus
  if (h === "localhost" || h.endsWith(".localhost")) return true;
  if (h.endsWith(".svc.cluster.local") || h.endsWith(".svc") || !h.includes(".")) return true;
  return PRIVAT.test(h);
}

/** Die Ziele außerhalb dieser Box, in der Reihenfolge der Einstellungen. */
export function datenziele(e: OrgSettings | undefined): Datenziel[] {
  if (!e) return [];
  const kandidaten: [string, string | null | undefined][] = [
    ["KI-Assistent", e.llm_ready ? e.llm_base_url : null],
    ["Sprachausgabe", e.tts_ready ? e.tts_endpoint_url : null],
    ["Suchdienst", e.suche_endpoint_url],
    ["E-Mail", e.smtp_ready ? e.smtp_host : null],
    ["Postausgang", e.mail_endpoint_url],
  ];
  const ziele: Datenziel[] = [];
  for (const [was, adresse] of kandidaten) {
    if (!adresse || istIntern(adresse)) continue;
    ziele.push({ was, host: host(adresse) });
  }
  // Brevo ist ein Dienst, keine Adresse — er steht als Name für sich.
  if (e.marketing_versand === "brevo" && e.brevo_api_key_set) {
    ziele.push({ was: "Marketing", host: "brevo.com" });
  }
  return ziele;
}

export interface Nachweis {
  text: string;
  extern: boolean;
  ziele: Datenziel[];
}

/**
 * Der Satz für den Fuß der Navigation. Ohne Einstellungen (noch nicht
 * geladen, Abfrage gescheitert) gibt es keinen Satz — dann steht dort
 * nichts, statt etwas Unbelegtes zu behaupten.
 */
export function nachweis(e: OrgSettings | undefined): Nachweis | null {
  if (!e) return null;
  const ziele = datenziele(e);
  if (ziele.length === 0) return { text: "Alles auf dieser Box", extern: false, ziele };
  return {
    text: ziele.length === 1 ? "1 Ziel außerhalb" : `${ziele.length} Ziele außerhalb`,
    extern: true,
    ziele,
  };
}
