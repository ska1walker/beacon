"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useState } from "react";
import { api } from "@/lib/api";
import { datumZeit } from "@/lib/format";
import type { Deal, Task } from "@/lib/typen";
import { Seitenkopf } from "@/components/seitenkopf";
import { Fehler, Laedt, Leer } from "@/components/zustaende";

export default function AufgabenSeite() {
  const client = useQueryClient();
  const [titel, setTitel] = useState("");
  const [faellig, setFaellig] = useState("");
  const [dealId, setDealId] = useState("");
  const [status, setStatus] = useState<"open" | "done">("open");
  const [bearbeite, setBearbeite] = useState<{ id: string; title: string; due: string } | null>(null);

  const abfrage = useQuery({ queryKey: ["aufgaben", status], queryFn: () => api.get<Task[]>(`/api/tasks?status=${status}`) });
  const deals = useQuery({ queryKey: ["deals-auswahl"], queryFn: () => api.get<Deal[]>("/api/deals?status=open&limit=200") });
  const frisch = () => client.invalidateQueries({ queryKey: ["aufgaben"] });

  const anlegen = useMutation({
    mutationFn: () => api.post<Task>("/api/tasks", { title: titel, due_at: faellig ? `${faellig}T09:00:00` : null, deal_id: dealId || null,
      company_id: deals.data?.find((d) => d.id === dealId)?.company_id ?? null }),
    onSuccess: () => { setTitel(""); setFaellig(""); setDealId(""); frisch(); },
  });
  const setzeStatus = useMutation({ mutationFn: ({ id, s }: { id: string; s: "open" | "done" | "cancelled" }) => api.patch<Task>(`/api/tasks/${id}`, { status: s }), onSuccess: frisch });
  const aendern = useMutation({
    mutationFn: () => api.patch<Task>(`/api/tasks/${bearbeite!.id}`, { title: bearbeite!.title, due_at: bearbeite!.due ? `${bearbeite!.due}T09:00:00` : null }),
    onSuccess: () => { setBearbeite(null); frisch(); },
  });

  return (
    <>
      <Seitenkopf titel="Aufgaben" zahl={abfrage.data ? `${abfrage.data.length} ${status === "open" ? "offen" : "erledigt"}` : undefined}>
        <button type="button" className={`btn btn-klein ${status === "open" ? "btn-primaer" : "btn-sekundaer"}`} onClick={() => setStatus("open")}>Offen</button>
        <button type="button" className={`btn btn-klein ${status === "done" ? "btn-primaer" : "btn-sekundaer"}`} onClick={() => setStatus("done")}>Erledigt</button>
      </Seitenkopf>

      <div className="werkzeugleiste">
        <form style={{ display: "flex", gap: "var(--am-raum-2)", flex: "1 1 520px", flexWrap: "wrap" }} onSubmit={(e) => { e.preventDefault(); if (titel.trim()) anlegen.mutate(); }}>
          <input className="input" style={{ flex: "2 1 220px" }} value={titel} onChange={(e) => setTitel(e.target.value)} placeholder="Was ist zu tun?" aria-label="Neue Aufgabe" />
          <input className="input" style={{ flex: "0 0 160px" }} type="date" value={faellig} onChange={(e) => setFaellig(e.target.value)} aria-label="Fällig am" />
          <select className="input" style={{ flex: "1 1 200px" }} value={dealId} onChange={(e) => setDealId(e.target.value)} aria-label="Geschäft">
            <option value="">— ohne Geschäft —</option>
            {deals.data?.map((d) => <option key={d.id} value={d.id}>{d.name}{d.company_name ? ` · ${d.company_name}` : ""}</option>)}
          </select>
          <button type="submit" className="btn btn-primaer" disabled={!titel.trim() || anlegen.isPending}>Anlegen</button>
        </form>
      </div>

      <div className="liste">
        {abfrage.isPending && <Laedt />}
        {abfrage.isError && <Fehler text={(abfrage.error as Error).message} />}
        {(anlegen.isError || aendern.isError || setzeStatus.isError) && <Fehler text={((anlegen.error ?? aendern.error ?? setzeStatus.error) as Error).message} />}
        {abfrage.data?.length === 0 && <Leer titel={status === "open" ? "Nichts offen" : "Noch nichts erledigt"} text={status === "open" ? "Alles abgearbeitet." : "Erledigtes erscheint hier."} />}
        {abfrage.data && abfrage.data.length > 0 && (
          <table className="tabelle">
            <thead><tr><th style={{ width: "3rem" }}><span className="nur-vorleser">Erledigt</span></th><th>Aufgabe</th><th>Gehört zu</th><th>Fällig</th><th style={{ width: "10rem" }} /></tr></thead>
            <tbody>
              {abfrage.data.map((a) => (
                <tr key={a.id} style={{ cursor: "default" }}>
                  <td><input type="checkbox" aria-label={`„${a.title}“ ${status === "open" ? "erledigt" : "wieder öffnen"}`} checked={status === "done"} onChange={() => setzeStatus.mutate({ id: a.id, s: status === "open" ? "done" : "open" })} /></td>
                  <td className="haupt">
                    {bearbeite?.id === a.id ? (
                      <input className="input" value={bearbeite.title} onChange={(e) => setBearbeite({ ...bearbeite, title: e.target.value })} aria-label="Titel" />
                    ) : a.title}
                  </td>
                  <td>{a.deal_id ? <Link href={`/deals/${a.deal_id}`} style={{ textDecoration: "underline", textUnderlineOffset: "2px" }}>{a.deal_name}</Link> : a.company_id ? <Link href={`/firmen/${a.company_id}`} style={{ textDecoration: "underline", textUnderlineOffset: "2px" }}>{a.company_name}</Link> : "—"}</td>
                  <td>{bearbeite?.id === a.id ? <input className="input" type="date" value={bearbeite.due} onChange={(e) => setBearbeite({ ...bearbeite, due: e.target.value })} aria-label="Fällig" /> : a.due_at ? datumZeit(a.due_at) : "—"}</td>
                  <td style={{ textAlign: "right", whiteSpace: "nowrap" }}>
                    {bearbeite?.id === a.id ? (
                      <><button type="button" className="btn btn-primaer btn-klein" onClick={() => aendern.mutate()}>Speichern</button> <button type="button" className="btn btn-still btn-klein" onClick={() => setBearbeite(null)}>Abbrechen</button></>
                    ) : (
                      <><button type="button" className="btn btn-still btn-klein" onClick={() => setBearbeite({ id: a.id, title: a.title, due: a.due_at ? a.due_at.slice(0, 10) : "" })}>Bearbeiten</button> <button type="button" className="btn btn-still btn-klein" onClick={() => setzeStatus.mutate({ id: a.id, s: "cancelled" })}>Verwerfen</button></>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </>
  );
}
