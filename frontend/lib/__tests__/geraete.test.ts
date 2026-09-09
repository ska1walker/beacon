import { describe, expect, it } from "vitest";
import { geraetName } from "@/components/geraete";

describe("geraetName", () => {
  it("macht aus einer Browserkennung etwas Wiedererkennbares", () => {
    const mac = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/152.0.0.0 Safari/537.36";
    expect(geraetName(mac)).toBe("Chrome auf Mac");

    const iphone = "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Mobile/15E148 Safari/604.1";
    expect(geraetName(iphone)).toBe("Safari auf iPhone");

    const win = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/152.0.0.0 Safari/537.36 Edg/152.0.0.0";
    expect(geraetName(win)).toBe("Edge auf Windows");
  });

  it("sagt lieber wenig als etwas Erfundenes", () => {
    expect(geraetName(null)).toBe("Unbekanntes Gerät");
    expect(geraetName("")).toBe("Unbekanntes Gerät");
    expect(geraetName("irgendein Skript/1.0")).toBe("Browser");
  });
});
