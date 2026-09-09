import { describe, expect, it } from "vitest";
import { anzahl, dateigroesse, euro, euroGenau, firmenschluessel, initialen, initialenAusName, personName, prozent } from "@/lib/format";

/**
 * Intl setzt vor das Währungszeichen ein geschütztes Leerzeichen (U+00A0),
 * kein gewöhnliches. Ein Test, der das nicht weiß, meldet „erwartet
 * '14.500 €', bekommen '14.500 €'" — zwei Zeichenketten, die gleich
 * aussehen und es nicht sind. Hier wird deshalb vergleichbar gemacht,
 * statt am Format herumzubasteln: Im Browser ist das geschützte
 * Leerzeichen genau richtig, es verhindert den Umbruch vor dem €.
 */
function schmal(text: string): string {
  return text.replace(/\u00a0/g, " ");
}

describe("Beträge", () => {
  it("rundet in Listen auf ganze Euro", () => {
    // In der Pipeline stören Cent: „14.500 €" liest sich, „14.500,00 €"
    // muss man entziffern.
    expect(schmal(euro(1450000))).toBe("14.500 €");
  });

  it("zeigt auf Kundendokumenten jeden Cent", () => {
    // Der Fehler, gegen den dieser Test steht: Die Druckfassung eines
    // Angebots hat 3.575,80 € als „3.576 €" ausgewiesen. Auf einem Blatt,
    // das an einen Kunden geht, ist das schlicht falsch.
    expect(schmal(euroGenau(357580))).toBe("3.575,80 €");
    expect(schmal(euroGenau(2239580))).toBe("22.395,80 €");
  });

  it("rundet nicht schon beim Rechnen", () => {
    // 4 Servicetage à 1.200 € mit 10 % Nachlass
    const betrag = Math.round(4 * 120000 * 0.9);
    expect(betrag).toBe(432000);
    expect(schmal(euroGenau(betrag))).toBe("4.320,00 €");
  });

  it("stellt die Null dar, statt sie zu verschlucken", () => {
    expect(schmal(euro(0))).toBe("0 €");
    expect(schmal(euroGenau(0))).toBe("0,00 €");
  });
});

describe("Anzeige", () => {
  it("gibt Wahrscheinlichkeiten in Prozent", () => {
    expect(schmal(prozent(0.4))).toBe("40 %");
    expect(prozent(null)).toBe("—");
  });

  it("kommt mit halben Namen zurecht", () => {
    expect(personName("Andrea", "Vosskamp")).toBe("Andrea Vosskamp");
    expect(personName(null, "Vosskamp")).toBe("Vosskamp");
    expect(personName(null, null)).toBe("Ohne Namen");
  });

  it("bildet Initialen", () => {
    expect(initialen("Andrea", "Vosskamp")).toBe("AV");
    expect(initialen(null, null)).toBe("?");
  });
});

describe("Ein- und Mehrzahl", () => {
  it("schreibt bei eins die Einzahl", () => {
    // „1 Punkte" liest sich wie ein Fehler — und wirkt so auf den Rest.
    expect(anzahl(1, "Punkt", "Punkte")).toBe("1 Punkt");
    expect(anzahl(0, "Punkt", "Punkte")).toBe("0 Punkte");
    expect(anzahl(2, "Punkt", "Punkte")).toBe("2 Punkte");
  });
});

describe("Initialen aus einem ganzen Namen", () => {
  it("nimmt die Anfangsbuchstaben zweier Wörter", () => {
    expect(initialenAusName("Kai Böhm")).toBe("KB");
    expect(initialenAusName("marc-bayer")).toBe("MB");
  });

  it("nimmt bei einem Wort zwei Buchstaben", () => {
    // Ein einzelnes „K" im Kreis sieht aus, als fehle etwas.
    expect(initialenAusName("kaivostudio")).toBe("KA");
  });

  it("bleibt bei fehlendem Namen ruhig", () => {
    expect(initialenAusName(null)).toBe("?");
    expect(initialenAusName("   ")).toBe("?");
  });
});

describe("firmenschluessel", () => {
  it("lässt die Rechtsform am Ende weg", () => {
    // Die Signatur schreibt sie hin, der Bestand meist nicht.
    expect(firmenschluessel("Hanseatic Legal Partner mbB")).toBe(
      firmenschluessel("Hanseatic Legal Partner"),
    );
    expect(firmenschluessel("Nordwind Logistik GmbH")).toBe("nordwind logistik");
    expect(firmenschluessel("Meyer Präzisionstechnik GmbH & Co. KG")).toBe(
      "meyer präzisionstechnik",
    );
  });

  it("wirft nichts weg, was zum Namen gehört", () => {
    // „Partner" trägt hier den Namen; „GmbH" wäre allein nichts.
    expect(firmenschluessel("Krüger Partner")).toBe("krüger partner");
    expect(firmenschluessel("GmbH")).toBe("gmbh");
  });

  it("führt verschiedene Firmen nicht zusammen", () => {
    expect(firmenschluessel("Nordwind Logistik")).not.toBe(
      firmenschluessel("Nordwind Logistik Nord"),
    );
  });
});

describe("dateigroesse", () => {
  it("nennt kleine Dateien in Bytes und große in Megabyte", () => {
    expect(dateigroesse(512)).toBe("512 B");
    expect(dateigroesse(2048)).toBe("2 KB");
    expect(dateigroesse(2_411_724)).toBe("2,3 MB");
  });

  it("rundet auf eine Nachkommastelle, damit die Zahl lesbar bleibt", () => {
    expect(dateigroesse(25 * 1024 * 1024)).toBe("25,0 MB");
  });
});
