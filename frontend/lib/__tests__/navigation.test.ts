import { describe, expect, it } from "vitest";
import {
  ALLE_ZIELE,
  GRUPPEN,
  LEISTE_STANDARD,
  MOBIL_STANDARD,
  leisteZiele,
  favoritUmschalten,
  favoritenZiele,
  istAktiv,
  mobilRest,
  mobilZiele,
} from "@/lib/navigation";

describe("Navigation", () => {
  it("führt alle dreizehn Ziele genau einmal in vier Gruppen", () => {
    expect(GRUPPEN.map((g) => g.titel)).toEqual(["Verkauf", "Bestand", "Post", "Wissen"]);
    const pfade = ALLE_ZIELE.map((z) => z.pfad);
    expect(pfade).toHaveLength(13);
    expect(new Set(pfade).size).toBe(13);
    expect(pfade).not.toContain("/einstellungen");
  });

  it("erkennt den aktiven Eintrag", () => {
    expect(istAktiv("/", "/")).toBe(true);
    expect(istAktiv("/", "/deals")).toBe(false);
    expect(istAktiv("/deals", "/deals/123")).toBe(true);
    expect(istAktiv("/deals", "/dealsx")).toBe(false);
  });

  it("hält die Reihenfolge der Favoriten und lässt Unbekanntes weg", () => {
    expect(favoritenZiele(["/kontakte", "/nix", "/firmen", "/kontakte", "/einstellungen"]).map((z) => z.pfad)).toEqual([
      "/kontakte",
      "/firmen",
      "/einstellungen",
    ]);
  });

  it("zeigt links die Vorgabe, bis der erste Stern sie ersetzt", () => {
    expect(leisteZiele([]).map((z) => z.pfad)).toEqual(LEISTE_STANDARD);
    expect(LEISTE_STANDARD).toHaveLength(6);
    // Ein einziger Stern genügt — die Vorgabe verschwindet ganz.
    expect(leisteZiele(["/erkenntnisse"]).map((z) => z.pfad)).toEqual(["/erkenntnisse"]);
    // Nur Unbekanntes zählt wie nichts.
    expect(leisteZiele(["/nix"]).map((z) => z.pfad)).toEqual(LEISTE_STANDARD);
    expect(leisteZiele(["/kontakte", "/", "/kontakte"]).map((z) => z.pfad)).toEqual(["/kontakte", "/"]);
  });

  it("schaltet einen Favoriten um", () => {
    expect(favoritUmschalten([], "/firmen")).toEqual(["/firmen"]);
    expect(favoritUmschalten(["/firmen", "/deals"], "/firmen")).toEqual(["/deals"]);
    expect(favoritUmschalten(["/deals"], "/firmen")).toEqual(["/deals", "/firmen"]);
  });

  it("zeigt unten Favoriten, füllt aus der Vorgabe auf, der Rest ist disjunkt", () => {
    expect(mobilZiele([]).map((z) => z.pfad)).toEqual(MOBIL_STANDARD);
    expect(mobilZiele(["/kontakte"]).map((z) => z.pfad)).toEqual(["/kontakte", "/", "/deals", "/firmen"]);
    expect(mobilZiele(["/tickets", "/kampagnen", "/listen", "/fragen", "/firmen"]).map((z) => z.pfad)).toEqual([
      "/tickets",
      "/kampagnen",
      "/listen",
      "/fragen",
    ]);
    const unten = new Set(mobilZiele([]).map((z) => z.pfad));
    const rest = mobilRest([]).map((z) => z.pfad);
    expect(rest.some((p) => unten.has(p))).toBe(false);
    expect(rest).toContain("/einstellungen");
    expect(unten.size + rest.length).toBe(14);
  });
});
