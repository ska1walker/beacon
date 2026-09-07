"use client";

import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { euro } from "@/lib/format";
import type { Board } from "@/lib/typen";
import { Seitenkopf } from "@/components/seitenkopf";
import { Fehler, Laedt } from "@/components/zustaende";
import { Tagesbriefing } from "@/components/briefing";
import { HeuteVorbereitet } from "@/components/podcast";

export default function StartSeite() {
  const board = useQuery({
    queryKey: ["board"],
    queryFn: () => api.get<Board>("/api/board"),
  });

  if (board.isPending) return <Laedt />;
  if (board.isError) return <Fehler text={(board.error as Error).message} />;

  const spalten = board.data!.columns;
  const offen = spalten.filter((s) => s.stage.kind === "open");
  const gewonnen = spalten.find((s) => s.stage.kind === "won");

  const summeOffen = offen.reduce((s, c) => s + c.sum_amount_cents, 0);
  const gewichtet = offen.reduce((s, c) => s + c.weighted_amount_cents, 0);
  const anzahlOffen = offen.reduce((s, c) => s + c.deals.length, 0);

  // Überfällig heißt: geplanter Abschluss liegt zurück und der Deal ist
  // noch offen. Das ist die Zahl, die morgens zählt.
  const heute = new Date();
  const ueberfaellig = offen
    .flatMap((c) => c.deals)
    .filter((d) => d.close_date && new Date(d.close_date) < heute);

  return (
    <>
      <Seitenkopf titel="Start" zahl={`${anzahlOffen} offene Leads`} />

      <dl className="kennzahlen">
        <div className="kennzahl">
          <dt>Offene Pipeline</dt>
          <dd>{euro(summeOffen)}</dd>
          <div className="kennzahl-fuss">{anzahlOffen} Geschäfte</div>
        </div>
        <div className="kennzahl">
          <dt>Gewichtet</dt>
          <dd>{euro(gewichtet)}</dd>
          <div className="kennzahl-fuss">nach Stufenwahrscheinlichkeit</div>
        </div>
        <div className="kennzahl">
          <dt>Gewonnen</dt>
          <dd>{euro(gewonnen?.sum_amount_cents ?? 0)}</dd>
          <div className="kennzahl-fuss">{gewonnen?.deals.length ?? 0} Abschlüsse</div>
        </div>
        <div className="kennzahl">
          <dt>Überfällig</dt>
          <dd>{ueberfaellig.length}</dd>
          <div className="kennzahl-fuss">Abschlussdatum verstrichen</div>
        </div>
      </dl>

      <div className="datensatz" style={{ gridTemplateColumns: "minmax(0, 1fr)" }}>
        <HeuteVorbereitet />
        <Tagesbriefing />
      </div>
    </>
  );
}
