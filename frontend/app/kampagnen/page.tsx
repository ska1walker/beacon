"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";
import { api } from "@/lib/api";
import { datum, KAMPAGNE_STATUS_ART, KAMPAGNE_STATUS_TEXT } from "@/lib/format";
import type { Kampagne, Liste } from "@/lib/typen";
import { Seitenkopf } from "@/components/seitenkopf";
import { Fehler, Laedt, Leer } from "@/components/zustaende";

function KampagneAnlegen({ vorgewaehlt, beiSchliessen, beiErfolg }: { vorgewaehlt: string | null; beiSchliessen: () => void; beiErfolg: (id: string) => void }) {
  const [name, setName] = useState("");
  const [listeId, setListeId] = useState(vorgewaehlt ?? "");
  const listen = useQuery({ queryKey: ["listen"], queryFn: () => api.get<Liste[]>("/api/listen") });
  const anlegen = useMutation({
    mutationFn: () => api.post<Kampagne>("/api/kampagnen", { name, liste_id: listeId || null }),
    onSuccess: (k) => beiErfolg(k.id),
  });
  return (
    <div className="dialog-schicht" role="dialog" aria-modal="true" aria-label="Kampagne anlegen">
      <div className="karte dialog-karte" style={{ maxWidth: "480px", width: "100%" }}>
        <h2 style={{ marginBottom: "var(--am-raum-4)", fontSize: "1.125rem" }}>Kampagne anlegen</h2>
        <form onSubmit={(e) => { e.preventDefault(); anlegen.mutate(); }}>
          <div className="feld">
            <label htmlFor="ka-name">Name</label>
            <input id="ka-name" value={name} onChange={(e) => setName(e.target.value)} required placeholder="Herbst-Neuigkeiten" />
            <p className="feld-hinweis">Nur für Sie — die Empfänger sehen den Betreff.</p>
          </div>
          <div className="feld">
            <label htmlFor="ka-liste">An wen</label>
            <select id="ka-liste" value={listeId} onChange={(e) => setListeId(e.target.value)}>
              <option value="">— Liste später wählen —</option>
              {listen.data?.map((l) => <option key={l.id} value={l.id}>{l.name} ({l.berechtigt} dürfen Post)</option>)}
            </select>
          </div>
          {anlegen.isError && <Fehler text={(anlegen.error as Error).message} />}
          <div className="btn-reihe" style={{ marginTop: "var(--am-raum-6)" }}>
            <button type="submit" className="btn btn-primaer" disabled={anlegen.isPending || !name.trim()}>
              {anlegen.isPending ? "Wird angelegt …" : "Anlegen"}
            </button>
            <button type="button" className="btn btn-still" onClick={beiSchliessen}>Abbrechen</button>
          </div>
        </form>
      </div>
    </div>
  );
}

function Inhalt() {
  const router = useRouter();
  const client = useQueryClient();
  const suche = useSearchParams();
  const [offen, setOffen] = useState(!!suche.get("liste"));
  const kampagnen = useQuery({ queryKey: ["kampagnen"], queryFn: () => api.get<Kampagne[]>("/api/kampagnen") });

  return (
    <>
      <Seitenkopf titel="Kampagnen" zahl={kampagnen.data ? `${kampagnen.data.length}` : undefined}>
        <button type="button" className="btn btn-primaer" onClick={() => setOffen(true)}>Kampagne anlegen</button>
      </Seitenkopf>

      {offen && (
        <KampagneAnlegen
          vorgewaehlt={suche.get("liste")}
          beiSchliessen={() => setOffen(false)}
          beiErfolg={(id) => { setOffen(false); client.invalidateQueries({ queryKey: ["kampagnen"] }); router.push(`/kampagnen/${id}`); }}
        />
      )}

      <div className="liste">
        {kampagnen.isPending && <Laedt />}
        {kampagnen.isError && <Fehler text={(kampagnen.error as Error).message} />}
        {kampagnen.data && kampagnen.data.length === 0 && (
          <Leer titel="Noch keine Kampagne" text="Eine Kampagne ist Betreff, Text und eine Liste. Geschrieben wird nur, wer eingewilligt hat." />
        )}
        {kampagnen.data && kampagnen.data.length > 0 && (
          <div className="rollbar">
            <table className="tabelle" style={{ minInlineSize: "48rem" }}>
              <thead>
                <tr>
                  <th>Kampagne</th>
                  <th>Liste</th>
                  <th>Status</th>
                  <th style={{ textAlign: "right" }}>Gesendet</th>
                  <th style={{ textAlign: "right" }}>Klicks</th>
                  <th style={{ textAlign: "right" }}>Abgemeldet</th>
                  <th>Gestartet</th>
                </tr>
              </thead>
              <tbody>
                {kampagnen.data.map((k) => (
                  <tr key={k.id} onClick={() => router.push(`/kampagnen/${k.id}`)}>
                    <td className="haupt">{k.name}<div style={{ fontSize: "0.8125rem", color: "var(--am-text-gedaempft)" }}>{k.betreff || "ohne Betreff"}</div></td>
                    <td>{k.liste_name ?? "—"}</td>
                    <td><span className="stufe" data-art={KAMPAGNE_STATUS_ART[k.status]}>{KAMPAGNE_STATUS_TEXT[k.status]}</span></td>
                    <td className="zahl">{k.gesendet}{k.wartend > 0 && <span style={{ color: "var(--am-text-gedaempft)" }}> +{k.wartend}</span>}</td>
                    <td className="zahl">{k.klicks}</td>
                    <td className="zahl">{k.abgemeldet}</td>
                    <td>{k.gestartet_am ? datum(k.gestartet_am) : "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </>
  );
}

export default function KampagnenSeite() {
  return (
    <Suspense fallback={<Laedt />}>
      <Inhalt />
    </Suspense>
  );
}
