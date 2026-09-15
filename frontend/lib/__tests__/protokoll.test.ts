import { describe, expect, it } from "vitest";
import { anriss, bloecke, stuecke } from "@/lib/protokoll";

const PROTOKOLL = [
  "# Wartung Serverraum",
  "",
  "**Datum:** 10. September 2026 · **Dauer:** 30 min",
  "",
  "## Aufgaben",
  "",
  "- [ ] Angebot schicken",
  "- [x] Termin bestätigt",
  "- ohne Haken",
  "",
  "Zweiter Absatz,",
  "über zwei Zeilen.",
].join("\n");

describe("bloecke", () => {
  it("kennt Überschriften, Absätze und Listen mit und ohne Haken", () => {
    const b = bloecke(PROTOKOLL);
    expect(b.map((x) => x.art)).toEqual(["ueberschrift", "absatz", "ueberschrift", "liste", "absatz"]);
    const liste = b[3];
    expect(liste.art === "liste" && liste.punkte.map((p) => p.erledigt)).toEqual([false, true, null]);
    expect(b[4]).toEqual({ art: "absatz", text: "Zweiter Absatz, über zwei Zeilen." });
  });

  it("macht aus HTML im Text kein HTML", () => {
    const [b] = bloecke("<img src=x onerror=alert(1)>");
    expect(b).toEqual({ art: "absatz", text: "<img src=x onerror=alert(1)>" });
  });
});

describe("stuecke", () => {
  it("trennt fett und nicht fett", () => {
    expect(stuecke("**Datum:** heute")).toEqual([
      { text: "Datum:", fett: true },
      { text: " heute", fett: false },
    ]);
  });
});

describe("anriss", () => {
  it("lässt Überschriften weg und kürzt", () => {
    const a = anriss(PROTOKOLL, 40);
    expect(a.startsWith("Datum:")).toBe(true);
    expect(a.endsWith("…")).toBe(true);
    expect(a).not.toContain("**");
    expect(anriss(PROTOKOLL)).not.toContain("Aufgaben");
  });
});
