"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "@/lib/api";
import { euro } from "@/lib/format";
import type { Product, Verlustgrund } from "@/lib/typen";
import { Fehler, Laedt } from "@/components/zustaende";

const ART: Record<string, string> = { system: "System", hardware: "Hardware", service: "Leistung", subscription: "Laufend" };

/** Produktkatalog: Preise sind hier gepflegt, nirgends sonst. */
export function Katalogblock() {
  const client = useQueryClient();
  const [neu, setNeu] = useState({ name: "", key: "", preis: "", tage: "", kind: "service" });
  const produkte = useQuery({ queryKey: ["produkte-alle"], queryFn: () => api.get<Product[]>("/api/products?nur_aktive=false") });
  const frisch = () => { client.invalidateQueries({ queryKey: ["produkte-alle"] }); client.invalidateQueries({ queryKey: ["produkte"] }); };
  const aendern = useMutation({ mutationFn: ({ id, ...rest }: { id: string } & Record<string, unknown>) => api.patch(`/api/products/${id}`, rest), onSuccess: frisch });
  const anlegen = useMutation({
    mutationFn: () => api.post("/api/products", { name: neu.name, key: neu.key || neu.name.toLowerCase().replace(/[^a-z0-9]+/g, "-"), kind: neu.kind, list_price_cents: Math.round(Number(neu.preis || 0) * 100), default_service_days: neu.tage ? Number(neu.tage) : null, position: produkte.data?.length ?? 0 }),
    onSuccess: () => { setNeu({ name: "", key: "", preis: "", tage: "", kind: "service" }); frisch(); },
  });
  if (produkte.isPending) return <Laedt />;
  return (
    <section className="block">
      <div className="block-kopf"><h2>Produktkatalog</h2></div>
      <div className="block-inhalt">
        <p style={{ fontSize: "0.875rem", color: "var(--am-text-sekundaer)", marginBottom: "var(--am-raum-4)" }}>
          Die Listenpreise für Angebote. Ein Angebot kopiert den Preis beim Anlegen — spätere Änderungen hier ändern kein liegendes Angebot.
        </p>
        <table className="tabelle" style={{ marginBottom: "var(--am-raum-4)" }}>
          <thead><tr><th>Produkt</th><th>Art</th><th style={{ textAlign: "right" }}>Netto €</th><th style={{ textAlign: "right" }}>Servicetage</th><th /></tr></thead>
          <tbody>
            {produkte.data!.map((p) => (
              <tr key={p.id} style={{ cursor: "default", opacity: p.is_active ? 1 : 0.5 }}>
                <td><input className="input" aria-label="Name" defaultValue={p.name} onBlur={(e) => e.target.value.trim() && e.target.value !== p.name && aendern.mutate({ id: p.id, name: e.target.value.trim() })} /></td>
                <td>{ART[p.kind] ?? p.kind}</td>
                <td className="zahl"><input className="input" type="number" min="0" step="100" aria-label="Preis" defaultValue={p.list_price_cents / 100} onBlur={(e) => { const c = Math.round(Number(e.target.value) * 100); if (c !== p.list_price_cents) aendern.mutate({ id: p.id, list_price_cents: c }); }} /></td>
                <td className="zahl"><input className="input" type="number" min="0" aria-label="Servicetage" defaultValue={p.default_service_days ?? ""} onBlur={(e) => { const t = e.target.value === "" ? null : Number(e.target.value); if (t !== p.default_service_days) aendern.mutate({ id: p.id, default_service_days: t }); }} /></td>
                <td style={{ textAlign: "right" }}><button type="button" className="btn btn-still btn-klein" onClick={() => aendern.mutate({ id: p.id, is_active: !p.is_active })}>{p.is_active ? "Abschalten" : "Einschalten"}</button></td>
              </tr>
            ))}
          </tbody>
        </table>
        {(aendern.isError || anlegen.isError) && <Fehler text={((aendern.error ?? anlegen.error) as Error).message} />}
        <form style={{ display: "grid", gridTemplateColumns: "2fr 1fr 1fr 1fr auto", gap: "var(--am-raum-2)", alignItems: "end" }} onSubmit={(e) => { e.preventDefault(); if (neu.name.trim()) anlegen.mutate(); }}>
          <div className="feld" style={{ marginBottom: 0 }}><label htmlFor="pk-name">Neues Produkt</label><input id="pk-name" value={neu.name} onChange={(e) => setNeu({ ...neu, name: e.target.value })} placeholder="Einführungstag" /></div>
          <div className="feld" style={{ marginBottom: 0 }}><label htmlFor="pk-art">Art</label><select id="pk-art" value={neu.kind} onChange={(e) => setNeu({ ...neu, kind: e.target.value })}>{Object.entries(ART).map(([w, t]) => <option key={w} value={w}>{t}</option>)}</select></div>
          <div className="feld" style={{ marginBottom: 0 }}><label htmlFor="pk-preis">Netto €</label><input id="pk-preis" type="number" min="0" value={neu.preis} onChange={(e) => setNeu({ ...neu, preis: e.target.value })} /></div>
          <div className="feld" style={{ marginBottom: 0 }}><label htmlFor="pk-tage">Tage</label><input id="pk-tage" type="number" min="0" value={neu.tage} onChange={(e) => setNeu({ ...neu, tage: e.target.value })} /></div>
          <button type="submit" className="btn btn-primaer btn-klein" disabled={!neu.name.trim() || anlegen.isPending}>Anlegen</button>
        </form>
      </div>
    </section>
  );
}

