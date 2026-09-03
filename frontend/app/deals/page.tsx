"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useState } from "react";
import { api, suchparameter } from "@/lib/api";
import { datum, euro } from "@/lib/format";
import type { Board, Deal, Mitglied, Pipeline, Wer } from "@/lib/typen";
import { Seitenkopf } from "@/components/seitenkopf";
import { Fehler, Laedt } from "@/components/zustaende";
import { DealAnlegen } from "@/components/deal-anlegen";

export default function BoardSeite() {
  const client = useQueryClient();
  const [ziel, setZiel] = useState<string | null>(null);
  const [formularOffen, setFormularOffen] = useState(false);
  const [nurMeine, setNurMeine] = useState(false);
  // Leer = Standard-Pipeline. Die Wahl liegt in der Seite, nicht in der
  // Adresse: Wer zurückkommt, sieht wieder den Standard — das ist der
  // Normalfall, nicht die zweite Pipeline.
  const [pipelineId, setPipelineId] = useState("");

  const pipelines = useQuery({
    queryKey: ["pipelines"],
    queryFn: () => api.get<Pipeline[]>("/api/pipelines"),
  });

  const abfrage = useQuery({
    queryKey: ["board", pipelineId],
    queryFn: () => api.get<Board>(`/api/board${suchparameter({ pipeline_id: pipelineId })}`),
  });

  const wer = useQuery({
    queryKey: ["wer"],
    queryFn: () => api.get<Wer>("/api/mitglieder/wer"),
  });

  const mitglieder = useQuery({
    queryKey: ["mitglieder"],
    queryFn: () => api.get<Mitglied[]>("/api/mitglieder"),
  });

  const verschieben = useMutation({
    mutationFn: ({ dealId, stageId }: { dealId: string; stageId: string }) =>
      api.post<Deal>(`/api/deals/${dealId}/stage`, { stage_id: stageId }),
    onSuccess: () => client.invalidateQueries({ queryKey: ["board"] }),
  });

  if (abfrage.isPending) return <Laedt />;
  if (abfrage.isError) return <Fehler text={(abfrage.error as Error).message} />;

  const rohboard = abfrage.data!;
  // Gefiltert wird in der Oberfläche, nicht in der Abfrage: Die Spalten-
  // summen sollen sich mit dem Filter mitändern, und dafür muss dieselbe
  // Rechnung über den gefilterten Bestand laufen.
  const board = nurMeine && wer.data
    ? {
        ...rohboard,
        columns: rohboard.columns.map((spalte) => {
          const meine = spalte.deals.filter((d) => d.owner_id === wer.data!.user_id);
          const summe = meine.reduce((s, d) => s + d.amount_cents, 0);
          return {
            ...spalte,
            deals: meine,
            sum_amount_cents: summe,
            weighted_amount_cents: Math.round(summe * spalte.stage.probability),
          };
        }),
      }
    : rohboard;

  const offen = board.columns.filter((s) => s.stage.kind === "open");
  const summeOffen = offen.reduce((s, c) => s + c.sum_amount_cents, 0);
  const gewichtetOffen = offen.reduce((s, c) => s + c.weighted_amount_cents, 0);

  return (
    <>
      <Seitenkopf
        titel={board.pipeline.name}
        zahl={`${euro(summeOffen)} offen · ${euro(gewichtetOffen)} gewichtet`}
      >
        {(pipelines.data?.length ?? 0) > 1 && (
          <select
            className="input"
            style={{ width: "auto" }}
            aria-label="Pipeline"
            value={pipelineId || board.pipeline.id}
            onChange={(e) => setPipelineId(e.target.value)}
          >
            {pipelines.data!.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name}
              </option>
            ))}
          </select>
        )}
        {(mitglieder.data?.length ?? 0) > 1 && (
          <button
            type="button"
            className={`btn btn-klein ${nurMeine ? "btn-primaer" : "btn-sekundaer"}`}
            onClick={() => setNurMeine((m) => !m)}
            aria-pressed={nurMeine}
          >
            {nurMeine ? `Nur ${wer.data?.display_name ?? "meine"}` : "Alle"}
          </button>
        )}
        <button type="button" className="btn btn-primaer" onClick={() => setFormularOffen(true)}>
          Deal anlegen
        </button>
      </Seitenkopf>

      {formularOffen && (
        <DealAnlegen
          pipelineId={board.pipeline.id}
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
