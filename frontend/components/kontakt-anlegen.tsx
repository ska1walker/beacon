"use client";

import { useMutation, useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "@/lib/api";
import type { Company, Contact } from "@/lib/typen";
import { Fehler } from "@/components/zustaende";

export function KontaktAnlegen({
  firmaId,
  beiSchliessen,
  beiErfolg,
}: {
  firmaId?: string;
  beiSchliessen: () => void;
  beiErfolg: (id: string) => void;
}) {
  const [werte, setWerte] = useState({ first_name: "", last_name: "", email: "", phone: "", job_title: "", buying_role: "", company_id: firmaId ?? "" });
  const firmen = useQuery({
    queryKey: ["firmen-auswahl"],
    queryFn: () => api.get<Company[]>("/api/companies?limit=200"),
    enabled: !firmaId,
  });
  const anlegen = useMutation({
    mutationFn: () =>
      api.post<Contact>("/api/contacts", {
        ...Object.fromEntries(Object.entries(werte).map(([k, v]) => [k, v || null])),
      }),
    onSuccess: (k) => beiErfolg(k.id),
  });
  const setze = (k: keyof typeof werte) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) =>
    setWerte((a) => ({ ...a, [k]: e.target.value }));

  return (
    <div className="dialog-schicht" role="dialog" aria-modal="true" aria-label="Kontakt anlegen">
      <div className="karte" style={{ maxWidth: "480px", width: "100%" }}>
        <h2 style={{ marginBottom: "var(--am-raum-6)", fontSize: "1.125rem" }}>Kontakt anlegen</h2>
        <form onSubmit={(e) => { e.preventDefault(); anlegen.mutate(); }}>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "0 var(--am-raum-4)" }}>
            <div className="feld"><label htmlFor="k-vn">Vorname</label><input id="k-vn" value={werte.first_name} onChange={setze("first_name")} /></div>
            <div className="feld"><label htmlFor="k-nn">Nachname</label><input id="k-nn" value={werte.last_name} onChange={setze("last_name")} required /></div>
          </div>
          <div className="feld"><label htmlFor="k-mail">E-Mail <span className="optional">optional</span></label><input id="k-mail" type="email" value={werte.email} onChange={setze("email")} /></div>
          <div className="feld"><label htmlFor="k-tel">Telefon <span className="optional">optional</span></label><input id="k-tel" value={werte.phone} onChange={setze("phone")} /></div>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "0 var(--am-raum-4)" }}>
            <div className="feld"><label htmlFor="k-pos">Position</label><input id="k-pos" value={werte.job_title} onChange={setze("job_title")} placeholder="Partnerin" /></div>
            <div className="feld"><label htmlFor="k-rolle">Kaufrolle</label><input id="k-rolle" value={werte.buying_role} onChange={setze("buying_role")} placeholder="Entscheiderin" /></div>
          </div>
          {!firmaId && (
            <div className="feld">
              <label htmlFor="k-firma">Firma <span className="optional">optional</span></label>
              <select id="k-firma" value={werte.company_id} onChange={setze("company_id")}>
                <option value="">— keine —</option>
                {firmen.data?.map((f) => <option key={f.id} value={f.id}>{f.name}</option>)}
              </select>
            </div>
          )}
          {anlegen.isError && <Fehler text={(anlegen.error as Error).message} />}
          <div className="btn-reihe" style={{ marginTop: "var(--am-raum-4)" }}>
            <button type="submit" className="btn btn-primaer" disabled={anlegen.isPending || !werte.last_name.trim()}>{anlegen.isPending ? "Legt an …" : "Anlegen"}</button>
            <button type="button" className="btn btn-still" onClick={beiSchliessen}>Abbrechen</button>
          </div>
        </form>
      </div>
    </div>
  );
}
