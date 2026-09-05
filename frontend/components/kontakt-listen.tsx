"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useState } from "react";
import { api } from "@/lib/api";
import type { Liste } from "@/lib/typen";
import { Fehler } from "@/components/zustaende";

/** In welchen Listen dieser Kontakt steht — und in welche er noch soll. */
export function KontaktListen({ kontaktId }: { kontaktId: string }) {
  const client = useQueryClient();
  const drin = useQuery({ queryKey: ["listen", "von", kontaktId], queryFn: () => api.get<Liste[]>(`/api/listen/von/${kontaktId}`) });
  const alle = useQuery({ queryKey: ["listen"], queryFn: () => api.get<Liste[]>("/api/listen") });
  const [wahl, setWahl] = useState("");
  const frisch = () => {
    client.invalidateQueries({ queryKey: ["listen"] });
    client.invalidateQueries({ queryKey: ["listen", "von", kontaktId] });
  };
  const hinzu = useMutation({
    mutationFn: (liste_id: string) => api.post(`/api/listen/${liste_id}/mitglieder`, { contact_ids: [kontaktId] }),
    onSuccess: () => { setWahl(""); frisch(); },
  });
  const raus = useMutation({
    mutationFn: (liste_id: string) => api.del(`/api/listen/${liste_id}/mitglieder/${kontaktId}`),
    onSuccess: frisch,
  });
  const drinIds = new Set((drin.data ?? []).map((l) => l.id));
  const offen = (alle.data ?? []).filter((l) => l.art === "statisch" && !drinIds.has(l.id));

  return (
    <section className="block">
      <div className="block-kopf">
        <h2>Listen</h2>
        {drin.data && <span className="stufe">{drin.data.length}</span>}
      </div>
      <div className="block-inhalt">
        {drin.data && drin.data.length === 0 && (
          <p style={{ fontSize: "0.8125rem", color: "var(--am-text-gedaempft)", marginBottom: "var(--am-raum-3)" }}>In keiner Liste.</p>
        )}
        {drin.data && drin.data.length > 0 && (
          <ul style={{ listStyle: "none", padding: 0, margin: "0 0 var(--am-raum-3)", display: "grid", gap: "var(--am-raum-1)" }}>
            {drin.data.map((l) => (
              <li key={l.id} style={{ display: "flex", alignItems: "center", gap: "var(--am-raum-2)" }}>
                <Link href={`/listen/${l.id}`} className="zellen-link" style={{ flex: 1 }}>{l.name}</Link>
                <button type="button" className="btn btn-still btn-klein" disabled={raus.isPending} onClick={() => raus.mutate(l.id)}>Entfernen</button>
              </li>
            ))}
          </ul>
        )}
        {offen.length > 0 && (
          <div style={{ display: "flex", gap: "var(--am-raum-2)" }}>
            <select value={wahl} onChange={(e) => setWahl(e.target.value)} aria-label="Liste wählen" style={{ flex: 1 }}>
              <option value="">— In eine Liste —</option>
              {offen.map((l) => <option key={l.id} value={l.id}>{l.name}</option>)}
            </select>
            <button type="button" className="btn btn-sekundaer btn-klein" disabled={!wahl || hinzu.isPending} onClick={() => hinzu.mutate(wahl)}>Hinzufügen</button>
          </div>
        )}
        {(hinzu.isError || raus.isError) && <Fehler text={((hinzu.error ?? raus.error) as Error).message} />}
      </div>
    </section>
  );
}
