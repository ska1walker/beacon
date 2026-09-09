// Alles, was die Oberfläche über die eigene Anmeldung wissen muss.
//
// Bewusst wenig: Das Passwort geht einmal über die Leitung und liegt
// danach nirgends — kein Zustandsspeicher, kein `localStorage`. Was den
// Zugang trägt, ist ein Keks, den JavaScript nicht sehen kann. Deshalb
// gibt es hier auch keine Funktion, die „das Token liest": Es gäbe nichts
// zu lesen, und eine solche Funktion wäre die Einladung, es doch wieder
// irgendwo abzulegen.

import { api } from "@/lib/api";

export const ANMELDEPFAD = "/anmelden";

export type Lage = {
  angemeldet: boolean;
  name: string | null;
  /** `olares` — der Sidecar prüft. `eigen` — diese Anmeldung prüft. */
  modus: string;
};

export type Einladung = {
  name: string;
  kennung: string;
  /** Das Konto hat schon ein Passwort — Einlösen **ersetzt** es. */
  uebernahme: boolean;
};

export function anmelden(name: string, passwort: string) {
  return api.post<Lage>("/api/anmeldung", { name, passwort });
}

export function abmelden() {
  return api.post<void>("/api/abmeldung");
}

export function lage() {
  return api.get<Lage>("/api/anmeldung/lage");
}

export function passwortAendern(alt: string, neu: string) {
  return api.post<void>("/api/anmeldung/passwort", { alt, neu });
}

/** Wo der Rücksetzcode liegt. Der Code selbst kommt nie über die Leitung. */
export type Ablageort = {
  /** Der Klickweg in der Dateien-App, etwa „Data › beacon › …". */
  ordner: string;
  minuten: number;
};

export function ruecksetzungAnfordern(name: string) {
  return api.post<Ablageort>("/api/anmeldung/vergessen", { name });
}

export function ruecksetzungEinloesen(name: string, code: string, passwort: string) {
  return api.post<Lage>("/api/anmeldung/zuruecksetzen", { name, code, passwort });
}

export function einladungLesen(token: string) {
  return api.get<Einladung>(`/api/einladung/${encodeURIComponent(token)}`);
}

export function einladungEinloesen(token: string, passwort: string) {
  return api.post<Lage>(`/api/einladung/${encodeURIComponent(token)}`, { passwort });
}

/**
 * Wohin nach dem Anmelden? Nur ein Pfad auf dieser Seite.
 *
 * Ohne diese Prüfung wäre `?weiter=` eine offene Weiterleitung: Ein Link
 * `…/anmelden?weiter=https://boese.example` führte nach erfolgreicher
 * Anmeldung auf eine fremde Seite, die aussieht wie Beacon. Erlaubt ist
 * deshalb nur ein Pfad, der mit genau einem Schrägstrich beginnt —
 * `//fremd.example` ist protokollrelativ und damit auch auswärts.
 */
export function zielPfad(weiter: string | null | undefined): string {
  if (!weiter || !weiter.startsWith("/") || weiter.startsWith("//")) return "/";
  return weiter;
}
