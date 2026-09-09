import { describe, expect, it } from "vitest";
import { ausfuhrPfad, EXPORTIERBAR } from "@/lib/ausfuhr";
import { EINFUHR_GRUND_TEXT } from "@/lib/format";
import type { EinfuhrGrund } from "@/lib/typen";

describe("ausfuhrPfad", () => {
  it("nimmt Filter, Sortierung und Spalten mit", () => {
    const pfad = ausfuhrPfad("contacts", {
      q: "meyer",
      filter: '[{"feld":"city","operator":"ist","wert":"Hamburg"}]',
      sort: "last_name",
      richtung: "asc",
      spalten: ["first_name", "last_name", "email"],
    });
    expect(pfad).toContain("entity=contacts");
    expect(pfad).toContain("spalten=first_name%2Clast_name%2Cemail");
    expect(pfad).toContain("sort=last_name");
    expect(decodeURIComponent(pfad)).toContain('"feld":"city"');
  });

  it("lässt weg, was nicht gesetzt ist", () => {
    // Ein leerer Filter in der Adresse wäre ein Filter, der nichts
    // findet — nicht keiner.
    expect(ausfuhrPfad("companies", {})).toBe("/api/ausfuhr?entity=companies");
  });

  it("kennt nur die Objekte, für die es geprüft ist", () => {
    expect(EXPORTIERBAR.has("contacts")).toBe(true);
    expect(EXPORTIERBAR.has("tickets")).toBe(false);
  });
});

describe("EINFUHR_GRUND_TEXT", () => {
  it("hat für jeden Grund einen Satz", () => {
    const gruende: EinfuhrGrund[] = [
      "dublette_email", "dublette_datei", "dublette_domain", "dublette_name",
      "unbekannte_auswahl", "ungueltiger_wert", "unbekannte_person", "leer",
    ];
    for (const g of gruende) expect(EINFUHR_GRUND_TEXT[g]).toBeTruthy();
  });
});