/** Verlustgründe pflegen. */
export function Verlustgruendeblock() {
  const client = useQueryClient();
  const [name, setName] = useState("");
  const gruende = useQuery({ queryKey: ["verlustgruende"], queryFn: () => api.get<Verlustgrund[]>("/api/verlustgruende") });
  const frisch = () => client.invalidateQueries({ queryKey: ["verlustgruende"] });
  const anlegen = useMutation({ mutationFn: () => api.post("/api/verlustgruende", { name }), onSuccess: () => { setName(""); frisch(); } });
  const aendern = useMutation({ mutationFn: ({ id, ...rest }: { id: string } & Record<string, unknown>) => api.patch(`/api/verlustgruende/${id}`, rest), onSuccess: frisch });
  return (
    <section className="block">
      <div className="block-kopf"><h2>Verlustgründe</h2></div>
      <div className="block-inhalt">
        <table className="tabelle" style={{ marginBottom: "var(--am-raum-4)" }}>
          <tbody>
            {gruende.data?.map((g) => (
              <tr key={g.id} style={{ cursor: "default" }}>
                <td><input className="input" aria-label="Grund" defaultValue={g.name} onBlur={(e) => e.target.value.trim() && e.target.value !== g.name && aendern.mutate({ id: g.id, name: e.target.value.trim() })} /></td>
                <td style={{ textAlign: "right" }}><button type="button" className="btn btn-still btn-klein" onClick={() => aendern.mutate({ id: g.id, is_active: false })}>Abschalten</button></td>
              </tr>
            ))}
          </tbody>
        </table>
        {(anlegen.isError || aendern.isError) && <Fehler text={((anlegen.error ?? aendern.error) as Error).message} />}
        <form style={{ display: "flex", gap: "var(--am-raum-2)" }} onSubmit={(e) => { e.preventDefault(); if (name.trim()) anlegen.mutate(); }}>
          <input className="input" value={name} onChange={(e) => setName(e.target.value)} placeholder="Neuer Grund" aria-label="Neuer Verlustgrund" />
          <button type="submit" className="btn btn-sekundaer btn-klein" disabled={!name.trim()}>Anlegen</button>
        </form>
      </div>
    </section>
  );
}
