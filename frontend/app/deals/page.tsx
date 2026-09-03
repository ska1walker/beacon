"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useState } from "react";
import { api } from "@/lib/api";
import { datum, euro } from "@/lib/format";
import type { Board, Deal } from "@/lib/typen";
import { Seitenkopf } from "@/components/seitenkopf";
import { Fehler, Laedt } from "@/components/zustaende";
import { DealAnlegen } from "@/components/deal-anlegen";

export default function BoardSeite() {
  const client = useQueryClient();
  const [ziel, setZiel] = useState<string | null>(null);
  const [formularOffen, setFormularOffen] = useState(false);

  const abfrage = useQuery({
    queryKey: ["board"],
    queryFn: () => api.get<Board>("/api/board"),
  });

  const verschieben = useMutation({
    mutationFn: ({ dealId, stageId }: { dealId: string; stageId: string }) =>
      api.post<Deal>(`/api/deals/${dealId}/stage`, { stage_id: stageId }),
    onSuccess: () => client.invalidateQueries({ queryKey: ["board"] }),
  });

  if (abfrage.isPending) return <Laedt />;
  if (abfrage.isError) return <Fehler text={(abfrage.error as Error).message} />;

  const board = abfrage.data!;
  const offen = board.columns.filter((s) => s.stage.kind === "open");
  const summeOffen = offen.reduce((s, c) => s + c.sum_amount_cents, 0);
  const gewichtetOffen = offen.reduce((s, c) => s + c.weighted_amount_cents, 0);

  return (
    <>
      <Seitenkopf
        titel={board.pipeline.name}
        zahl={`${euro(summeOffen)} offen · ${euro(gewichtetOffen)} gewichtet`}
      >
        <button type="button" className="btn btn-primaer" onClick={() => setFormularOffen(true)}>
          Deal anlegen
        </button>
      </Seitenkopf>

      {formularOffen && (
        <DealAnlegen
          stufen={board.pipeline.stages}
          beiSchliessen={() => setFormularOffen(false)}
          beiErfolg={() => {
            setFormularOffen(false);
            client.invalidateQueries({ queryKey: ["board"] });
          }}
        />
      )}

      {verschieben.isError && (
        <div style={{ padding: "0 var(--am-raum-8)" }}>
          <Fehler text={(verschieben.error as Error).message} />
        </div>
      )}

      <div className="board">
        {board.columns.map((spalte) => (
          <div
            key={spalte.stage.id}
            className="board-spalte"
            data-ziel={ziel === spalte.stage.id ? "true" : undefined}
            onDragOver={(e) => {
              // Ohne preventDefault lehnt der Browser das Ablegen ab —
              // der Ziehvorgang endet dann wortlos im Nichts.
              e.preventDefault();
              setZiel(spalte.stage.id);
            }}
            onDragLeave={() => setZiel((z) => (z === spalte.stage.id ? null : z))}
            onDrop={(e) => {
              e.preventDefault();
              setZiel(null);
              const dealId = e.dataTransfer.getData("text/plain");
              if (dealId) verschieben.mutate({ dealId, stageId: spalte.stage.id });
            }}
          >
            <div className="board-spalte-kopf">
              <div className="board-spalte-name">
                <span>{spalte.stage.name}</span>
                <span className="board-spalte-anzahl">{spalte.deals.length}</span>
              </div>
              <div className="board-spalte-summe">{euro(spalte.sum_amount_cents)}</div>
              {spalte.stage.kind === "open" && (
                <div className="board-spalte-gewichtet">
                  gewichtet {euro(spalte.weighted_amount_cents)}
                </div>
              )}
            </div>

            {spalte.deals.map((deal) => (
              <Link
                key={deal.id}
                href={`/deals/${deal.id}`}
                className="deal-karte"
                draggable
                onDragStart={(e) => e.dataTransfer.setData("text/plain", deal.id)}
              >
                <div className="deal-karte-name">{deal.name}</div>
                <div className="deal-karte-firma">{deal.company_name ?? "Ohne Firma"}</div>
                <div className="deal-karte-fuss">
                  <span className="deal-karte-betrag">{euro(deal.amount_cents)}</span>
                  <span
                    className="deal-karte-datum"
                    data-ueberfaellig={
                      spalte.stage.kind === "open" &&
                      deal.close_date &&
                      new Date(deal.close_date) < new Date()
                        ? "true"
                        : undefined
                    }
                  >
                    {datum(deal.close_date)}
                  </span>
                </div>
              </Link>
            ))}
          </div>
        ))}
      </div>
    </>
  );
}
