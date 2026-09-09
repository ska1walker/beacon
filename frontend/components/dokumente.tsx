"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { FileText, FileImage, FileSpreadsheet, File as FileZeichen, Upload } from "lucide-react";
import { useRef, useState } from "react";
import { api, suchparameter } from "@/lib/api";
import { dateigroesse, datum } from "@/lib/format";
import type { Dokument } from "@/lib/typen";
import { Fehler } from "@/components/zustaende";

/** Woran ein Dokument hängt. Genau eines davon, wie im Backend. */
export type Dokumentbezug = {
  contact_id?: string;
  company_id?: string;
  deal_id?: string;
  ticket_id?: string;
};

/** Ein Zeichen, das die Art erkennen lässt, bevor man den Namen liest. */
function Zeichen({ typ }: { typ: string | null }) {
  const art = (typ ?? "").split(";")[0];
  const gemeinsam = { size: 16, "aria-hidden": true, style: { flexShrink: 0, color: "var(--am-text-gedaempft)" } };
  if (art.startsWith("image/")) return <FileImage {...gemeinsam} />;
  if (art === "application/pdf") return <FileText {...gemeinsam} />;
  if (art.includes("sheet") || art === "text/csv") return <FileSpreadsheet {...gemeinsam} />;
  return <FileZeichen {...gemeinsam} />;
}

/**
 * Die Ablage am Datensatz — Angebot, Vertrag, das Foto vom Zählerstand.
 *
 * Die Datei wird **nicht** über `fetch` geholt und in ein Objekt-URL
 * gepackt: Ein gewöhnlicher Link nimmt den Keks von selbst mit, kann
 * abbrechen und weiterladen, und der Browser muss die Datei nie ganz im
 * Speicher halten.
 */
export function Dokumente({ bezug }: { bezug: Dokumentbezug }) {
  const client = useQueryClient();
  const feld = useRef<HTMLInputElement>(null);
  const [ueber, setUeber] = useState(false);
  const schluessel = ["dokumente", bezug];
  const frage = suchparameter(bezug as Record<string, string | undefined>);

  const liste = useQuery({
    queryKey: schluessel,
    queryFn: () => api.get<Dokument[]>(`/api/dokumente${frage}`),
  });

  const hochladen = useMutation({
    mutationFn: async (dateien: File[]) => {
      // Nacheinander, nicht nebeneinander: Der Fortschritt bleibt so
      // verständlich, und eine große Datei drängt die anderen nicht weg.
      for (const datei of dateien) {
        const formular = new FormData();
        formular.append("datei", datei);
        for (const [schluessel, wert] of Object.entries(bezug)) {
          if (wert) formular.append(schluessel, wert);
        }
        await api.postForm<Dokument>("/api/dokumente", formular);
      }
    },
    onSuccess: () => client.invalidateQueries({ queryKey: schluessel }),
  });

  const loeschen = useMutation({
    mutationFn: (id: string) => api.del(`/api/dokumente/${id}`),
    onSuccess: () => client.invalidateQueries({ queryKey: schluessel }),
  });

  const waehlen = (dateien: FileList | null) => {
    const gewaehlt = Array.from(dateien ?? []);
    if (gewaehlt.length > 0) hochladen.mutate(gewaehlt);
  };

  const dokumente = liste.data ?? [];

  return (
    <section className="block">
      <div className="block-kopf">
        <h2>Dokumente</h2>
        {dokumente.length > 0 && <span className="stufe">{dokumente.length}</span>}
      </div>
      <div className="block-inhalt">
        {dokumente.length > 0 && (
          <ul style={{ listStyle: "none", padding: 0, margin: "0 0 var(--am-raum-3)", display: "grid", gap: "var(--am-raum-2)" }}>
            {dokumente.map((d) => (
              <li key={d.id}>
                {/* Der Name bekommt die volle Breite. Daneben stünde er in
                    einer 300-Pixel-Spalte in drei Zeilen. */}
                <div style={{ display: "flex", alignItems: "center", gap: "var(--am-raum-2)" }}>
                  <Zeichen typ={d.typ} />
                  <a
                    href={`/api/dokumente/${d.id}/datei`}
                    target={d.im_fenster ? "_blank" : undefined}
                    rel={d.im_fenster ? "noopener noreferrer" : undefined}
                    className="zellen-link"
                    style={{ minWidth: 0, overflowWrap: "anywhere" }}
                  >
                    {d.name}
                  </a>
                </div>
                <div style={{ display: "flex", alignItems: "center", gap: "var(--am-raum-2)", paddingLeft: "calc(16px + var(--am-raum-2))" }}>
                  <span style={{ flex: 1, fontSize: "0.75rem", color: "var(--am-text-gedaempft)" }}>
                    {dateigroesse(d.groesse)} · {datum(d.created_at)}
                    {d.hochgeladen_von_name ? ` · ${d.hochgeladen_von_name}` : ""}
                  </span>
                  <button
                    type="button"
                    className="btn btn-still btn-klein"
                    disabled={loeschen.isPending}
                    onClick={() => loeschen.mutate(d.id)}
                    aria-label={`${d.name} entfernen`}
                  >
                    Entfernen
                  </button>
                </div>
              </li>
            ))}
          </ul>
        )}

        {liste.data && dokumente.length === 0 && (
          <p style={{ fontSize: "0.8125rem", color: "var(--am-text-gedaempft)", marginBottom: "var(--am-raum-3)" }}>
            Noch nichts abgelegt.
          </p>
        )}

        <div
          onDragOver={(e) => { e.preventDefault(); setUeber(true); }}
          onDragLeave={() => setUeber(false)}
          onDrop={(e) => { e.preventDefault(); setUeber(false); waehlen(e.dataTransfer.files); }}
          style={{
            border: `1px dashed ${ueber ? "var(--am-handlung)" : "var(--am-rand)"}`,
            borderRadius: "var(--am-radius-2)",
            padding: "var(--am-raum-3)",
            textAlign: "center",
            background: ueber ? "var(--am-flaeche-2)" : "transparent",
          }}
        >
          <input
            ref={feld}
            type="file"
            multiple
            hidden
            onChange={(e) => { waehlen(e.target.files); e.target.value = ""; }}
          />
          <button
            type="button"
            className="btn btn-sekundaer btn-klein"
            disabled={hochladen.isPending}
            onClick={() => feld.current?.click()}
          >
            <Upload size={14} aria-hidden />
            {hochladen.isPending ? "Wird abgelegt …" : "Datei ablegen"}
          </button>
          <p style={{ fontSize: "0.75rem", color: "var(--am-text-gedaempft)", margin: "var(--am-raum-2) 0 0" }}>
            oder hierher ziehen · bis 25 MB
          </p>
        </div>

        {(hochladen.isError || loeschen.isError) && (
          <Fehler text={((hochladen.error ?? loeschen.error) as Error).message} />
        )}
      </div>
    </section>
  );
}
