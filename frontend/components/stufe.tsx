import { STUFEN_TEXT } from "@/lib/format";
import type { LifecycleStage, StageKind } from "@/lib/typen";

/** Lebenszyklus-Stufe einer Firma oder eines Kontakts. */
export function Stufenpille({ stufe }: { stufe: LifecycleStage }) {
  return (
    <span className="stufe" data-stufe={stufe}>
      {STUFEN_TEXT[stufe] ?? stufe}
    </span>
  );
}

/** Stufe eines Deals — die Art (offen/gewonnen/verloren) färbt. */
export function Dealstufe({ name, art }: { name: string | null; art: StageKind | null }) {
  return (
    <span className="stufe" data-art={art ?? "open"}>
      {name ?? "—"}
    </span>
  );
}
