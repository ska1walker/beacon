"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { X } from "lucide-react";
import { useState } from "react";
import { api } from "@/lib/api";
import type { Besprechung, BesprechungVoll, Company, Contact, Deal } from "@/lib/typen";
import { Mehrfachauswahl } from "@/components/mehrfachauswahl";
import { Fehler } from "@/components/zustaende";

function kontaktname(k: Pick<Contact, "first_name" | "last_name" | "email">): string {
  return [k.first_name, k.last_name].filter(Boolean).join(" ") || k.email || "Kontakt";
}

/**
 * Eine Besprechung einem Kunden zuordnen — von Hand, mit dem Vorschlag
 * als Ausgangspunkt.
 *
 * Firma zuerst, dann deren Kontakte und Leads: Wer die Firma kennt, will
 * nicht aus zweihundert Kontakten wählen. Passt ein Name auf mehrere
 * Kontakte, stehen die Kandidaten oben als Abkürzung — mit ihrer Firma,
 * denn genau daran unterscheidet man die beiden Meyers.
 */
export function BesprechungZuordnen({
  besprechung,
  beiSchliessen,
  beiErfolg,
}: {
  besprechung: Besprechung;
  beiSchliessen: () => void;
  beiErfolg?: (b: BesprechungVoll) => void;
}) {
  const client = useQueryClient();
  const v = besprechung.vorschlag;
  const [firma, setFirma] = useState(besprechung.company?.id ?? v?.company?.id ?? "");
  const [kontakte, setKontakte] = useState<string[]>(
    besprechung.kontakte.length ? besprechung.kontakte.map((k) => k.id) : (v?.kontakte ?? []).map((k) => k.id),
  );
  const [lead, setLead] = useState(besprechung.deal?.id ?? v?.deal?.id ?? "");

  const firmen = useQuery({
    queryKey: ["firmen-auswahl"],
    queryFn: () => api.get<Company[]>("/api/companies?limit=200&sort=name&richtung=asc"),
  });
  const firmenkontakte = useQuery({
    queryKey: ["kontakte-der-firma", firma],
    queryFn: () => api.get<Contact[]>(`/api/contacts?company_id=${firma}&limit=200`),
    enabled: Boolean(firma),
  });
  const leads = useQuery({
    queryKey: ["leads-der-firma", firma],
    queryFn: () => api.get<Deal[]>(`/api/deals?company_id=${firma}&status=open`),
    enabled: Boolean(firma),
  });

  const zuordnen = useMutation({
    mutationFn: () =>
      api.post<BesprechungVoll>(`/api/besprechungen/${besprechung.id}/zuordnen`, {
        company_id: firma || null,
        contact_ids: kontakte,
        deal_id: lead || null,
      }),
    onSuccess: (b) => {
      client.invalidateQueries({ queryKey: ["besprechungen"] });
      client.invalidateQueries({ queryKey: ["besprechung", besprechung.id] });
      client.invalidateQueries({ queryKey: ["briefing"] });
      beiErfolg?.(b);
      beiSchliessen();
    },
  });

  function firmaWechseln(neu: string) {
    setFirma(neu);
    // Kontakte und Lead gehören zur Firma; eine neue Firma nimmt sie mit.
    setKontakte([]);
    setLead("");
  }

  // Firmen, die zur Auswahl stehen: der Bestand, plus eine vorgeschlagene,
  // falls sie jenseits der ersten zweihundert liegt.
  const firmenliste = [...(firmen.data ?? [])];
  for (const b of [besprechung.company, v?.company]) {
    if (b && !firmenliste.some((f) => f.id === b.id)) firmenliste.unshift({ id: b.id, name: b.name } as Company);
  }

  return (
    <div className="dialog-schicht" role="dialog" aria-modal="true" aria-label="Besprechung zuordnen">
      <div className="karte dialog-karte" style={{ maxWidth: "560px", width: "100%" }}>
        <div className="dialog-kopf">
          <h2>Zuordnen</h2>
          <button type="button" className="dialog-zu" aria-label="Schließen" onClick={beiSchliessen}>
            <X size={18} aria-hidden="true" />
          </button>
        </div>

        <form
          className="dialog-form"
          onSubmit={(e) => {
            e.preventDefault();
            zuordnen.mutate();
          }}
        >
          <div className="dialog-koerper">
            <p className="erfassung-hinweis" style={{ marginTop: 0, marginBottom: "var(--am-raum-4)" }}>
              <strong style={{ color: "var(--am-text-primaer)" }}>{besprechung.titel || "Besprechung"}</strong>
              {besprechung.beteiligte.length > 0 && <> · genannt: {besprechung.beteiligte.join(", ")}</>}
            </p>

            {v?.mehrdeutig && v.kandidaten.length > 0 && (
              <div className="feld">
                <p className="feld-hinweis" style={{ marginTop: 0 }}>{v.grund}</p>
                <ul className="finden-kandidaten" style={{ margin: 0 }}>
                  {v.kandidaten.map((k) => (
                    <li key={k.contact_id} style={{ listStyle: "none" }}>
                      <button
                        type="button"
                        className="finden-kandidat"
                        onClick={() => {
                          if (k.company_id) setFirma(k.company_id);
                          setKontakte([k.contact_id]);
                          setLead("");
                        }}
                      >
                        <span className="finden-kandidat-name">{k.name}</span>
                        <span className="finden-kandidat-unter">{k.company_name ?? "ohne Firma"}</span>
                        <span className="finden-kandidat-aktion">Wählen</span>
                      </button>
                    </li>
                  ))}
                </ul>
              </div>
            )}

            <div className="feld">
              <label htmlFor="bz-firma">Firma</label>
              <select id="bz-firma" value={firma} onChange={(e) => firmaWechseln(e.target.value)}>
                <option value="">— keine —</option>
                {firmenliste.map((f) => (
                  <option key={f.id} value={f.id}>{f.name}</option>
                ))}
              </select>
            </div>

            <div className="feld">
              <label htmlFor="bz-kontakte">
                Beteiligte beim Kunden <span className="optional">optional</span>
              </label>
              <Mehrfachauswahl
                id="bz-kontakte"
                ariaLabel="Beteiligte beim Kunden"
                platzhalter={firma ? "niemand gewählt" : "erst die Firma wählen"}
                deaktiviert={!firma}
                optionen={(firmenkontakte.data ?? []).map((k) => ({ wert: k.id, text: kontaktname(k) }))}
                gewaehlt={kontakte}
                beiAendern={setKontakte}
              />
              <p className="feld-hinweis">Die Besprechung steht danach an jedem gewählten Kontakt.</p>
            </div>

            <div className="feld">
              <label htmlFor="bz-lead">
                Lead <span className="optional">optional</span>
              </label>
              <select id="bz-lead" value={lead} onChange={(e) => setLead(e.target.value)} disabled={!firma}>
                <option value="">— keiner —</option>
                {(leads.data ?? []).map((d) => (
                  <option key={d.id} value={d.id}>{d.name}</option>
                ))}
              </select>
            </div>

            {zuordnen.isError && <Fehler text={(zuordnen.error as Error).message} />}
          </div>

          <div className="dialog-fuss">
            <button type="submit" className="btn btn-primaer" disabled={zuordnen.isPending || !(firma || kontakte.length)}>
              {zuordnen.isPending ? "Ordnet zu …" : "Zuordnen"}
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
