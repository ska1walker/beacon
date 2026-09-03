"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { api } from "@/lib/api";
import { datum, euro } from "@/lib/format";
import type { Board, Task } from "@/lib/typen";
import { Seitenkopf } from "@/components/seitenkopf";
import { Fehler, Laedt } from "@/components/zustaende";

export default function StartSeite() {
  const board = useQuery({
    queryKey: ["board"],
    queryFn: () => api.get<Board>("/api/board"),
  });

  const aufgaben = useQuery({
    queryKey: ["aufgaben", "open"],
    queryFn: () => api.get<Task[]>("/api/tasks?status=open"),
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
      <Seitenkopf titel="Start" zahl={`${anzahlOffen} offene Geschäfte`} />

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
        <section className="block">
          <div className="block-kopf">
            <h2>Was ansteht</h2>
            <Link href="/aufgaben" style={{ fontSize: "0.8125rem" }}>
              alle Aufgaben
            </Link>
          </div>
          <div className="block-inhalt">
            {aufgaben.data?.length === 0 && (
              <p style={{ fontSize: "0.875rem", color: "var(--am-text-gedaempft)" }}>
                Nichts offen.
              </p>
            )}
            <dl>
              {aufgaben.data?.slice(0, 6).map((a) => (
                <div className="eigenschaft" key={a.id}>
                  <dt>{a.due_at ? datum(a.due_at) : "ohne Frist"}</dt>
                  <dd>{a.title}</dd>
                </div>
              ))}
            </dl>
          </div>
        </section>

        {ueberfaellig.length > 0 && (
          <section className="block">
            <div className="block-kopf">
              <h2>Überfällige Geschäfte</h2>
            </div>
            <div className="block-inhalt">
              {ueberfaellig.map((d) => (
                <Link
                  key={d.id}
                  href={`/deals/${d.id}`}
                  className="deal-karte"
                  style={{ marginBottom: "var(--am-raum-2)" }}
                >
                  <div className="deal-karte-name">{d.name}</div>
                  <div className="deal-karte-firma">{d.company_name ?? "Ohne Firma"}</div>
                  <div className="deal-karte-fuss">
                    <span className="deal-karte-betrag">{euro(d.amount_cents)}</span>
                    <span className="deal-karte-datum" data-ueberfaellig="true">
                      {datum(d.close_date)}
                    </span>
                  </div>
                </Link>
              ))}
            </div>
          </section>
        )}
      </div>
    </>
  );
}
