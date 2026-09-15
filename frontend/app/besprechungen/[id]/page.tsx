"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ExternalLink } from "lucide-react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useState } from "react";
import { api } from "@/lib/api";
import { datumZeit } from "@/lib/format";
import { bloecke, stuecke } from "@/lib/protokoll";
import type { BesprechungVoll } from "@/lib/typen";
import { BesprechungZuordnen } from "@/components/besprechung-zuordnen";
import { Seitenkopf } from "@/components/seitenkopf";
import { Fehler, Laedt } from "@/components/zustaende";

function Text({ text }: { text: string }) {
  return (
    <>
      {stuecke(text).map((s, i) => (s.fett ? <strong key={i}>{s.text}</strong> : <span key={i}>{s.text}</span>))}
    </>
  );
}

/**
 * Eine Besprechung: links das Protokoll, rechts, wem sie gehört.
 *
 * Der Wortlaut steht nicht hier — Beacon bewahrt ihn bewusst nicht auf.
 * Wer den genauen Satz braucht, öffnet Insilo.
 */
export default function BesprechungSeite() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const client = useQueryClient();
  const [waehlt, setWaehlt] = useState(false);

  const abfrage = useQuery({
    queryKey: ["besprechung", id],
    queryFn: () => api.get<BesprechungVoll>(`/api/besprechungen/${id}`),
  });

  const nachHandlung = (b?: BesprechungVoll) => {
    if (b) client.setQueryData(["besprechung", id], b);
    client.invalidateQueries({ queryKey: ["besprechungen"] });
    client.invalidateQueries({ queryKey: ["briefing"] });
  };

  const uebernehmen = useMutation({
    mutationFn: (b: BesprechungVoll) =>
      api.post<BesprechungVoll>(`/api/besprechungen/${id}/zuordnen`, {
        company_id: b.vorschlag?.company?.id ?? null,
        contact_ids: (b.vorschlag?.kontakte ?? []).map((k) => k.id),
        deal_id: b.vorschlag?.deal?.id ?? null,
      }),
    onSuccess: nachHandlung,
  });
  const loesen = useMutation({
    mutationFn: () => api.post<BesprechungVoll>(`/api/besprechungen/${id}/loesen`),
    onSuccess: nachHandlung,
  });
  const neuVorschlagen = useMutation({
    mutationFn: () => api.post<BesprechungVoll>(`/api/besprechungen/${id}/vorschlagen`),
    onSuccess: nachHandlung,
  });
  const verwerfen = useMutation({
    mutationFn: () => api.post(`/api/besprechungen/${id}/verwerfen`),
    onSuccess: () => {
      nachHandlung();
      router.push("/besprechungen");
    },
  });

  if (abfrage.isPending) return <Laedt />;
  if (abfrage.isError) return <Fehler text={(abfrage.error as Error).message} />;
  const b = abfrage.data!;
  const v = b.vorschlag;
  const fehler = uebernehmen.error ?? loesen.error ?? neuVorschlagen.error ?? verwerfen.error;

  return (
    <>
      <Seitenkopf
        titel={b.titel || "Besprechung"}
        zahl={[datumZeit(b.recorded_at ?? b.created_at), b.vorlage].filter(Boolean).join(" · ")}
        pfad={{ text: "← Besprechungen", href: "/besprechungen" }}
      >
        {b.insilo_link && (
          <a className="btn btn-sekundaer" href={b.insilo_link} target="_blank" rel="noopener noreferrer">
            <ExternalLink size={15} aria-hidden="true" />
            In Insilo öffnen
          </a>
        )}
      </Seitenkopf>

      <div className="besprechung-seite">
        <article className="block protokoll">
          <div className="block-kopf">
            <h2>Protokoll</h2>
          </div>
          <div className="block-inhalt">
            {b.protokoll ? (
              bloecke(b.protokoll).map((block, i) => {
                if (block.art === "ueberschrift") {
                  // Die erste Überschrift ist der Titel — der steht schon oben.
                  if (block.stufe === 1) return null;
                  return block.stufe === 2 ? <h3 key={i}><Text text={block.text} /></h3> : <h4 key={i}><Text text={block.text} /></h4>;
                }
                if (block.art === "liste") {
                  return (
                    <ul key={i}>
                      {block.punkte.map((p, j) => (
                        <li key={j} data-erledigt={p.erledigt === null ? undefined : String(p.erledigt)}>
                          {p.erledigt !== null && <span className="protokoll-haken" aria-label={p.erledigt ? "erledigt" : "offen"}>{p.erledigt ? "☑" : "☐"}</span>}
                          <Text text={p.text} />
                        </li>
                      ))}
                    </ul>
                  );
                }
                return <p key={i}><Text text={block.text} /></p>;
              })
            ) : (
              <p className="erfassung-hinweis">Insilo hat zu dieser Besprechung kein Protokoll geschickt.</p>
            )}
            {b.insilo_link ? null : (
              <p className="protokoll-fuss">
                Der Wortlaut bleibt in Insilo. Mit der Adresse von Insilo unter Einstellungen › KI und Programme › Verbundene Programme
                steht hier ein Link dorthin.
              </p>
            )}
          </div>
        </article>

        <aside>
          <section className="block">
            <div className="block-kopf">
              <h2>Kunde</h2>
              <span className="stufe" data-art={b.status === "zugeordnet" ? "won" : undefined}>
                {b.status === "zugeordnet" ? "zugeordnet" : b.status === "verworfen" ? "verworfen" : "ohne Kunde"}
              </span>
            </div>
            <div className="block-inhalt">
              {b.status === "zugeordnet" ? (
                <dl className="besprechung-bezug">
                  {b.company && (
                    <div><dt>Firma</dt><dd><Link href={`/firmen/${b.company.id}`}>{b.company.name}</Link></dd></div>
                  )}
                  {b.kontakte.length > 0 && (
                    <div>
                      <dt>Beteiligte</dt>
                      <dd>
                        {b.kontakte.map((k, i) => (
                          <span key={k.id}>{i > 0 && ", "}<Link href={`/kontakte/${k.id}`}>{k.name}</Link></span>
                        ))}
                      </dd>
                    </div>
                  )}
                  {b.deal && (
                    <div><dt>Lead</dt><dd><Link href={`/deals/${b.deal.id}`}>{b.deal.name}</Link></dd></div>
                  )}
                </dl>
              ) : v?.company ? (
                <div className="besprechung-vorschlag">
                  <p className="kundenzelle-marke">{v.quelle === "modell" ? `Vorschlag des Modells${v.modell ? ` (${v.modell})` : ""}` : "Vorschlag"}</p>
                  <p className="haupt">{[v.company.name, ...v.kontakte.map((k) => k.name)].join(" · ")}</p>
                  {v.deal && <p className="kundenzelle-unter">Lead: {v.deal.name}</p>}
                  <p className="kundenzelle-unter">{v.grund}</p>
                </div>
              ) : (
                <p className="erfassung-hinweis" style={{ marginTop: 0 }}>{v?.grund || "Noch kein Vorschlag."}</p>
              )}

              {fehler && <Fehler text={(fehler as Error).message} />}

              <div className="btn-reihe" style={{ marginTop: "var(--am-raum-4)" }}>
                {b.status === "offen" && v?.company && (
                  <button type="button" className="btn btn-primaer btn-klein" onClick={() => uebernehmen.mutate(b)} disabled={uebernehmen.isPending}>
                    {uebernehmen.isPending ? "Ordnet zu …" : "Übernehmen"}
                  </button>
                )}
                {b.status !== "verworfen" && (
                  <button type="button" className="btn btn-sekundaer btn-klein" onClick={() => setWaehlt(true)}>
                    {b.status === "zugeordnet" ? "Umhängen …" : v?.company ? "Anders …" : "Zuordnen …"}
                  </button>
                )}
                {b.status === "zugeordnet" && (
                  <button type="button" className="btn btn-still btn-klein" onClick={() => loesen.mutate()} disabled={loesen.isPending}>
                    Zuordnung lösen
                  </button>
                )}
              </div>
              {b.status === "offen" && (
                <div className="btn-reihe" style={{ marginTop: "var(--am-raum-2)" }}>
                  <button type="button" className="btn btn-still btn-klein" onClick={() => neuVorschlagen.mutate()} disabled={neuVorschlagen.isPending}>
                    {neuVorschlagen.isPending ? "Sucht …" : "Neu vorschlagen"}
                  </button>
                  <button type="button" className="btn btn-still btn-klein" onClick={() => verwerfen.mutate()} disabled={verwerfen.isPending}>
                    Verwerfen
                  </button>
                </div>
              )}
            </div>
          </section>

          {(b.beteiligte.length > 0 || b.schlagworte.length > 0) && (
            <section className="block">
              <div className="block-kopf"><h2>Aus Insilo</h2></div>
              <div className="block-inhalt">
                <dl className="besprechung-bezug">
                  {b.beteiligte.length > 0 && <div><dt>Genannt</dt><dd>{b.beteiligte.join(", ")}</dd></div>}
                  {b.schlagworte.length > 0 && <div><dt>Schlagworte</dt><dd>{b.schlagworte.join(", ")}</dd></div>}
                </dl>
              </div>
            </section>
          )}
        </aside>
      </div>

      {waehlt && <BesprechungZuordnen besprechung={b} beiSchliessen={() => setWaehlt(false)} beiErfolg={(neu) => client.setQueryData(["besprechung", id], neu)} />}
    </>
  );
}
