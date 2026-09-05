"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowDown, ArrowUp, Star } from "lucide-react";
import { useState } from "react";
import { api } from "@/lib/api";
import type { Pipeline, Stage, StageKind } from "@/lib/typen";
import { Fehler, Laedt } from "@/components/zustaende";
import { Erklaerung } from "@/components/erklaerung";

const ART_TEXT: Record<StageKind, string> = { open: "offen", won: "gewonnen", lost: "verloren" };

/**
 * Pipelines und Stufen pflegen.
 *
 * Löschen ist hart gemacht: Eine Stufe mit Geschäften geht nur mit
 * Zielangabe, eine Pipeline nur ohne Geschäfte, die letzte gar nicht.
 * Die Art einer Stufe ist fest, sobald etwas darauf liegt.
 */
export function Pipelinesblock() {
  const client = useQueryClient();
  const [neuerName, setNeuerName] = useState("");
  const [neueStufe, setNeueStufe] = useState<Record<string, string>>({});
  const [loeschZiel, setLoeschZiel] = useState<{ stage: Stage; pipeline: Pipeline } | null>(null);
  const [ziel, setZiel] = useState("");

  const pipelines = useQuery({
    queryKey: ["pipelines"],
    queryFn: () => api.get<Pipeline[]>("/api/pipelines"),
  });

  const neu = () => client.invalidateQueries({ queryKey: ["pipelines"] }).then(() => client.invalidateQueries({ queryKey: ["board"] }));

  const anlegen = useMutation({
    mutationFn: () => api.post("/api/pipelines", { name: neuerName }),
    onSuccess: () => { setNeuerName(""); neu(); },
  });
  const pipelineAendern = useMutation({
    mutationFn: ({ id, ...rest }: { id: string; name?: string; is_default?: boolean }) => api.patch(`/api/pipelines/${id}`, rest),
    onSuccess: neu,
  });
  const pipelineLoeschen = useMutation({
    mutationFn: (id: string) => api.del(`/api/pipelines/${id}`),
    onSuccess: neu,
  });
  const stufeAnlegen = useMutation({
    mutationFn: ({ pipelineId, name }: { pipelineId: string; name: string }) =>
      api.post(`/api/pipelines/${pipelineId}/stages`, { name, probability: 0.3 }),
    onSuccess: (_d, v) => { setNeueStufe((a) => ({ ...a, [v.pipelineId]: "" })); neu(); },
  });
  const stufeAendern = useMutation({
    mutationFn: ({ id, ...rest }: { id: string; name?: string; probability?: number }) => api.patch(`/api/pipelines/stages/${id}`, rest),
    onSuccess: neu,
  });
  const reihenfolge = useMutation({
    mutationFn: ({ pipelineId, ids }: { pipelineId: string; ids: string[] }) =>
      api.put(`/api/pipelines/${pipelineId}/stages/reihenfolge`, { stage_ids: ids }),
    onSuccess: neu,
  });
  const stufeLoeschen = useMutation({
    mutationFn: ({ id, zielId }: { id: string; zielId: string | null }) =>
      api.post(`/api/pipelines/stages/${id}/loeschen`, { ziel_stage_id: zielId }),
    onSuccess: () => { setLoeschZiel(null); setZiel(""); neu(); },
  });

  if (pipelines.isPending) return <Laedt />;
  const fehler = [anlegen, pipelineAendern, pipelineLoeschen, stufeAnlegen, stufeAendern, reihenfolge, stufeLoeschen].find((m) => m.isError);

  function verschiebe(pl: Pipeline, index: number, richtung: -1 | 1) {
    const ids = pl.stages.map((s) => s.id);
    const j = index + richtung;
    if (j < 0 || j >= ids.length) return;
    [ids[index], ids[j]] = [ids[j], ids[index]];
    reihenfolge.mutate({ pipelineId: pl.id, ids });
  }

  return (
    <section className="block">
      <div className="block-kopf"><h2>Pipelines und Stufen</h2></div>
      <div className="block-inhalt">
        <Erklaerung kurz="Die Stufen, die ein Geschäft durchläuft — bei Bedarf mehrere Pipelines." lang={<>Neugeschäft und Bestandskunden laufen anders — dafür gibt es mehrere Pipelines. Neue
          Geschäfte landen ohne Angabe in der Standard-Pipeline. Die Wahrscheinlichkeit einer
          Stufe geht in die gewichtete Prognose ein.</>} />
        {fehler && <Fehler text={(fehler.error as Error).message} />}

        {pipelines.data!.map((pl) => (
          <div key={pl.id} className="karte" style={{ marginBottom: "var(--am-raum-4)", padding: "var(--am-raum-4)" }}>
            <div style={{ display: "flex", gap: "var(--am-raum-2)", alignItems: "center", marginBottom: "var(--am-raum-3)" }}>
              <input
                className="input"
                aria-label="Name der Pipeline"
                defaultValue={pl.name}
                onBlur={(e) => e.target.value.trim() && e.target.value !== pl.name && pipelineAendern.mutate({ id: pl.id, name: e.target.value.trim() })}
                style={{ flex: 1, fontWeight: 600 }}
              />
              <button
                type="button"
                className={`btn btn-klein ${pl.is_default ? "btn-primaer" : "btn-still"}`}
                title={pl.is_default ? "Standard-Pipeline" : "Als Standard setzen"}
                disabled={pl.is_default}
                onClick={() => pipelineAendern.mutate({ id: pl.id, is_default: true })}
              >
                <Star size={14} aria-hidden="true" />{pl.is_default ? "Standard" : "Standard setzen"}
              </button>
              <button type="button" className="btn btn-still btn-klein" onClick={() => pipelineLoeschen.mutate(pl.id)}>Löschen</button>
            </div>

            <table className="tabelle">
              <thead><tr><th>Stufe</th><th>Art</th><th style={{ textAlign: "right", width: "9rem" }}>Wahrscheinlichkeit %</th><th style={{ width: "10rem" }} /></tr></thead>
              <tbody>
                {pl.stages.map((s, i) => (
                  <tr key={s.id} style={{ cursor: "default" }}>
                    <td>
                      <input className="input" aria-label="Name der Stufe" defaultValue={s.name}
                        onBlur={(e) => e.target.value.trim() && e.target.value !== s.name && stufeAendern.mutate({ id: s.id, name: e.target.value.trim() })} />
                    </td>
                    <td><span className="stufe" data-art={s.kind}>{ART_TEXT[s.kind]}</span></td>
                    <td className="zahl">
                      <input className="input" type="number" min="0" max="100" step="5" aria-label="Wahrscheinlichkeit"
                        defaultValue={Math.round(s.probability * 100)}
                        onBlur={(e) => { const p = Number(e.target.value) / 100; if (p !== s.probability) stufeAendern.mutate({ id: s.id, probability: p }); }} />
                    </td>
                    <td style={{ textAlign: "right", whiteSpace: "nowrap" }}>
                      <button type="button" className="btn btn-still btn-klein" aria-label="nach oben" disabled={i === 0} onClick={() => verschiebe(pl, i, -1)}><ArrowUp size={14} /></button>
                      <button type="button" className="btn btn-still btn-klein" aria-label="nach unten" disabled={i === pl.stages.length - 1} onClick={() => verschiebe(pl, i, 1)}><ArrowDown size={14} /></button>
                      <button type="button" className="btn btn-still btn-klein" onClick={() => { setLoeschZiel({ stage: s, pipeline: pl }); setZiel(""); }}>Löschen</button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>

            <form style={{ display: "flex", gap: "var(--am-raum-2)", marginTop: "var(--am-raum-3)" }}
              onSubmit={(e) => { e.preventDefault(); const n = (neueStufe[pl.id] ?? "").trim(); if (n) stufeAnlegen.mutate({ pipelineId: pl.id, name: n }); }}>
              <input className="input" placeholder="Neue Stufe — landet vor dem Abschluss" aria-label="Neue Stufe"
                value={neueStufe[pl.id] ?? ""} onChange={(e) => setNeueStufe((a) => ({ ...a, [pl.id]: e.target.value }))} />
              <button type="submit" className="btn btn-sekundaer btn-klein" disabled={!(neueStufe[pl.id] ?? "").trim()}>Stufe anlegen</button>
            </form>
          </div>
        ))}

        <form style={{ display: "flex", gap: "var(--am-raum-2)" }} onSubmit={(e) => { e.preventDefault(); if (neuerName.trim()) anlegen.mutate(); }}>
          <input className="input" placeholder="Neue Pipeline, z. B. Bestandskunden" aria-label="Neue Pipeline" value={neuerName} onChange={(e) => setNeuerName(e.target.value)} />
          <button type="submit" className="btn btn-primaer btn-klein" disabled={!neuerName.trim() || anlegen.isPending}>Pipeline anlegen</button>
        </form>

        {loeschZiel && (
          <div className="dialog-schicht" role="dialog" aria-modal="true" aria-label="Stufe löschen">
            <div className="karte" style={{ maxWidth: "440px", width: "100%" }}>
              <h2 style={{ fontSize: "1.125rem", marginBottom: "var(--am-raum-4)" }}>„{loeschZiel.stage.name}“ löschen</h2>
              <p style={{ fontSize: "0.875rem", color: "var(--am-text-sekundaer)", marginBottom: "var(--am-raum-4)" }}>
                Liegen Geschäfte auf dieser Stufe, wandern sie auf die gewählte — mit Eintrag im Verlauf.
              </p>
              <div className="feld">
                <label htmlFor="loeschziel">Leads verschieben nach</label>
                <select id="loeschziel" value={ziel} onChange={(e) => setZiel(e.target.value)}>
                  <option value="">— keine liegen dort —</option>
                  {loeschZiel.pipeline.stages.filter((s) => s.id !== loeschZiel.stage.id).map((s) => (
                    <option key={s.id} value={s.id}>{s.name}</option>
                  ))}
                </select>
              </div>
              <div className="btn-reihe">
                <button type="button" className="btn btn-primaer" onClick={() => stufeLoeschen.mutate({ id: loeschZiel.stage.id, zielId: ziel || null })} disabled={stufeLoeschen.isPending}>Löschen</button>
                <button type="button" className="btn btn-still" onClick={() => setLoeschZiel(null)}>Abbrechen</button>
              </div>
            </div>
          </div>
        )}
      </div>
    </section>
  );
}
