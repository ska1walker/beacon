"use client";

import { useEffect } from "react";
import { HOECHSTENS_JE_SEITE, fehlerMeldung } from "@/lib/fehlermeldung";

let gemeldet = 0;

/**
 * Schickt einen Fehler an die Box. Absichtlich nicht über `api.post`:
 * Der Fehlerpfad darf selbst nie werfen, und `keepalive` lässt die
 * Meldung auch dann noch ankommen, wenn die Seite gerade zerbricht.
 */
export function fehlerMelden(fehler: unknown): void {
  if (typeof window === "undefined" || gemeldet >= HOECHSTENS_JE_SEITE) return;
  gemeldet += 1;
  try {
    const bericht = fehlerMeldung(fehler, window.location.pathname, navigator.userAgent);
    void fetch("/api/fehler", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(bericht),
      keepalive: true,
    }).catch(() => undefined);
  } catch {
    /* ein Fehler beim Melden eines Fehlers bleibt still */
  }
}

/** Hört auf unbehandelte Fehler und Promise-Abweisungen der Seite. */
export function Fehlermelder() {
  useEffect(() => {
    function beiFehler(ev: ErrorEvent) {
      fehlerMelden(ev.error ?? ev.message);
    }
    function beiAbweisung(ev: PromiseRejectionEvent) {
      fehlerMelden(ev.reason);
    }
    window.addEventListener("error", beiFehler);
    window.addEventListener("unhandledrejection", beiAbweisung);
    return () => {
      window.removeEventListener("error", beiFehler);
      window.removeEventListener("unhandledrejection", beiAbweisung);
    };
  }, []);
  return null;
}
