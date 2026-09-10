"use client";

// „Neu" in der Kopfleiste zeigt auf die Liste, in der der Datensatz
// danach steht — und sagt ihr, dass sie ihren Anlegen-Dialog öffnen soll.
//
// Warum ein Parameter in der Adresse und nicht ein Dialog in der Hülle:
// Die Dialoge brauchen Daten, die auf ihrer Seite ohnehin geladen sind
// (Pipelines und Stufen beim Lead, Kategorien beim Ticket). In die Hülle
// gezogen, stellte sie diese Abfragen auf **jeder** Seite, für ein Menü,
// das man selten öffnet.

import { useEffect, useState } from "react";

export const NEU_PARAM = "neu";

/** Wohin „Neu" zeigt, je Objekt. */
export const NEU_ZIELE = [
  { pfad: "/kontakte", text: "Kontakt" },
  { pfad: "/firmen", text: "Firma" },
  { pfad: "/deals", text: "Lead" },
  { pfad: "/tickets", text: "Ticket" },
  { pfad: "/aufgaben", text: "Aufgabe" },
] as const;

export function neuPfad(pfad: string): string {
  return `${pfad}?${NEU_PARAM}=1`;
}

/**
 * Hat jemand über „Neu" hierher gezeigt?
 *
 * Gelesen wird `window.location.search` statt `useSearchParams`: Letzteres
 * verlangt auf jeder Seite eine Suspense-Grenze, und der Wert wird hier
 * genau einmal gebraucht. Danach kommt der Parameter wieder aus der
 * Adresse heraus — sonst öffnete ein Neuladen oder der Zurück-Knopf den
 * Dialog ein zweites Mal.
 */
export function useNeuGewuenscht(): boolean {
  const [gewuenscht, setGewuenscht] = useState(false);

  useEffect(() => {
    const parameter = new URLSearchParams(window.location.search);
    if (!parameter.has(NEU_PARAM)) return;
    parameter.delete(NEU_PARAM);
    const rest = parameter.toString();
    window.history.replaceState(null, "", window.location.pathname + (rest ? `?${rest}` : ""));
    setGewuenscht(true);
  }, []);

  return gewuenscht;
}
