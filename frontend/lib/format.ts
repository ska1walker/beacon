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
