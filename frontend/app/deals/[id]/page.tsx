"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { use, useState } from "react";
import { api, suchparameter } from "@/lib/api";
import {
  ANGEBOT_STATUS_ART,
  ANGEBOT_STATUS_TEXT,
  datum,
  euro,
  PRODUKT_TEXT,
  prozent,
} from "@/lib/format";
import type { Board, Deal, Quote } from "@/lib/typen";
import { Seitenkopf } from "@/components/seitenkopf";
import { Dealstufe } from "@/components/stufe";
import { Zeitleiste } from "@/components/zeitleiste";
import { KiKnopf } from "@/components/ki-knopf";
import { Fehler, Laedt } from "@/components/zustaende";
import { AngebotAnlegen } from "@/components/angebot-anlegen";

export default function DealSeite({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const client = useQueryClient();
  const [angebotOffen, setAngebotOffen] = useState(false);

  const deal = useQuery({
    queryKey: ["deal", id],
    queryFn: () => api.get<Deal>(`/api/deals/${id}`),
  });

  const angebote = useQuery({
    queryKey: ["angebote", "deal", id],
    queryFn: () => api.get<Quote[]>(`/api/quotes${suchparameter({ deal_id: id })}`),
  });

  const board = useQuery({
    queryKey: ["board"],
    queryFn: () => api.get<Board>("/api/board"),
  });

  const verschieben = useMutation({
    mutationFn: (stageId: string) => api.post<Deal>(`/api/deals/${id}/stage`, { stage_id: stageId }),
    onSuccess: () => {
      client.invalidateQueries({ queryKey: ["deal", id] });
      client.invalidateQueries({ queryKey: ["aktivitaeten"] });
      client.invalidateQueries({ queryKey: ["board"] });
    },
  });

  if (deal.isPending) return <Laedt />;
  if (deal.isError) return <Fehler text={(deal.error as Error).message} />;

  const d = deal.data!;
  const ueberfaellig =
    d.stage_kind === "open" && d.close_date && new Date(d.close_date) < new Date();

  return (
    <>
      <Seitenkopf
        titel={d.name}
        zahl={`${euro(d.amount_cents)} · ${PRODUKT_TEXT[d.product]}`}
        pfad={{ text: "← Pipeline", href: "/deals" }}
      >
        <KiKnopf
          pfad={`/api/ki/deals/${id}/naechster-schritt`}
          text="Nächsten Schritt vorschlagen"
          invalidiert={["deal", id]}
        />
      </Seitenkopf>

      {angebotOffen && (
        <AngebotAnlegen dealId={id} beiSchliessen={() => setAngebotOffen(false)} />
      )}

      <div className="datensatz">
        <div>
          <section className="block">
            <div className="block-kopf">
              <h2>Über dieses Geschäft</h2>
              <Dealstufe name={d.stage_name} art={d.stage_kind} />
            </div>
            <div className="block-inhalt">
              <dl>
                <div className="eigenschaft">
                  <dt>Firma</dt>
                  <dd>
                    {d.company_id ? (
                      <Link
                        href={`/firmen/${d.company_id}`}
                        style={{ textDecoration: "underline", textUnderlineOffset: "2px" }}
                      >
                        {d.company_name}
                      </Link>
                    ) : (
                      "—"
                    )}
                  </dd>
                </div>
                <div className="eigenschaft">
                  <dt>Betrag netto</dt>
                  <dd>{euro(d.amount_cents)}</dd>
                </div>
                <div className="eigenschaft">
                  <dt>Wahrscheinlichkeit</dt>
                  <dd>{prozent(d.probability)}</dd>
                </div>
                <div className="eigenschaft">
                  <dt>Gewichtet</dt>
                  <dd>{euro(Math.round(d.amount_cents * (d.probability ?? 0)))}</dd>
                </div>
                <div className="eigenschaft">
                  <dt>Abschluss geplant</dt>
                  <dd style={ueberfaellig ? { color: "var(--am-fehler)" } : undefined}>
                    {datum(d.close_date)}
                    {ueberfaellig && " · überfällig"}
                  </dd>
                </div>
                <div className="eigenschaft">
                  <dt>Servicetage</dt>
                  <dd>{d.service_days ?? "—"}</dd>
                </div>
                {d.lost_reason && (
                  <div className="eigenschaft">
                    <dt>Grund für die Absage</dt>
                    <dd>{d.lost_reason}</dd>
                  </div>
                )}
              </dl>

              {d.next_step && (
                <div className="hinweis" style={{ marginTop: "var(--am-raum-4)" }}>
                  <span>
                    <strong>Nächster Schritt:</strong> {d.next_step}
                  </span>
                </div>
              )}
            </div>
          </section>

          <section className="block">
            <div className="block-kopf">
              <h2>Stufe wechseln</h2>
            </div>
            <div className="block-inhalt">
              <div className="btn-reihe">
                {board.data?.pipeline.stages.map((s) => (
                  <button
                    key={s.id}
                    type="button"
                    className={`btn btn-klein ${s.id === d.stage_id ? "btn-primaer" : "btn-sekundaer"}`}
                    disabled={s.id === d.stage_id || verschieben.isPending}
                    onClick={() => verschieben.mutate(s.id)}
                  >
                    {s.name}
                  </button>
                ))}
              </div>
              {verschieben.isError && <Fehler text={(verschieben.error as Error).message} />}
            </div>
          </section>

          {d.ai_summary && (
            <section className="block">
              <div className="block-inhalt">
                <div className="ki-block">
                  <div className="ki-block-kopf">Vorschlag der KI</div>
                  <p className="ki-block-text">{d.ai_summary}</p>
                </div>
              </div>
            </section>
          )}
        </div>

        <Zeitleiste bezug={{ deal_id: id }} />

        <div>
          <section className="block">
            <div className="block-kopf">
              <h2>Angebote</h2>
              <button
                type="button"
                className="btn btn-still btn-klein"
                onClick={() => setAngebotOffen(true)}
              >
                Anlegen
              </button>
            </div>
            <div className="block-inhalt">
              {angebote.data?.length === 0 && (
                <p style={{ fontSize: "0.875rem", color: "var(--am-text-gedaempft)" }}>
                  Noch kein Angebot.
                </p>
              )}
              {angebote.data?.map((a) => (
                <Link
                  key={a.id}
                  href={`/angebote/${a.id}`}
                  className="deal-karte"
                  style={{ marginBottom: "var(--am-raum-2)" }}
                >
                  <div className="deal-karte-name mono">{a.number}</div>
                  <div className="deal-karte-fuss">
                    <span className="deal-karte-betrag">{euro(a.gross_cents)}</span>
                    <span className="stufe" data-art={ANGEBOT_STATUS_ART[a.status]}>
                      {ANGEBOT_STATUS_TEXT[a.status]}
                    </span>
                  </div>
                </Link>
              ))}
            </div>
          </section>

          <section className="block">
            <div className="block-kopf">
              <h2>Verlauf des Geschäfts</h2>
            </div>
            <div className="block-inhalt">
              <dl>
                <div className="eigenschaft">
                  <dt>Angelegt</dt>
                  <dd>{datum(d.created_at)}</dd>
                </div>
                <div className="eigenschaft">
                  <dt>Zuletzt bewegt</dt>
                  <dd>{datum(d.updated_at)}</dd>
                </div>
                <div className="eigenschaft">
                  <dt>Geschlossen</dt>
                  <dd>{d.closed_at ? datum(d.closed_at) : "offen"}</dd>
                </div>
              </dl>
            </div>
          </section>
        </div>
      </div>
    </>
  );
}
