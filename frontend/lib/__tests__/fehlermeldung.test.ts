import { describe, expect, it } from "vitest";
import { fehlerMeldung } from "@/lib/fehlermeldung";

describe("fehlerMeldung", () => {
  it("nimmt Name, Meldung und Stack aus einem Error", () => {
    const e = new TypeError("x is not a function");
    const b = fehlerMeldung(e, "/firmen/1", "Mozilla/5.0");
    expect(b.nachricht).toBe("TypeError: x is not a function");
    expect(b.stack).toContain("TypeError");
    expect(b.pfad).toBe("/firmen/1");
    expect(b.agent).toBe("Mozilla/5.0");
  });

  it("kommt mit Zeichenketten, Objekten und nichts zurecht", () => {
    expect(fehlerMeldung("kaputt", "/").nachricht).toBe("kaputt");
    expect(fehlerMeldung({ message: "aus Objekt" }, "/").nachricht).toBe("aus Objekt");
    expect(fehlerMeldung(undefined, "/").nachricht).toBe("Unbekannter Fehler");
    expect(fehlerMeldung(42, "/").nachricht).toBe("42");
  });

  it("kürzt auf das, was das Backend annimmt", () => {
    const e = new Error("m".repeat(5000));
    e.stack = "s".repeat(20000);
    const b = fehlerMeldung(e, "/p".repeat(600), "a".repeat(1000));
    expect(b.nachricht.length).toBe(2000);
    expect(b.stack.length).toBe(8000);
    expect(b.pfad.length).toBe(500);
    expect(b.agent.length).toBe(300);
  });
});
