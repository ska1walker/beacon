"use client";

import { useMutation, useQuery } from "@tanstack/react-query";
import { X } from "lucide-react";
import { useState } from "react";
import { api } from "@/lib/api";
import { PRIORITAET_TEXT } from "@/lib/format";
import type { Company, Contact, Ticket, Ticketkategorie, Ticketprioritaet } from "@/lib/typen";
import { Fehler } from "@/components/zustaende";

/**
 * Ein Anliegen aufnehmen.
 *
 * Betreff und Dringlichkeit reichen — alles andere lässt sich später am
 * Ticket nachtragen. Wer ein Formular mit zehn Pflichtfeldern vor sich
 * hat, während der Kunde am Telefon ist, legt gar kein Ticket an.
 */
export function TicketAnlegen({
  contactId,
  companyId,
  beiSchliessen,
  beiErfolg,
}: {
  contactId?: string;
  companyId?: string;
  beiSchliessen: () => void;
  beiErfolg: (id: string) => void;
}) {
  const [betreff, setBetreff] = useState("");
  const [beschreibung, setBeschreibung] = useState("");
  const [prioritaet, setPrioritaet] = useState<Ticketprioritaet>("mittel");
  const [kategorie, setKategorie] = useState("");
  const [kontakt, setKontakt] = useState(contactId ?? "");
  const [firma, setFirma] = useState(companyId ?? "");

  const kategorien = useQuery({
    queryKey: ["ticket-kategorien"],
    queryFn: () => api.get<Ticketkategorie[]>("/api/tickets/kategorien"),
  });

  const kontakte = useQuery({
    queryKey: ["kontakte-kurz"],
    queryFn: () => api.get<Contact[]>("/api/contacts?limit=200"),
    enabled: !contactId,
  });

  const firmen = useQuery({
    queryKey: ["firmen-kurz"],
    queryFn: () => api.get<Company[]>("/api/companies?limit=200"),
    enabled: !companyId,
  });

  const anlegen = useMutation({
    mutationFn: () =>
      api.post<Ticket>("/api/tickets", {
        betreff,
        beschreibung: beschreibung || null,
        prioritaet,
        kategorie: kategorie || null,
        contact_id: kontakt || null,
        company_id: firma || null,
      }),
    onSuccess: (t) => beiErfolg(t.id),
  });

  return (
    <div className="dialog-schicht" role="dialog" aria-modal="true" aria-label="Ticket anlegen">
      <div className="karte dialog-karte" style={{ maxWidth: "560px", width: "100%" }}>
        <div className="dialog-kopf">
          <h2>Ticket anlegen</h2>
          <button type="button" className="dialog-zu" aria-label="Schließen" onClick={beiSchliessen}>
            <X size={18} aria-hidden="true" />
          </button>
        </div>
        <form
          className="dialog-form"
          onSubmit={(e) => {
            e.preventDefault();
            if (betreff.trim()) anlegen.mutate();
          }}
        >
          <div className="dialog-koerper">
          <div className="feld">
            <label htmlFor="t-betreff">Betreff</label>
            <input
              id="t-betreff"
              value={betreff}
              onChange={(e) => setBetreff(e.target.value)}
              placeholder="Worum geht es?"
              autoFocus
            />
          </div>

          <div className="feld">
            <label htmlFor="t-beschreibung">
              Beschreibung <span className="optional">optional</span>
            </label>
            <textarea
              id="t-beschreibung"
              rows={4}
              value={beschreibung}
              onChange={(e) => setBeschreibung(e.target.value)}
              placeholder="Was ist passiert, was wurde schon versucht?"
            />
          </div>

          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "var(--am-raum-4)" }}>
            <div className="feld">
              <label htmlFor="t-prio">Dringlichkeit</label>
              <select
                id="t-prio"
                value={prioritaet}
                onChange={(e) => setPrioritaet(e.target.value as Ticketprioritaet)}
              >
                {Object.entries(PRIORITAET_TEXT).map(([wert, text]) => (
                  <option key={wert} value={wert}>
                    {text}
                  </option>
                ))}
              </select>
              <p className="feld-hinweis">Die Frist entsteht daraus.</p>
            </div>

            <div className="feld">
              <label htmlFor="t-kat">
                Kategorie <span className="optional">optional</span>
              </label>
              <select id="t-kat" value={kategorie} onChange={(e) => setKategorie(e.target.value)}>
                <option value="">— keine —</option>
                {kategorien.data?.map((c) => (
                  <option key={c.id} value={c.name}>
                    {c.name}
                  </option>
                ))}
              </select>
            </div>
          </div>

          {!contactId && (
            <div className="feld">
              <label htmlFor="t-kontakt">
                Kontakt <span className="optional">optional</span>
              </label>
              <select id="t-kontakt" value={kontakt} onChange={(e) => setKontakt(e.target.value)}>
                <option value="">— niemand —</option>
                {kontakte.data?.map((c) => (
                  <option key={c.id} value={c.id}>
                    {[c.first_name, c.last_name].filter(Boolean).join(" ")}
                    {c.company_name ? ` · ${c.company_name}` : ""}
                  </option>
                ))}
              </select>
            </div>
          )}

          {!companyId && (
            <div className="feld">
              <label htmlFor="t-firma">
                Firma <span className="optional">optional</span>
              </label>
              <select id="t-firma" value={firma} onChange={(e) => setFirma(e.target.value)}>
                <option value="">— keine —</option>
                {firmen.data?.map((f) => (
                  <option key={f.id} value={f.id}>
                    {f.name}
                  </option>
                ))}
              </select>
            </div>
          )}

          {anlegen.isError && <Fehler text={(anlegen.error as Error).message} />}
          </div>

          <div className="dialog-fuss">
            <button type="submit" className="btn btn-primaer" disabled={!betreff.trim() || anlegen.isPending}>
              {anlegen.isPending ? "Legt an …" : "Anlegen"}
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
