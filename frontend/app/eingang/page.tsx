"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "@/lib/api";
import { datumZeit } from "@/lib/format";
import type { Company, Deal, Eingangsposten } from "@/lib/typen";
import { Seitenkopf } from "@/components/seitenkopf";
import { Fehler, Laedt, Leer } from "@/components/zustaende";

/**
 * Länge des Protokolls. Auf Tausender zu runden machte aus einem kurzen
 * Protokoll „0 kZeichen" — eine Zahl, die behauptet, es gäbe nichts.
 */
function laenge(zeichen: number): string {
  if (zeichen >= 1000) return `${Math.round(zeichen / 1000)}.000 Zeichen`;
  return `${zeichen} Zeichen`;
}

/**
 * Was aus Insilo hereinkam und sich nicht von allein zuordnen ließ.
 *
 * Eindeutiges landet direkt am Geschäft — hier steht nur, was
 * mehrdeutig war. Ein Protokoll am falschen Kunden ist schlimmer als
 * eines, das eine Minute wartet.
 */
export default function EingangSeite() {
  const client = useQueryClient();
  const [offenerPosten, setOffenerPosten] = useState<string | null>(null);
  const [ziel, setZiel] = useState("");
  const [ansicht, setAnsicht] = useState<{ titel: string | null; markdown: string } | null>(null);

  const posten = useQuery({
    queryKey: ["eingang"],
    queryFn: () => api.get<Eingangsposten[]>("/api/eingang"),
    // Ereignisse kommen von außen, ohne dass die Oberfläche es merkt.
    refetchInterval: 60_000,
  });

  const deals = useQuery({
    queryKey: ["deals-auswahl"],
    queryFn: () => api.get<Deal[]>("/api/deals?limit=200"),
  });

  const firmen = useQuery({
    queryKey: ["firmen-auswahl"],
    queryFn: () => api.get<Company[]>("/api/companies?limit=200"),
  });

  const zuordnen = useMutation({
    mutationFn: ({ id, wert }: { id: string; wert: string }) => {
      const [art, kennung] = wert.split(":");
      return api.post(`/api/eingang/${id}/zuordnen`, {
        [art === "deal" ? "deal_id" : "company_id"]: kennung,
      });
    },
    onSuccess: () => {
      setOffenerPosten(null);
      setZiel("");
      client.invalidateQueries();
    },
  });

  const verwerfen = useMutation({
    mutationFn: (id: string) => api.post(`/api/eingang/${id}/verwerfen`),
    onSuccess: () => client.invalidateQueries({ queryKey: ["eingang"] }),
  });

  if (posten.isPending) return <Laedt />;
  if (posten.isError) return <Fehler text={(posten.error as Error).message} />;

  return (
    <>
      <Seitenkopf
        titel="Eingang"
        zahl={
          posten.data!.length === 0
            ? "nichts offen"
            : `${posten.data!.length} ohne eindeutige Zuordnung`
        }
      />

      {ansicht && (
        <div className="dialog-schicht" role="dialog" aria-modal="true" aria-label="Inhalt">
          <div className="karte" style={{ maxWidth: "720px", width: "100%", maxHeight: "85vh", overflow: "auto" }}>
            <h2 style={{ fontSize: "1.125rem", marginBottom: "var(--am-raum-4)" }}>{ansicht.titel ?? "Inhalt"}</h2>
            <pre style={{ whiteSpace: "pre-wrap", fontFamily: "var(--am-schrift-sans)", fontSize: "0.875rem", lineHeight: 1.6 }}>{ansicht.markdown}</pre>
            <div className="btn-reihe" style={{ marginTop: "var(--am-raum-4)" }}>
              <button type="button" className="btn btn-still" onClick={() => setAnsicht(null)}>Schließen</button>
            </div>
          </div>
        </div>
      )}

      <div className="liste">
        {posten.data!.length === 0 && (
          <Leer
            titel="Nichts offen"
            text="Besprechungen aus Insilo, die sich eindeutig zuordnen ließen, stehen direkt am Geschäft."
          />
        )}

        {posten.data!.map((p) => (
          <section className="block" key={p.id} style={{ marginBottom: "var(--am-raum-4)" }}>
            <div className="block-kopf">
              <h2>{p.titel ?? "Ohne Titel"}</h2>
              <span style={{ fontSize: "0.75rem", color: "var(--am-text-gedaempft)" }}>
                {datumZeit(p.occurred_at ?? p.created_at)}
              </span>
            </div>
            <div className="block-inhalt">
              <dl>
                <div className="eigenschaft">
                  <dt>Ereignis</dt>
                  <dd className="mono">{p.event}</dd>
                </div>
                <div className="eigenschaft">
                  <dt>Warum es hier liegt</dt>
                  <dd>{p.zuordnung_grund ?? "—"}</dd>
                </div>
                {p.markdown_laenge > 0 && (
                  <div className="eigenschaft">
                    <dt>Protokoll</dt>
                    <dd>{laenge(p.markdown_laenge)}</dd>
                  </div>
                )}
              </dl>

              {offenerPosten === p.id ? (
                <div style={{ marginTop: "var(--am-raum-4)" }}>
                  <div className="feld">
                    <label htmlFor={`ziel-${p.id}`}>Wohin gehört es?</label>
                    <select
                      id={`ziel-${p.id}`}
                      value={ziel}
                      onChange={(e) => setZiel(e.target.value)}
                    >
                      <option value="">— wählen —</option>
                      <optgroup label="Geschäfte">
                        {deals.data?.map((d) => (
                          <option key={d.id} value={`deal:${d.id}`}>
                            {d.name} · {d.company_name ?? "ohne Firma"}
                          </option>
                        ))}
                      </optgroup>
                      <optgroup label="Firmen">
                        {firmen.data?.map((f) => (
                          <option key={f.id} value={`company:${f.id}`}>
                            {f.name}
                          </option>
                        ))}
                      </optgroup>
                    </select>
                  </div>
                  {zuordnen.isError && <Fehler text={(zuordnen.error as Error).message} />}
                  <div className="btn-reihe">
                    <button
                      type="button"
                      className="btn btn-primaer btn-klein"
                      disabled={!ziel || zuordnen.isPending}
                      onClick={() => zuordnen.mutate({ id: p.id, wert: ziel })}
                    >
                      {zuordnen.isPending ? "Ordnet zu …" : "Zuordnen"}
                    </button>
                    <button
                      type="button"
                      className="btn btn-still btn-klein"
                      onClick={() => setOffenerPosten(null)}
                    >
                      Abbrechen
                    </button>
                  </div>
                </div>
              ) : (
                <div className="btn-reihe" style={{ marginTop: "var(--am-raum-4)" }}>
                  <button
                    type="button"
                    className="btn btn-primaer btn-klein"
                    onClick={() => {
                      setOffenerPosten(p.id);
                      setZiel("");
                    }}
                  >
                    Zuordnen
                  </button>
                  {p.markdown_laenge > 0 && (
                    <button type="button" className="btn btn-sekundaer btn-klein" onClick={async () => setAnsicht(await api.get(`/api/eingang/${p.id}/markdown`))}>
                      Ansehen
                    </button>
                  )}
                  <button
                    type="button"
                    className="btn btn-still btn-klein"
                    onClick={() => verwerfen.mutate(p.id)}
                  >
                    Verwerfen
                  </button>
                </div>
              )}
            </div>
          </section>
        ))}
      </div>
    </>
  );
}
