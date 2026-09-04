"use client";

import { useMutation, useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "@/lib/api";
import { PRODUKT_TEXT } from "@/lib/format";
import type { Company, Contact, Deal, DealProduct, Stage } from "@/lib/typen";
import { Mehrfachauswahl } from "@/components/mehrfachauswahl";
import { Fehler } from "@/components/zustaende";

// Die Listenpreise aus claude/Produkte.md. Sie füllen den Betrag vor,
// wenn ein Produkt gewählt wird — überschreibbar, denn beim Experten
// kommen Leistungen dazu.
const LISTENPREIS: Record<DealProduct, number> = {
  assistent: 9900,
  analyst: 14500,
  experte: 14500,
  service: 0,
  sonstiges: 0,
};

export function DealAnlegen({
  pipelineId,
  stufen,
  firmaId,
  beiSchliessen,
  beiErfolg,
}: {
  pipelineId?: string;
  stufen: Stage[];
  firmaId?: string;
  beiSchliessen: () => void;
  beiErfolg: () => void;
}) {
  const [name, setName] = useState("");
  const [produkt, setProdukt] = useState<DealProduct>("assistent");
  const [betrag, setBetrag] = useState(String(LISTENPREIS.assistent));
  const [firma, setFirma] = useState(firmaId ?? "");
  const [stufe, setStufe] = useState(stufen[0]?.id ?? "");
  const [datum, setDatum] = useState("");
  // Ansprechpartner sind hier bewusst mehrere und bewusst freiwillig.
  // Ein Lead entsteht oft aus einem Anruf, bei dem noch nicht feststeht,
  // wer im Haus entscheidet.
  const [kontakte, setKontakte] = useState<string[]>([]);

  const firmen = useQuery({
    queryKey: ["firmen-auswahl"],
    queryFn: () => api.get<Company[]>("/api/companies?limit=200"),
    enabled: !firmaId,
  });

  const alleKontakte = useQuery({
    queryKey: ["kontakte-auswahl"],
    queryFn: () => api.get<Contact[]>("/api/contacts?limit=200"),
  });

  const anlegen = useMutation({
    mutationFn: async () => {
      const lead = await api.post<Deal>("/api/deals", {
        name,
        product: produkt,
        pipeline_id: pipelineId ?? null,
        amount_cents: Math.round(Number(betrag || 0) * 100),
        company_id: firma || null,
        stage_id: stufe || null,
        close_date: datum || null,
      });
      // Nacheinander, nicht parallel: Der erste Beteiligte darf seine
      // Firma an einen Lead ohne Firma vererben, und wer gleichzeitig
      // schreibt, überlässt es dem Zufall, welcher das ist.
      for (const id of kontakte) {
        await api.post(`/api/deals/${lead.id}/beteiligte`, { contact_id: id });
      }
      return lead;
    },
    onSuccess: beiErfolg,
  });

  return (
    <div className="dialog-schicht" role="dialog" aria-modal="true" aria-label="Lead anlegen">
      <div className="karte" style={{ maxWidth: "480px", width: "100%", padding: "var(--am-raum-6)" }}>
        <h2 style={{ marginBottom: "var(--am-raum-6)", fontSize: "1.125rem" }}>Lead anlegen</h2>

        <form
          onSubmit={(e) => {
            e.preventDefault();
            anlegen.mutate();
          }}
        >
          <div className="feld">
            <label htmlFor="deal-name">Bezeichnung</label>
            <input
              id="deal-name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              required
              placeholder="Analyst — Jahresabschlussauswertung"
            />
          </div>

          <div className="feld">
            <label htmlFor="deal-produkt">Produkt</label>
            <select
              id="deal-produkt"
              value={produkt}
              onChange={(e) => {
                const p = e.target.value as DealProduct;
                setProdukt(p);
                // Nur vorfüllen, nie überschreiben, was jemand getippt hat.
                if (LISTENPREIS[p] > 0) setBetrag(String(LISTENPREIS[p]));
              }}
            >
              {Object.keys(PRODUKT_TEXT).map((p) => (
                <option key={p} value={p}>
                  {PRODUKT_TEXT[p]}
                </option>
              ))}
            </select>
          </div>

          <div className="feld">
            <label htmlFor="deal-betrag">Betrag netto in Euro</label>
            <input
              id="deal-betrag"
              type="number"
              min="0"
              step="100"
              value={betrag}
              onChange={(e) => setBetrag(e.target.value)}
            />
          </div>

          {!firmaId && (
            <div className="feld">
              <label htmlFor="deal-firma">
                Firma <span className="optional">optional</span>
              </label>
              <select id="deal-firma" value={firma} onChange={(e) => setFirma(e.target.value)}>
                <option value="">— keine —</option>
                {firmen.data?.map((f) => (
                  <option key={f.id} value={f.id}>
                    {f.name}
                  </option>
                ))}
              </select>
            </div>
          )}

          <div className="feld">
            <label htmlFor="deal-kontakte">
              Ansprechpartner <span className="optional">optional</span>
            </label>
            <Mehrfachauswahl
              id="deal-kontakte"
              ariaLabel="Ansprechpartner"
              platzhalter="noch niemand"
              optionen={(alleKontakte.data ?? []).map((k) => ({
                wert: k.id,
                text:
                  [k.first_name, k.last_name].filter(Boolean).join(" ") ||
                  k.email ||
                  "Kontakt",
              }))}
              gewaehlt={kontakte}
              beiAendern={setKontakte}
            />
            <p className="feld-hinweis">
              Lässt sich später am Lead ergänzen — ebenso wie die Firma.
            </p>
          </div>

          <div className="feld">
            <label htmlFor="deal-stufe">Stufe</label>
            <select id="deal-stufe" value={stufe} onChange={(e) => setStufe(e.target.value)}>
              {stufen.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.name}
                </option>
              ))}
            </select>
          </div>

          <div className="feld">
            <label htmlFor="deal-datum">
              Abschluss geplant <span className="optional">optional</span>
            </label>
            <input
              id="deal-datum"
              type="date"
              value={datum}
              onChange={(e) => setDatum(e.target.value)}
            />
          </div>

          {anlegen.isError && <Fehler text={(anlegen.error as Error).message} />}

          <div className="btn-reihe" style={{ marginTop: "var(--am-raum-6)" }}>
            <button type="submit" className="btn btn-primaer" disabled={anlegen.isPending || !name.trim()}>
              {anlegen.isPending ? "Wird angelegt …" : "Anlegen"}
            </button>
            <button type="button" className="btn btn-still" onClick={beiSchliessen}>
              Abbrechen
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
