import { describe, expect, it } from "vitest";
import { NEU_PARAM, NEU_ZIELE, neuPfad } from "@/lib/neu";

describe("neuPfad", () => {
  it("hängt den Parameter an, den die Zielseite liest", () => {
    expect(neuPfad("/kontakte")).toBe(`/kontakte?${NEU_PARAM}=1`);
  });

  it("führt jedes Ziel auf eine eigene Liste", () => {
    const pfade = NEU_ZIELE.map((z) => z.pfad);
    expect(new Set(pfade).size).toBe(pfade.length);
    for (const z of NEU_ZIELE) expect(z.pfad.startsWith("/")).toBe(true);
  });
});
