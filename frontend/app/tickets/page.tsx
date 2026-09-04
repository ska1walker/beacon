"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Columns3, Table2 } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { api, suchparameter } from "@/lib/api";
import { anzahl, frist } from "@/lib/format";
import type { Mitglied, Ticket, Ticketbrett, Ticketpipeline } from "@/lib/typen";
import { Seitenkopf } from "@/components/seitenkopf";
import { Segmentliste } from "@/components/segmentliste";
import { TicketAnlegen } from "@/components/ticket-anlegen";
import { Prioritaetspille } from "@/components/prioritaet";
import { Fehler, Laedt } from "@/components/zustaende";

type Sicht = "brett" | "tabelle";
type Reiter = "alle" | "meine" | "offen";

const REITER: { wert: Reiter; text: string }[] = [
  { wert: "alle", text: "Alle Tickets" },
  { wert: "meine", text: "Meine offenen" },
  { wert: "offen", text: "Nicht zugewiesen" },
];

export default function TicketsSeite() {
  const router = useRouter();
  const client = useQueryClient();
  const [sicht, setSicht] = useState<Sicht>("brett");
  const [reiter, setReiter] = useState<Reiter>("alle");
  const [offenFormular, setOffenFormular] = useState(false);
  const [ziel, setZiel] = useState<string | null>(null);
  const [pipelineId, setPipelineId] = useState("");

  const pipelines = useQuery({
    queryKey: ["ticket-pipelines"],
    queryFn: () => api.get<Ticketpipeline[]>("/api/tickets/pipelines"),
  });

  const mitglieder = useQuery({
    queryKey: ["mitglieder"],
    queryFn: () => api.get<Mitglied[]>("/api/mitglieder"),
  });

  const parameter = suchparameter({
    pipeline_id: pipelineId,
    mein: reiter === "meine" ? "true" : "",
    ohne_besitzer: reiter === "offen" ? "true" : "",
  });

  const brett = useQuery({
    enabled: sicht === "brett",
    queryKey: ["ticket-brett", parameter],
    queryFn: () => api.get<Ticketbrett>(`/api/tickets/brett${parameter}`),
  });

  const verschieben = useMutation({
    mutationFn: ({ id, stageId }: { id: string; stageId: string }) =>
      api.post<Ticket>(`/api/tickets/${id}/stufe`, { stage_id: stageId }),
    onSuccess: () => client.invalidateQueries({ queryKey: ["ticket-brett"] }),
  });

  const offeneAnzahl = brett.data
    ? brett.data.spalten
        .filter((s) => s.stufe.art !== "abgeschlossen")
        .reduce((n, s) => n + s.anzahl, 0)
    : null;

  return (
    <>
      <Seitenkopf
        titel="Tickets"
        zahl={offeneAnzahl !== null ? `${anzahl(offeneAnzahl, "Anliegen", "Anliegen")} offen` : undefined}
      >
        {(pipelines.data?.length ?? 0) > 1 && (
          <select
            style={{ width: "auto" }}
            aria-label="Ticket-Pipeline"
            value={pipelineId || brett.data?.pipeline.id || ""}
            onChange={(e) => setPipelineId(e.target.value)}
          >
            {pipelines.data!.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name}
              </option>
            ))}
          </select>
        )}
        <div className="sichtwahl" role="group" aria-label="Ansicht">
          <button
            type="button"
            className={`sicht-knopf${sicht === "brett" ? " aktiv" : ""}`}
            aria-pressed={sicht === "brett"}
            title="Brett"
            onClick={() => setSicht("brett")}
          >
            <Columns3 size={15} aria-hidden="true" />
            <span className="nur-vorleser">Brett</span>
          </button>
          <button
            type="button"
            className={`sicht-knopf${sicht === "tabelle" ? " aktiv" : ""}`}
            aria-pressed={sicht === "tabelle"}
            title="Tabelle"
            onClick={() => setSicht("tabelle")}
          >
            <Table2 size={15} aria-hidden="true" />
            <span className="nur-vorleser">Tabelle</span>
          </button>
        </div>
        <button type="button" className="btn btn-primaer" onClick={() => setOffenFormular(true)}>
          Ticket anlegen
        </button>
      </Seitenkopf>

      {offenFormular && (
        <TicketAnlegen
          beiSchliessen={() => setOffenFormular(false)}
          beiErfolg={(id) => {
            setOffenFormular(false);
            router.push(`/tickets/${id}`);
          }}
        />
      )}

      {sicht === "tabelle" ? (
        <Segmentliste
          entity="tickets"
          basisPfad="/tickets"
          suchePlatzhalter="Betreff, Beschreibung oder Firma"
          leerTitel="Kein Ticket gefunden"
          leerText="Entweder ist der Filter zu eng, oder es liegt gerade nichts an."
          stapelfelder={[
            { schluessel: "prioritaet", text: "Dringlichkeit" },
            { schluessel: "owner_id", text: "Zuständig" },
            { schluessel: "kategorie", text: "Kategorie" },
          ]}
        />
      ) : (
        <>
          {/* Dieselben drei Fragen, die eine Warteschlange täglich stellt. */}
          <div className="ansichtsleiste" role="tablist" aria-label="Ansichten">
            {REITER.map((r) => (
              <button
                key={r.wert}
                type="button"
                role="tab"
                aria-selected={reiter === r.wert}
                className={`ansicht-reiter${reiter === r.wert ? " aktiv" : ""}`}
                onClick={() => setReiter(r.wert)}
                disabled={r.wert === "meine" && (mitglieder.data?.length ?? 0) === 0}
              >
                {r.text}
              </button>
            ))}
          </div>

          {brett.isPending && <Laedt />}
          {brett.isError && <Fehler text={(brett.error as Error).message} />}
          {verschieben.isError && (
            <div style={{ padding: "0 var(--am-raum-8)" }}>
              <Fehler text={(verschieben.error as Error).message} />
            </div>
          )}

          {brett.data && (
            <div className="board">
              {brett.data.spalten.map((spalte) => (
                <div
                  key={spalte.stufe.id}
                  className="board-spalte"
                  data-ziel={ziel === spalte.stufe.id ? "true" : undefined}
                  onDragOver={(e) => {
                    // Ohne preventDefault lehnt der Browser das Ablegen ab.
                    e.preventDefault();
                    setZiel(spalte.stufe.id);
                  }}
                  onDragLeave={() => setZiel((z) => (z === spalte.stufe.id ? null : z))}
                  onDrop={(e) => {
                    e.preventDefault();
                    setZiel(null);
                    const id = e.dataTransfer.getData("text/plain");
                    if (id) verschieben.mutate({ id, stageId: spalte.stufe.id });
                  }}
                >
                  <div className="board-spalte-kopf">
                    <div className="board-spalte-name">
                      <span>{spalte.stufe.name}</span>
                      <span className="board-spalte-anzahl">{spalte.anzahl}</span>
                    </div>
                    {spalte.stufe.art === "wartet_auf_kontakt" && (
                      <div className="board-spalte-gewichtet">Frist pausiert</div>
                    )}
                  </div>

                  {spalte.tickets.map((t) => (
                    <Ticketkarte key={t.id} ticket={t} />
                  ))}

                  {spalte.anzahl > spalte.tickets.length && (
                    <p className="board-mehr">
                      {spalte.anzahl - spalte.tickets.length} weitere — über die Tabelle sichtbar
                    </p>
                  )}
                </div>
              ))}
            </div>
          )}
        </>
      )}
    </>
  );
}

/** Eine Karte trägt, was man zum Priorisieren braucht — nicht mehr. */
function Ticketkarte({ ticket }: { ticket: Ticket }) {
  return (
    <Link
      href={`/tickets/${ticket.id}`}
      className="deal-karte"
      draggable
      onDragStart={(e) => e.dataTransfer.setData("text/plain", ticket.id)}
    >
      <div className="ticket-karte-kopf">
        <span className="ticket-kennung">{ticket.kennung}</span>
        <Prioritaetspille prioritaet={ticket.prioritaet} />
      </div>
      <div className="deal-karte-name">{ticket.betreff}</div>
      <div className="deal-karte-firma">
        {ticket.firma_name ?? ticket.kontakt_name ?? "Ohne Bezug"}
      </div>
      <div className="deal-karte-fuss">
        <span className="deal-karte-datum">{ticket.besitzer_name ?? "Nicht zugewiesen"}</span>
        {ticket.offen && (
          <span className="deal-karte-datum" data-ueberfaellig={ticket.ueberfaellig ? "true" : undefined}>
            {frist(ticket.faellig_am)}
          </span>
        )}
      </div>
    </Link>
  );
}

