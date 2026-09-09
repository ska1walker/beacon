/**
 * Ein Sitzplatz, den es nicht mehr gibt.
 *
 * Nach einer Neuinstallation ist die Datenbank neu, der Platz im Browser
 * aber noch der alte. Dann scheitert jeder Aufruf mit 403, und an den
 * Sitzplatz denkt in dem Moment niemand — die Oberfläche muss ihn selbst
 * wegräumen.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { liesSitzplatz, setzeSitzplatz, SITZPLATZ_COOKIE } from "@/lib/sitzplatz";

/**
 * Ein Keksglas in zehn Zeilen statt jsdom als Abhängigkeit.
 *
 * Geprüft wird die eigene Logik — das Lesen mit einem regulären Ausdruck
 * und das Löschen über `Max-Age=0`. Dafür genügt ein `document.cookie`,
 * das sich wie eines verhält: Zuweisen legt an, Lesen gibt alles zurück.
 */
function keksglas() {
  const kekse = new Map<string, string>();
  return {
    get cookie(): string {
      return [...kekse].map(([k, w]) => `${k}=${w}`).join("; ");
    },
    set cookie(zeile: string) {
      const [paar, ...teile] = zeile.split(";").map((t) => t.trim());
      const trenner = paar.indexOf("=");
      const name = paar.slice(0, trenner);
      const wert = paar.slice(trenner + 1);
      if (teile.some((t) => t.toLowerCase() === "max-age=0")) kekse.delete(name);
      else kekse.set(name, wert);
    },
  };
}

beforeEach(() => vi.stubGlobal("document", keksglas()));
afterEach(() => vi.unstubAllGlobals());

describe("Sitzplatz im Cookie", () => {
  it("wird gesetzt und wiedergefunden", () => {
    setzeSitzplatz("11111111-1111-1111-1111-111111111111");
    expect(liesSitzplatz()).toBe("11111111-1111-1111-1111-111111111111");
  });

  it("lässt sich wieder wegräumen", () => {
    setzeSitzplatz("22222222-2222-2222-2222-222222222222");
    setzeSitzplatz(null);
    expect(liesSitzplatz()).toBeNull();
    expect(document.cookie).not.toContain(`${SITZPLATZ_COOKIE}=2222`);
  });
});

describe("Ein unbekannter Platz räumt sich selbst weg", () => {
  beforeEach(() => {
    vi.resetModules();
    setzeSitzplatz("33333333-3333-3333-3333-333333333333");
  });

  it("löscht den Platz und lädt einmal neu", async () => {
    const neuLaden = vi.fn();
    // `window` muss es geben: Der Wächter in `api.ts` steht dort, damit
    // beim Server-Rendern nichts auf den Browser zugreift.
    vi.stubGlobal("window", { location: { reload: neuLaden, pathname: "/kontakte", search: "" } });
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        new Response(JSON.stringify({ detail: "Dieser Sitzplatz gehört nicht zu Ihrer Organisation." }), {
          status: 403,
          headers: { "Content-Type": "application/json", "X-Beacon-Sitzplatz": "unbekannt" },
        }),
      ),
    );

    const { api } = await import("@/lib/api");
    await expect(api.get("/api/companies")).rejects.toThrow();

    expect(liesSitzplatz()).toBeNull();
    expect(neuLaden).toHaveBeenCalledTimes(1);
  });

  it("räumt nicht bei einem gewöhnlichen 403", async () => {
    const neuLaden = vi.fn();
    // `window` muss es geben: Der Wächter in `api.ts` steht dort, damit
    // beim Server-Rendern nichts auf den Browser zugreift.
    vi.stubGlobal("window", { location: { reload: neuLaden, pathname: "/kontakte", search: "" } });
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        new Response(JSON.stringify({ detail: "Dafür fehlt Ihnen die Berechtigung." }), {
          status: 403,
          headers: { "Content-Type": "application/json" },
        }),
      ),
    );

    const { api } = await import("@/lib/api");
    await expect(api.get("/api/settings")).rejects.toThrow();

    expect(liesSitzplatz()).toBe("33333333-3333-3333-3333-333333333333");
    expect(neuLaden).not.toHaveBeenCalled();
  });
});
