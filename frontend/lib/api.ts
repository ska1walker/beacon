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

async function anfrage<T>(pfad: string, init?: RequestInit): Promise<T> {
  // Der Sitzplatz geht bei jedem Aufruf mit. Ihn nur beim Anlegen
  // mitzuschicken wäre nicht genug: Auch das Protokoll einer Änderung
  // muss auf die richtige Person zeigen.
  const sitzplatz = liesSitzplatz();

  const antwort = await fetch(pfad, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(sitzplatz ? { "X-Aicrm-Sitzplatz": sitzplatz } : {}),
      ...(init?.headers ?? {}),
    },
  });

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
};

export function suchparameter(werte: Record<string, string | number | undefined | null>): string {
  const p = new URLSearchParams();
  for (const [schluessel, wert] of Object.entries(werte)) {
    if (wert !== undefined && wert !== null && wert !== "") p.set(schluessel, String(wert));
  }
  const s = p.toString();
  return s ? `?${s}` : "";
}
