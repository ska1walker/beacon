/**
 * Der Sitzplatz — wer gerade an der Tastatur sitzt.
 *
 * Olares installiert Apps pro Nutzer und kennt an einem Entrance nur
 * private, public und internal; einen zweiten Nutzer zusätzlich
 * hereinzulassen gibt es nicht. Wer zu zweit dasselbe CRM benutzt, teilt
 * also einen Olares-Zugang — und `X-Bfl-User` trägt für beide denselben
 * Namen.
 *
 * Der Sitzplatz sagt dem Backend, wem die Arbeit zugeschrieben wird. Er
 * liegt in einem Cookie und damit **pro Browser**: Ihr Rechner ist Ihr
 * Platz, Marcs Rechner ist seiner.
 *
 * **Das ist Zuschreibung, keine Anmeldung.** Wer den geteilten Zugang
 * hat, kann jeden Platz wählen. Die Grenze, die trägt, prüft das
 * Backend: ein Sitzplatz muss Mitglied derselben Organisation sein.
 */

export const SITZPLATZ_COOKIE = "beacon-sitzplatz";

export function liesSitzplatz(): string | null {
  if (typeof document === "undefined") return null;
  const treffer = document.cookie.match(/(?:^|;\s*)beacon-sitzplatz=([^;]*)/);
  return treffer?.[1] || null;
}

export function setzeSitzplatz(id: string | null): void {
  if (id) {
    const ablauf = new Date();
    ablauf.setTime(ablauf.getTime() + 365 * 86400 * 1000);
    document.cookie = `${SITZPLATZ_COOKIE}=${id}; Path=/; Expires=${ablauf.toUTCString()}; SameSite=Lax`;
  } else {
    document.cookie = `${SITZPLATZ_COOKIE}=; Path=/; Max-Age=0; SameSite=Lax`;
  }
}
