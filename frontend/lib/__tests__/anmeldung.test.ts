import { describe, expect, it } from "vitest";
import { zielPfad } from "@/lib/anmeldung";

describe("zielPfad", () => {
  it("führt nach dem Anmelden dorthin zurück, wo jemand hinwollte", () => {
    expect(zielPfad("/deals")).toBe("/deals");
    expect(zielPfad("/kontakte?sortierung=neu")).toBe("/kontakte?sortierung=neu");
  });

  it("schickt niemanden auf eine fremde Seite", () => {
    // Ohne diese Prüfung wäre der Parameter eine offene Weiterleitung:
    // Der Link sieht aus wie Beacon und endet auf einer nachgebauten Maske.
    expect(zielPfad("https://boese.example/anmelden")).toBe("/");
    expect(zielPfad("//boese.example")).toBe("/");
    expect(zielPfad("javascript:alert(1)")).toBe("/");
    expect(zielPfad("deals")).toBe("/");
    expect(zielPfad(null)).toBe("/");
    expect(zielPfad("")).toBe("/");
  });
});
