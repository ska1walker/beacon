// Die Adresse, unter der die aktuelle Liste als CSV liegt.
//
// Bewusst nur ein Pfad und kein `fetch`: Ein gewöhnlicher Link mit
// `download` nimmt den Sitzungskeks von selbst mit, kann abbrechen und
// weiterladen, und der Browser muss die Datei nie ganz im Speicher
// halten. Bei zwanzigtausend Kontakten ist das der Unterschied zwischen
// „lädt" und „Tab abgestürzt".

import { suchparameter } from "@/lib/api";
import type { Objektart } from "@/lib/typen";

/** Wovon es eine Ausfuhr gibt. Tickets und Aufgaben hätten dieselben
    Feldlisten — sie fehlen, weil sie nicht geprüft sind. */
export const EXPORTIERBAR = new Set<Objektart>(["contacts", "companies"]);

export type Ausfuhrlage = {
  q?: string;
  filter?: string;
  sort?: string | null;
  richtung?: string | null;
  spalten?: string[];
};

export function ausfuhrPfad(entity: Objektart, lage: Ausfuhrlage): string {
  return `/api/ausfuhr${suchparameter({
    entity,
    q: lage.q,
    filter: lage.filter,
    sort: lage.sort,
    richtung: lage.richtung,
    // Die Reihenfolge der Spalten ist die der Tabelle. Wer sie in der
    // Datei anders will, sortiert sie in Excel — nicht hier.
    spalten: lage.spalten?.length ? lage.spalten.join(",") : "",
  })}`;
}
