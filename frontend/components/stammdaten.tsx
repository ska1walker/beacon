"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Pencil, Trash2 } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { api } from "@/lib/api";
import { Fehler } from "@/components/zustaende";

export interface Stammfeld {
  key: string;
  text: string;
  art?: "text" | "number" | "date" | "select" | "email" | "textarea";
  optionen?: { wert: string; text: string }[];
  /** Für die Anzeige, wenn nicht bearbeitet wird. */
  zeige?: (wert: unknown) => React.ReactNode;
  /** Gespeichert wird wert × skala — Cent in der API, Euro im Feld. */
  skala?: number;
}

/**
 * Die festen Felder eines Datensatzes — ansehen, bearbeiten, löschen.
 *
 * Ein Schalter, dann werden alle Felder zu Eingaben; gespeichert wird,
 * was sich geändert hat. Kein Feld-für-Feld-Klicken wie bei HubSpot:
 * Das ist auf dem Papier eleganter und in der Praxis fünf Speicherungen
 * für eine Adresse.
 */
export function Stammdaten({
  titel,
  pfad,
  felder,
  werte,
  abfrageSchluessel,
  zurueckNach,
  loeschtext,
  kopfrechts,
}: {
  titel: string;
  pfad: string;
  felder: Stammfeld[];
  werte: Record<string, unknown>;
  abfrageSchluessel: unknown[];
  zurueckNach: string;
  loeschtext: string;
  kopfrechts?: React.ReactNode;
}) {
  const client = useQueryClient();
  const router = useRouter();
  const [bearbeiten, setBearbeiten] = useState(false);
  const [entwurf, setEntwurf] = useState<Record<string, string>>({});
  const [loeschen, setLoeschen] = useState(false);

  const speichern = useMutation({
    mutationFn: () => {
      const patch: Record<string, unknown> = {};
      for (const [k, v] of Object.entries(entwurf)) {
        const f = felder.find((x) => x.key === k);
        if (v === "") patch[k] = null;
        else if (f?.art === "number") patch[k] = Math.round(Number(v) * (f.skala ?? 1));
        else patch[k] = v;
      }
      return api.patch(pfad, patch);
    },
    onSuccess: () => {
      setBearbeiten(false);
      setEntwurf({});
      client.invalidateQueries({ queryKey: abfrageSchluessel });
      client.invalidateQueries();
    },
  });

  const entfernen = useMutation({
    mutationFn: () => api.del(pfad),
    onSuccess: () => {
      client.invalidateQueries();
      router.push(zurueckNach);
    },
  });

  function wert(key: string): string {
    if (key in entwurf) return entwurf[key];
    const v = werte[key];
    const f = felder.find((x) => x.key === key);
    if (v === null || v === undefined) return "";
    return f?.skala && typeof v === "number" ? String(v / f.skala) : String(v);
  }

  return (
    <section className="block">
      <div className="block-kopf">
        <h2>{titel}</h2>
        <span style={{ display: "inline-flex", gap: "var(--am-raum-1)", alignItems: "center" }}>
          {kopfrechts}
          {!bearbeiten && (
            <button type="button" className="btn btn-still btn-klein" onClick={() => setBearbeiten(true)} aria-label="Bearbeiten">
              <Pencil size={14} aria-hidden="true" />
            </button>
          )}
        </span>
      </div>
      <div className="block-inhalt">
        {bearbeiten ? (
          <form onSubmit={(e) => { e.preventDefault(); speichern.mutate(); }}>
            {felder.map((f) => (
              <div className="feld" key={f.key}>
                <label htmlFor={`sd-${f.key}`}>{f.text}</label>
                {f.art === "select" ? (
                  <select id={`sd-${f.key}`} value={wert(f.key)} onChange={(e) => setEntwurf((a) => ({ ...a, [f.key]: e.target.value }))}>
                    <option value="">—</option>
                    {f.optionen?.map((o) => <option key={o.wert} value={o.wert}>{o.text}</option>)}
                  </select>
                ) : f.art === "textarea" ? (
                  <textarea id={`sd-${f.key}`} rows={3} value={wert(f.key)} onChange={(e) => setEntwurf((a) => ({ ...a, [f.key]: e.target.value }))} />
                ) : (
                  <input id={`sd-${f.key}`} type={f.art ?? "text"} value={wert(f.key)} onChange={(e) => setEntwurf((a) => ({ ...a, [f.key]: e.target.value }))} />
                )}
              </div>
            ))}
            {speichern.isError && <Fehler text={(speichern.error as Error).message} />}
            <div className="btn-reihe">
              <button type="submit" className="btn btn-primaer btn-klein" disabled={speichern.isPending || Object.keys(entwurf).length === 0}>
                {speichern.isPending ? "Speichert …" : "Speichern"}
              </button>
              <button type="button" className="btn btn-still btn-klein" onClick={() => { setBearbeiten(false); setEntwurf({}); }}>Abbrechen</button>
              <button type="button" className="btn btn-still btn-klein" style={{ marginLeft: "auto", color: "var(--am-fehler)" }} onClick={() => setLoeschen(true)}>
                <Trash2 size={14} aria-hidden="true" /> Löschen
              </button>
            </div>
          </form>
        ) : (
          <dl>
            {felder.map((f) => {
              const v = werte[f.key];
              const leer = v === null || v === undefined || v === "";
              return (
                <div className="eigenschaft" key={f.key}>
                  <dt>{f.text}</dt>
                  <dd>{leer ? "—" : f.zeige ? f.zeige(v) : f.art === "select" ? (f.optionen?.find((o) => o.wert === v)?.text ?? String(v)) : String(v)}</dd>
                </div>
              );
            })}
          </dl>
        )}

        {loeschen && (
          <div className="dialog-schicht" role="dialog" aria-modal="true" aria-label="Löschen bestätigen">
            <div className="karte" style={{ maxWidth: "420px", width: "100%" }}>
              <h2 style={{ fontSize: "1.125rem", marginBottom: "var(--am-raum-3)" }}>Wirklich löschen?</h2>
              <p style={{ fontSize: "0.875rem", color: "var(--am-text-sekundaer)", marginBottom: "var(--am-raum-4)" }}>{loeschtext}</p>
              {entfernen.isError && <Fehler text={(entfernen.error as Error).message} />}
              <div className="btn-reihe">
                <button type="button" className="btn btn-primaer" onClick={() => entfernen.mutate()} disabled={entfernen.isPending}>Löschen</button>
                <button type="button" className="btn btn-still" onClick={() => setLoeschen(false)}>Abbrechen</button>
              </div>
            </div>
          </div>
        )}
      </div>
    </section>
  );
}
