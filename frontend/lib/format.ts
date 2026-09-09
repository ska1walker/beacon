import type { StageKind } from "@/lib/typen";
// Formatieren an einer Stelle. Beträge kommen als Cent aus der API — wer
// sie irgendwo durch 100 teilt, tut es hier oder gar nicht.

// Zwei Formate, und der Unterschied ist keine Geschmacksfrage.
//
// In Listen und Summen der Pipeline stören Cent-Beträge: „14.500 €" liest
// sich, „14.500,00 €" muss man entziffern. Auf einem Angebot dagegen ist
// die gerundete Zahl schlicht falsch — 3.575,80 € sind nicht 3.576 €, und
// das Blatt geht an einen Kunden.
const WAEHRUNG = new Intl.NumberFormat("de-DE", {
  style: "currency",
  currency: "EUR",
  maximumFractionDigits: 0,
});

const WAEHRUNG_GENAU = new Intl.NumberFormat("de-DE", {
  style: "currency",
  currency: "EUR",
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

const DATUM = new Intl.DateTimeFormat("de-DE", {
  day: "2-digit",
  month: "2-digit",
  year: "numeric",
});

const DATUM_ZEIT = new Intl.DateTimeFormat("de-DE", {
  day: "2-digit",
  month: "2-digit",
  year: "numeric",
  hour: "2-digit",
  minute: "2-digit",
});

export function euro(cents: number): string {
  return WAEHRUNG.format(cents / 100);
}

/** Auf Cent genau. Für alles, was ein Kunde in die Hand bekommt. */
export function euroGenau(cents: number): string {
  return WAEHRUNG_GENAU.format(cents / 100);
}

export function datum(wert: string | null | undefined): string {
  if (!wert) return "—";
  return DATUM.format(new Date(wert));
}

export function datumZeit(wert: string | null | undefined): string {
  if (!wert) return "—";
  return DATUM_ZEIT.format(new Date(wert));
}

export function prozent(anteil: number | null | undefined): string {
  if (anteil === null || anteil === undefined) return "—";
  return `${Math.round(anteil * 100)} %`;
}

export function personName(vorname: string | null, nachname: string | null): string {
  const name = [vorname, nachname].filter(Boolean).join(" ").trim();
  return name || "Ohne Namen";
}

export function initialen(vorname: string | null, nachname: string | null): string {
  const a = vorname?.[0] ?? "";
  const b = nachname?.[0] ?? "";
  return (a + b).toUpperCase() || "?";
}

/**
 * Initialen aus einem ganzen Namen: „Kai Böhm" → „KB", „kaivostudio" → „KA".
 *
 * Zwei Zeichen, nie drei — im Kreis wird das dritte unleserlich. Bei einem
 * einzelnen Wort werden die ersten beiden Buchstaben genommen; ein
 * einzelnes „K" sähe aus, als fehle etwas. Trennzeichen wie in
 * „marc-bayer" zählen als Wortgrenze, denn das ist die Kennung einer
 * Person ohne eigenen Zugang.
 */
export function initialenAusName(name: string | null | undefined): string {
  const sauber = (name ?? "").trim();
  if (!sauber) return "?";
  const teile = sauber.split(/[\s._-]+/).filter(Boolean);
  if (teile.length >= 2) return (teile[0][0] + teile[1][0]).toUpperCase();
  return sauber.slice(0, 2).toUpperCase();
}

export const STUFEN_TEXT: Record<string, string> = {
  lead: "Kontakt",
  qualified: "Qualifiziert",
  opportunity: "Chance",
  customer: "Kunde",
  partner: "Partner",
  disqualified: "Verworfen",
};

export const PRODUKT_TEXT: Record<string, string> = {
  assistent: "Assistent",
  analyst: "Analyst",
  experte: "Experte",
  service: "Leistung",
  sonstiges: "Sonstiges",
};

export const AKTIVITAET_TEXT: Record<string, string> = {
  note: "Notiz",
  call: "Anruf",
  email: "E-Mail",
  meeting: "Termin",
  task: "Aufgabe",
  stage_change: "Stufenwechsel",
  quote: "Angebot",
  ai: "KI",
  system: "System",
};

export const ANGEBOT_STATUS_TEXT: Record<string, string> = {
  draft: "Entwurf",
  sent: "Verschickt",
  accepted: "Angenommen",
  rejected: "Abgelehnt",
  expired: "Frist abgelaufen",
};

/** Wie die Stufenpille: Farbe trägt die Aussage nie allein. */
export const ANGEBOT_STATUS_ART: Record<string, "open" | "won" | "lost"> = {
  draft: "open",
  sent: "open",
  accepted: "won",
  rejected: "lost",
  expired: "lost",
};

/**
 * Ein/Mehrzahl. Klein, aber „1 Punkte" liest sich wie ein Fehler — und
 * genau so wirkt es auch auf den Rest der Anwendung.
 */
export function anzahl(n: number, einzahl: string, mehrzahl: string): string {
  return `${n} ${n === 1 ? einzahl : mehrzahl}`;
}

/** Wie ein Operator in der Filterleiste heißt. */
export const OPERATOR_TEXT: Record<string, string> = {
  ist: "ist",
  ist_nicht: "ist nicht",
  enthaelt: "enthält",
  enthaelt_nicht: "enthält nicht",
  beginnt_mit: "beginnt mit",
  ist_eines_von: "ist eines von",
  hat_eines_von: "hat eines von",
  hat_alle_von: "hat alle von",
  hat_keines_von: "hat keines von",
  hat_nicht_alle_von: "hat nicht alle von",
  groesser: "größer als",
  kleiner: "kleiner als",
  nach: "nach dem",
  vor: "vor dem",
  letzte_tage: "in den letzten … Tagen",
  aelter_als_tage: "älter als … Tage",
  leer: "ist leer",
  nicht_leer: "ist nicht leer",
  ist_wahr: "ist ja",
  ist_falsch: "ist nein",
};

/** Operatoren, die ohne Wert auskommen. */
export const OHNE_WERT = new Set(["leer", "nicht_leer", "ist_wahr", "ist_falsch"]);

/** Wie die Dringlichkeit eines Tickets heißt — und in welcher Reihenfolge. */
export const EINWILLIGUNG_TEXT: Record<string, string> = {
  keine: "keine",
  angefragt: "angefragt",
  bestaetigt: "bestätigt",
  bestandskunde: "Bestandskunde",
  abgemeldet: "abgemeldet",
};

export const KAMPAGNE_STATUS_TEXT: Record<string, string> = {
  entwurf: "Entwurf",
  laeuft: "läuft",
  abgeschlossen: "abgeschlossen",
  abgebrochen: "abgebrochen",
};

export const KAMPAGNE_STATUS_ART: Record<string, string | undefined> = {
  entwurf: undefined,
  laeuft: "open",
  abgeschlossen: "won",
  abgebrochen: "lost",
};

export const PRIORITAET_TEXT: Record<string, string> = {
  dringend: "Dringend",
  hoch: "Hoch",
  mittel: "Mittel",
  niedrig: "Niedrig",
};

export const QUELLE_TEXT: Record<string, string> = {
  manuell: "Von Hand",
  email: "E-Mail",
  telefon: "Telefon",
  insilo: "Insilo",
  formular: "Formular",
  api: "Schnittstelle",
  bot: "Bot",
};

/**
 * „in 3 Stunden" oder „seit 2 Tagen überfällig".
 *
 * Eine Frist als Datum zu zeigen zwingt zum Kopfrechnen. Der Abstand ist
 * die Angabe, nach der man handelt.
 */
export function frist(wert: string | null | undefined, jetzt: Date = new Date()): string {
  if (!wert) return "ohne Frist";
  const ziel = new Date(wert);
  const minuten = Math.round((ziel.getTime() - jetzt.getTime()) / 60000);
  const spanne = (m: number): string => {
    const abs = Math.abs(m);
    if (abs < 60) return `${abs} Min.`;
    if (abs < 60 * 24) return anzahl(Math.round(abs / 60), "Stunde", "Stunden");
    return anzahl(Math.round(abs / (60 * 24)), "Tag", "Tagen");
  };
  return minuten >= 0 ? `in ${spanne(minuten)}` : `seit ${spanne(minuten)} überfällig`;
}

/** Wie eine Aufgabenart heißt. Ein Anruf wird anders erledigt als eine Mail. */
export const AUFGABEN_ART_TEXT: Record<string, string> = {
  todo: "To-do",
  anruf: "Anruf",
  email: "E-Mail",
  termin: "Termin",
};

/** Die Phase innerhalb von „offen“ — „angefangen“ ist kein Zustand von status. */
export const AUFGABEN_PHASE_TEXT: Record<string, string> = {
  nicht_gestartet: "Nicht gestartet",
  in_arbeit: "In Arbeit",
  wartet: "Wartet",
};

/**
 * Ein Firmenname, auf das Vergleichbare eingedampft.
 *
 * „Hanseatic Legal Partner mbB" und „Hanseatic Legal Partner" sind
 * dieselbe Kanzlei; eine Signatur schreibt die Rechtsform hin, der
 * Bestand oft nicht. Wer stur zeichenweise vergleicht, legt dieselbe
 * Firma ein zweites Mal an — und der Kontakt hängt danach an der
 * falschen.
 *
 * Bewusst zurückhaltend: Kleinschreibung, Satzzeichen weg, und nur
 * **hinten** stehende Rechtsformen. „Partner" bleibt stehen, es gehört
 * bei Kanzleien zum Namen. Ein Abgleich, der zu viel wegwirft, führt
 * zwei verschiedene Firmen zusammen — das ist der teurere Fehler.
 */
const RECHTSFORMEN = new Set([
  "gmbh", "mbh", "mbb", "ug", "ag", "kg", "kgaa", "ohg", "gbr", "se", "ev",
  "ek", "partg", "partgmbb", "co", "haftungsbeschraenkt",
  "ltd", "limited", "inc", "llc", "llp", "plc", "bv", "nv", "sa", "sarl",
  "srl", "spa", "oy", "ab", "as",
]);

export function firmenschluessel(name: string): string {
  const worte = name
    .toLowerCase()
    .replace(/[.,()]/g, " ")
    .replace(/&/g, " ")
    .split(/\s+/)
    .filter(Boolean);
  while (worte.length > 1 && RECHTSFORMEN.has(worte[worte.length - 1])) worte.pop();
  return worte.join(" ");
}

/**
 * Wie ein Vorgang in der Pipeline heißt — Lead oder Deal.
 *
 * Solange er offen ist, ist er ein **Lead**: eine Möglichkeit, mehr
 * nicht. Erst der Abschluss macht daraus einen **Deal**. Das ist keine
 * Wortklauberei — wer alles „Deal" nennt, redet sich eine Pipeline
 * schön, in der noch nichts unterschrieben ist.
 *
 * Ein verlorener Vorgang bleibt ein Lead. Er ist nie einer geworden.
 */
export function vorgangswort(
  art: StageKind | null | undefined,
  mehrzahl = false,
): string {
  const wort = art === "won" ? "Deal" : "Lead";
  return mehrzahl ? `${wort}s` : wort;
}

/** Dateigröße, wie ein Mensch sie liest.

    Gerundet auf eine Nachkommastelle ab einem Megabyte: „2,4 MB" sagt,
    was man wissen will, „2.411.724 Bytes" nicht. */
export function dateigroesse(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1).replace(".", ",")} MB`;
}
