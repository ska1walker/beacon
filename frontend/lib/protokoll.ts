/**
 * Insilos Protokoll, in Blöcke zerlegt — ohne HTML aus dem Text.
 *
 * Das Protokoll ist Markdown aus einem Sprachmodell. Es als HTML in die
 * Seite zu schreiben hieße, einem Modell die Seite zu überlassen. Diese
 * Zerlegung kennt genau, was Insilo schreibt — Überschriften, Absätze,
 * Listen mit und ohne Haken, **fett** — und alles andere bleibt Text.
 */

export type Stueck = { text: string; fett: boolean };

export type Block =
  | { art: "ueberschrift"; stufe: 1 | 2 | 3; text: string }
  | { art: "absatz"; text: string }
  | { art: "liste"; punkte: { text: string; erledigt: boolean | null }[] };

const LISTENPUNKT = /^\s*[-*]\s+(?:\[( |x|X)\]\s+)?(.*)$/;

export function bloecke(markdown: string): Block[] {
  const ergebnis: Block[] = [];
  let absatz: string[] = [];
  let liste: { text: string; erledigt: boolean | null }[] | null = null;

  const absatzSchliessen = () => {
    if (absatz.length) ergebnis.push({ art: "absatz", text: absatz.join(" ") });
    absatz = [];
  };
  const listeSchliessen = () => {
    if (liste?.length) ergebnis.push({ art: "liste", punkte: liste });
    liste = null;
  };

  for (const roh of markdown.split("\n")) {
    const zeile = roh.trimEnd();
    const kopf = /^(#{1,3})\s+(.*)$/.exec(zeile);
    const punkt = LISTENPUNKT.exec(zeile);
    if (kopf) {
      absatzSchliessen();
      listeSchliessen();
      ergebnis.push({ art: "ueberschrift", stufe: kopf[1].length as 1 | 2 | 3, text: kopf[2] });
    } else if (punkt) {
      absatzSchliessen();
      liste ??= [];
      liste.push({ text: punkt[2], erledigt: punkt[1] === undefined ? null : punkt[1].toLowerCase() === "x" });
    } else if (!zeile.trim()) {
      absatzSchliessen();
      listeSchliessen();
    } else {
      listeSchliessen();
      absatz.push(zeile.trim());
    }
  }
  absatzSchliessen();
  listeSchliessen();
  return ergebnis;
}

/** „**Datum:** 3. Sep" → fett und nicht fett, in Reihenfolge. */
export function stuecke(text: string): Stueck[] {
  return text
    .split(/(\*\*[^*]+\*\*)/)
    .filter(Boolean)
    .map((t) => (t.startsWith("**") && t.endsWith("**") && t.length > 4 ? { text: t.slice(2, -2), fett: true } : { text: t, fett: false }));
}

/** Die ersten Zeilen eines Protokolls als schlichter Text — für die Zeitleiste. */
export function anriss(markdown: string, zeichen = 220): string {
  const text = bloecke(markdown)
    // Überschriften weg: „Zusammenfassung — Aufgaben" mitten im Satz liest
    // sich wie ein Fehler, und der Anriss soll den Inhalt zeigen.
    .filter((b) => b.art !== "ueberschrift")
    .map((b) => (b.art === "liste" ? b.punkte.map((p) => p.text).join(" · ") : b.text))
    .join(" — ")
    .replace(/\*\*/g, "");
  return text.length > zeichen ? `${text.slice(0, zeichen).trimEnd()} …` : text;
}
