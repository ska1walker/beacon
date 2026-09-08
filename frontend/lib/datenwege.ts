// Wohin Daten gehen — gemessen, nicht behauptet.
//
// Die Regel steht in docs/DESIGN.md §5: Der Nachweis am Fuß der Navigation
// trägt gemessene Werte oder gar nichts, denn „eine Zusage ohne Beleg ist
// schlechter als keine". Gemessen wird an dem, was eingetragen ist: Was
// nicht nachweislich auf dieser Box liegt, gilt als außerhalb — dieselbe
// Richtung wie Insilos egress.py, lieber einmal zu viel warnen als einmal
// zu wenig.
//
// „Auf dieser Box" heißt: Kubernetes-Dienstname, localhost, ein privates
// Netz — **oder die eigene Olares-Zone**. Letzteres ist gemessen, nicht
// vermutet: Aus Beacons Backend-Pod löst `llm.kaivostudio.olares.de` auf
// 192.168.1.17 auf, die Box selbst (8.9.2026). Olares führt seine Zone
// intern auf den eigenen Knoten; ein Aufruf dorthin verlässt das Haus
// nicht. Ohne diese Regel hätte die Zeile „außerhalb" behauptet, wo nichts
// hinausgeht — und ein falscher Alarm zerstört das Vertrauen in den
// Nachweis genauso zuverlässig wie eine falsche Beruhigung.
//
// Nötig ist die Ausnahme, weil ein Dienst im eigenen Namensraum (etwa
// LiteLLM unter `litellm-kaivostudio`) von Beacon aus **nicht** direkt
// erreichbar ist: Dort steht nur `app-np`, und Olares riegelt Namensräume
// gegeneinander ab. Nur als *shared* installierte Apps (Speaches) tragen
// die Regeln, die andere hereinlassen. Für alles andere ist die
// Zonen-Adresse der einzige Weg — und der bleibt auf der Box.

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

/**
 * Die Zone dieser Box — abgeleitet aus der Adresse der öffentlichen Links
 * (`41b89d101.kaivostudio.olares.de` → `kaivostudio.olares.de`). Sie ist
 * die einzige Stelle, an der Beacon den eigenen Namen kennt.
 */
export function zone(e: OrgSettings | undefined): string {
  const teile = host(e?.links_basis_wirksam).split(".");
  return teile.length > 2 ? teile.slice(1).join(".") : "";
}

/** Liegt diese Adresse nachweislich auf dieser Box? */
export function istIntern(adresse: string | null | undefined, eigeneZone = ""): boolean {
  const h = host(adresse);
  if (!h) return true; // nichts eingetragen heißt: es geht nichts hinaus
  if (h === "localhost" || h.endsWith(".localhost")) return true;
  if (h.endsWith(".svc.cluster.local") || h.endsWith(".svc") || !h.includes(".")) return true;
  if (eigeneZone && (h === eigeneZone || h.endsWith(`.${eigeneZone}`))) return true;
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
  const eigeneZone = zone(e);
  const ziele: Datenziel[] = [];
  for (const [was, adresse] of kandidaten) {
    if (!adresse || istIntern(adresse, eigeneZone)) continue;
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
