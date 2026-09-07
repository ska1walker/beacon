import { describe, expect, it } from "vitest";
import { dauerText, fortschrittText, istDeutsch, modellName } from "@/lib/podcast";

describe("dauerText", () => {
  it("rundet auf Minuten und sagt ca.", () => {
    expect(dauerText(null)).toBe("");
    expect(dauerText(0)).toBe("");
    expect(dauerText(30)).toBe("unter 1 Min");
    expect(dauerText(61)).toBe("ca. 1 Min");
    expect(dauerText(200)).toBe("ca. 3 Min");
  });
});

describe("fortschrittText", () => {
  it("macht aus dem Schritt einen Satz", () => {
    expect(fortschrittText({})).toBe("Bereitet vor …");
    expect(fortschrittText({ schritt: "kontext" })).toBe("Liest den Bestand …");
    expect(fortschrittText({ schritt: "skript" })).toBe("Schreibt das Gespräch …");
    expect(fortschrittText({ schritt: "audio", segment: 3, gesamt: 12 })).toBe("Spricht Absatz 3 von 12 …");
    expect(fortschrittText({ schritt: "fertig" })).toBe("Fertig.");
  });
});

describe("modellName", () => {
  it("liest Piper-Kennungen", () => {
    expect(modellName("speaches-ai/piper-de_DE-thorsten-high")).toBe("Thorsten (high, DE)");
    expect(modellName("speaches-ai/piper-de_DE-eva_k-x_low")).toBe("Eva k (x_low, DE)");
    expect(modellName("speaches-ai/Kokoro-82M-v1.0-ONNX")).toBe("Kokoro-82M-v1.0-ONNX");
  });
  it("erkennt deutsche Stimmen", () => {
    expect(istDeutsch("speaches-ai/piper-de_DE-kerstin-low")).toBe(true);
    expect(istDeutsch("speaches-ai/piper-en_US-amy-low")).toBe(false);
  });
});
