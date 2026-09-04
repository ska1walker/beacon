import { PRIORITAET_TEXT } from "@/lib/format";

/**
 * Die Dringlichkeit — Punkt **und** Wort.
 *
 * Farbe allein trägt die Aussage nicht: Wer Rot und Gelb nicht
 * unterscheidet, sieht sonst vier gleiche Karten. Rot bleibt dem
 * Ernstfall vorbehalten, und ein dringendes Ticket ist einer.
 */
export function Prioritaetspille({ prioritaet }: { prioritaet: string }) {
  return (
    <span className="prio" data-prio={prioritaet}>
      <span className="prio-punkt" aria-hidden="true" />
      {PRIORITAET_TEXT[prioritaet] ?? prioritaet}
    </span>
  );
}
