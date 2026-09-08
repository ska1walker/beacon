// Ein Zugang zur API, nicht viele. Jeder Aufruf geht über denselben
// Ursprung — auf der Box sieht der Envoy-Sidecar ihn dadurch und prüft ihn.

import { liesSitzplatz } from "@/lib/sitzplatz";

export class ApiFehler extends Error {
  constructor(
    readonly status: number,
    message: string,
  ) {
    super(message);
    this.name = "ApiFehler";
  }
}

/**
 * Bei 401 einmal zur Anmeldemaske, mit dem Weg zurück im Gepäck.
 *
 * Einmal, nicht je Kachel: Eine Seite stellt mehrere Abfragen gleichzeitig,
 * und ohne diese Sperre lösten fünf gleichzeitige 401 fünf Weiterleitungen
 * aus — der Browser käme mit einem Verlauf zurück, in dem der Zurück-Knopf
 * nichts mehr tut.
 *
 * Die Anmeldewege selbst sind ausgenommen: Ein falsches Passwort ist auch
 * ein 401, und es soll als Meldung im Formular stehen, nicht als Sprung.
 */
let leitetUm = false;

function zurZurAnmeldung(pfad: string): void {
  if (typeof window === "undefined" || leitetUm) return;
  if (pfad.startsWith("/api/anmeldung") || pfad.startsWith("/api/einladung")) return;
  const hier = window.location.pathname;
  if (hier === "/anmelden" || hier.startsWith("/einladung/")) return;
  leitetUm = true;
  const weiter = hier + window.location.search;
  window.location.assign(`/anmelden?weiter=${encodeURIComponent(weiter)}`);
}

async function anfrage<T>(pfad: string, init?: RequestInit): Promise<T> {
  // Der Sitzplatz geht bei jedem Aufruf mit. Ihn nur beim Anlegen
  // mitzuschicken wäre nicht genug: Auch das Protokoll einer Änderung
  // muss auf die richtige Person zeigen.
  const sitzplatz = liesSitzplatz();

  const koepfe: Record<string, string> = {
    "Content-Type": "application/json",
    ...(sitzplatz ? { "X-Beacon-Sitzplatz": sitzplatz } : {}),
    ...((init?.headers as Record<string, string>) ?? {}),
  };
  // Ein leerer Wert heißt „diesen Kopf nicht setzen" — siehe `postForm`.
  for (const [name, wert] of Object.entries(koepfe)) if (!wert) delete koepfe[name];

  const antwort = await fetch(pfad, { ...init, headers: koepfe });

  if (antwort.status === 401) zurZurAnmeldung(pfad);

  if (!antwort.ok) {
    // FastAPI legt den Grund unter `detail` ab. Steht dort nichts
    // Brauchbares, ist der Statuscode immer noch mehr als „Fehler".
    let grund = `Anfrage fehlgeschlagen (${antwort.status})`;
    try {
      const koerper = await antwort.json();
      if (typeof koerper?.detail === "string") grund = koerper.detail;
    } catch {
      /* keine JSON-Antwort — dann bleibt der Statuscode die Auskunft */
    }
    throw new ApiFehler(antwort.status, grund);
  }

  if (antwort.status === 204) return undefined as T;
  return (await antwort.json()) as T;
}

export const api = {
  get: <T>(pfad: string) => anfrage<T>(pfad),
  post: <T>(pfad: string, koerper?: unknown) =>
    anfrage<T>(pfad, { method: "POST", body: JSON.stringify(koerper ?? {}) }),
  patch: <T>(pfad: string, koerper: unknown) =>
    anfrage<T>(pfad, { method: "PATCH", body: JSON.stringify(koerper) }),
  put: <T>(pfad: string, koerper: unknown) =>
    anfrage<T>(pfad, { method: "PUT", body: JSON.stringify(koerper) }),
  del: (pfad: string) => anfrage<void>(pfad, { method: "DELETE" }),

  /**
   * Ein Formular mit Datei. Setzt **kein** `Content-Type`: Bei
   * `multipart/form-data` gehört die Trennmarke dazu, und die kennt nur
   * der Browser. Wer den Kopf hier von Hand setzt, schickt eine Grenze,
   * die es nicht gibt — der Server findet dann kein einziges Feld.
   */
  postForm: <T>(pfad: string, formular: FormData) =>
    anfrage<T>(pfad, { method: "POST", body: formular, headers: { "Content-Type": "" } }),
};

export function suchparameter(werte: Record<string, string | number | undefined | null>): string {
  const p = new URLSearchParams();
  for (const [schluessel, wert] of Object.entries(werte)) {
    if (wert !== undefined && wert !== null && wert !== "") p.set(schluessel, String(wert));
  }
  const s = p.toString();
  return s ? `?${s}` : "";
}
