import { describe, expect, it } from "vitest";
import { datenziele, host, istIntern, nachweis, zone } from "@/lib/datenwege";
import type { OrgSettings } from "@/lib/typen";

const LEER = {
  llm_ready: false,
  llm_base_url: "",
  tts_ready: false,
  tts_endpoint_url: null,
  suche_endpoint_url: null,
  smtp_ready: false,
  smtp_host: null,
  mail_endpoint_url: null,
  marketing_versand: "smtp",
  brevo_api_key_set: false,
  links_basis_wirksam: "https://41b89d101.kaivostudio.olares.de",
} as unknown as OrgSettings;

function mit(mehr: Partial<OrgSettings>): OrgSettings {
  return { ...LEER, ...mehr } as OrgSettings;
}

describe("host", () => {
  it("schält Schema, Port und Pfad ab", () => {
    expect(host("https://api.search.brave.com/res/v1/web/search")).toBe("api.search.brave.com");
    expect(host("http://speaches.speachesv3-shared.svc.cluster.local:8000")).toBe("speaches.speachesv3-shared.svc.cluster.local");
    expect(host("  HTTP://Litellm.Local:4000/v1  ")).toBe("litellm.local");
    expect(host(null)).toBe("");
  });
});

describe("istIntern", () => {
  it("erkennt, was auf dieser Box liegt", () => {
    expect(istIntern("http://speaches.speachesv3-shared.svc.cluster.local:8000")).toBe(true);
    expect(istIntern("http://localhost:4000/v1")).toBe(true);
    expect(istIntern("http://127.0.0.1:8010")).toBe(true);
    expect(istIntern("http://192.168.1.17:4000")).toBe(true);
    expect(istIntern("http://10.233.0.5")).toBe(true);
    expect(istIntern("http://172.20.0.9")).toBe(true);
    expect(istIntern("http://litellm:4000/v1")).toBe(true); // Dienstname ohne Punkt
    expect(istIntern(null)).toBe(true); // nichts eingetragen, nichts geht hinaus
  });

  it("hält alles andere für außerhalb", () => {
    expect(istIntern("https://api.search.brave.com")).toBe(false);
    expect(istIntern("smtp.strato.de")).toBe(false);
    expect(istIntern("http://172.15.0.1")).toBe(false); // knapp außerhalb des privaten Blocks
  });

  it("zählt die eigene Zone als Box — gemessen, nicht vermutet", () => {
    // Aus Beacons Pod löst llm.kaivostudio.olares.de auf 192.168.1.17 auf.
    expect(istIntern("https://llm.kaivostudio.olares.de/v1", "kaivostudio.olares.de")).toBe(true);
    expect(istIntern("https://kaivostudio.olares.de", "kaivostudio.olares.de")).toBe(true);
    // Eine fremde Zone bleibt fremd — auch wenn sie ähnlich endet.
    expect(istIntern("https://llm.fremd.olares.de/v1", "kaivostudio.olares.de")).toBe(false);
    expect(istIntern("https://boesekaivostudio.olares.de", "kaivostudio.olares.de")).toBe(false);
  });
});

describe("zone", () => {
  it("leitet die eigene Zone aus der Link-Adresse ab", () => {
    expect(zone(LEER)).toBe("kaivostudio.olares.de");
    expect(zone(undefined)).toBe("");
    expect(zone({ ...LEER, links_basis_wirksam: null } as OrgSettings)).toBe("");
    expect(zone({ ...LEER, links_basis_wirksam: "https://beispiel.de" } as OrgSettings)).toBe("");
  });
});

describe("datenziele und nachweis", () => {
  it("sagt ohne Einstellungen nichts", () => {
    expect(nachweis(undefined)).toBeNull();
    expect(datenziele(undefined)).toEqual([]);
  });

  it("zählt Endpunkte auf der Box nicht mit — Dienstname wie Zone", () => {
    const e = mit({
      llm_ready: true,
      llm_base_url: "https://llm.kaivostudio.olares.de/v1",
      tts_ready: true,
      tts_endpoint_url: "http://speaches.speachesv3-shared.svc.cluster.local:8000",
    });
    expect(datenziele(e)).toEqual([]);
    expect(nachweis(e)).toEqual({ text: "Alles auf dieser Box", extern: false, ziele: [] });
  });

  it("nennt fremde Ziele beim Namen und zählt sie", () => {
    const eins = mit({ suche_endpoint_url: "https://api.search.brave.com/res/v1/web/search" });
    expect(datenziele(eins)).toEqual([{ was: "Suchdienst", host: "api.search.brave.com" }]);
    expect(nachweis(eins)!.text).toBe("1 Ziel außerhalb");
    expect(nachweis(eins)!.extern).toBe(true);

    const drei = mit({
      suche_endpoint_url: "https://api.search.brave.com",
      smtp_ready: true,
      smtp_host: "smtp.strato.de",
      marketing_versand: "brevo",
      brevo_api_key_set: true,
    });
    expect(datenziele(drei).map((z) => z.was)).toEqual(["Suchdienst", "E-Mail", "Marketing"]);
    expect(nachweis(drei)!.text).toBe("3 Ziele außerhalb");
  });

  it("zählt nur, was auch benutzt wird", () => {
    // Adresse hinterlegt, aber nicht eingerichtet: es geht nichts hinaus.
    const aus = mit({ llm_ready: false, llm_base_url: "https://openai.example.com/v1" });
    expect(datenziele(aus)).toEqual([]);
    // Brevo gewählt, aber ohne Schlüssel: derselbe Fall.
    const ohneSchluessel = mit({ marketing_versand: "brevo", brevo_api_key_set: false });
    expect(datenziele(ohneSchluessel)).toEqual([]);
  });
});
