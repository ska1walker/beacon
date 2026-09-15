import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

/**
 * Jede `var(--am-…)` muss es geben.
 *
 * Eine unbekannte CSS-Variable ist kein Fehler, sie ist einfach nichts:
 * `padding: var(--am-raum-5)` wird zu gar keinem Polster, ohne Warnung.
 * So standen alle Dialoge von 0.9.0 bis 0.10.0 ohne Innenabstand da — die
 * Raumskala springt von 4 auf 6. Der Browser meldet das nirgends, also
 * meldet es dieser Test.
 */

const WURZEL = join(__dirname, "..", "..");

function dateien(ordner: string): string[] {
  return readdirSync(ordner).flatMap((name) => {
    if (name === "node_modules" || name.startsWith(".")) return [];
    const pfad = join(ordner, name);
    if (statSync(pfad).isDirectory()) return dateien(pfad);
    return /\.(css|tsx?)$/.test(name) && !name.endsWith(".test.ts") ? [pfad] : [];
  });
}

describe("Designtoken", () => {
  it("verwendet nur Variablen, die definiert sind", () => {
    const quellen = ["app", "components", "lib"].flatMap((o) => dateien(join(WURZEL, o)));
    const texte = quellen.map((p) => [p, readFileSync(p, "utf8")] as const);
    // Definitionen auch aus dem gelieferten Preset, falls dort welche stehen.
    const definiert = new Set(
      texte.flatMap(([, t]) => [...t.matchAll(/(--am-[\w-]+)\s*:/g)].map((m) => m[1])),
    );

    const fehlend = texte.flatMap(([pfad, t]) =>
      [...t.matchAll(/var\((--am-[\w-]+)/g)]
        .map((m) => m[1])
        .filter((name) => !definiert.has(name))
        .map((name) => `${pfad.replace(WURZEL, "")}: ${name}`),
    );

    expect([...new Set(fehlend)]).toEqual([]);
  });
});
