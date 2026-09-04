"use client";

import { useMutation } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "@/lib/api";
import { STUFEN_TEXT } from "@/lib/format";
import type { Company, Erfassungsvorschlag, LifecycleStage } from "@/lib/typen";
import { Erfassung } from "@/components/erfassung";
import { Fehler } from "@/components/zustaende";

export function FirmaAnlegen({
  beiSchliessen,
  beiErfolg,
}: {
  beiSchliessen: () => void;
  beiErfolg: (id: string) => void;
}) {
  const [name, setName] = useState("");
  const [domain, setDomain] = useState("");
  const [branche, setBranche] = useState("");
  const [ort, setOrt] = useState("");
  const [stufe, setStufe] = useState<LifecycleStage>("lead");
  // Was das Modell noch gelesen hat und wofür die Maske kein Feld führt.
  // Es geht trotzdem mit — sonst wäre es zweimal getippt.
  const [weitere, setWeitere] = useState<Record<string, string>>({});

  const anlegen = useMutation({
    mutationFn: () =>
      api.post<Company>("/api/companies", {
        ...weitere,
        name,
        domain: domain || null,
        industry: branche || null,
        city: ort || null,
        lifecycle_stage: stufe,
      }),
    onSuccess: (firma) => beiErfolg(firma.id),
  });

  /** Das Gelesene übernehmen — nur in Felder, die noch leer sind. */
  function uebernehmen(v: Erfassungsvorschlag) {
    const f = v.felder;
    if (f.name) setName((a) => a || f.name);
    if (f.domain) setDomain((a) => a || f.domain);
    if (f.industry) setBranche((a) => a || f.industry);
    if (f.city) setOrt((a) => a || f.city);
    // Straße, PLZ, Land, Telefon, Website, LinkedIn und Beschreibung
    // haben in dieser Maske kein Feld; sie gehen beim Anlegen trotzdem mit
    // und stehen danach am Datensatz.
    const rest: Record<string, string> = {};
    for (const k of ["street", "postal_code", "country", "phone", "website", "linkedin_url", "description"]) {
      if (f[k]) rest[k] = f[k];
    }
    if (v.rest && !rest.description) rest.description = v.rest;
    setWeitere(rest);
  }

  const mit = Object.keys(weitere).length;

  return (
    <div className="dialog-schicht" role="dialog" aria-modal="true" aria-label="Firma anlegen">
      <div className="karte dialog-karte" style={{ maxWidth: "480px", width: "100%" }}>
        <h2 style={{ marginBottom: "var(--am-raum-4)", fontSize: "1.125rem" }}>Firma anlegen</h2>

        <Erfassung art="company" beiErgebnis={uebernehmen} />
        <form
          onSubmit={(e) => {
            e.preventDefault();
            anlegen.mutate();
          }}
        >
          <div className="feld">
            <label htmlFor="firma-name">Name</label>
            <input id="firma-name" value={name} onChange={(e) => setName(e.target.value)} required />
          </div>
          <div className="feld">
            <label htmlFor="firma-domain">
              Domain <span className="optional">optional</span>
            </label>
            <input
              id="firma-domain"
              value={domain}
              onChange={(e) => setDomain(e.target.value)}
              placeholder="beispiel.de"
            />
          </div>
          <div className="feld">
            <label htmlFor="firma-branche">
              Branche <span className="optional">optional</span>
            </label>
            <input id="firma-branche" value={branche} onChange={(e) => setBranche(e.target.value)} />
          </div>
          <div className="feld">
            <label htmlFor="firma-ort">
              Ort <span className="optional">optional</span>
            </label>
            <input id="firma-ort" value={ort} onChange={(e) => setOrt(e.target.value)} />
          </div>
          <div className="feld">
            <label htmlFor="firma-stufe">Stufe</label>
            <select
              id="firma-stufe"
              value={stufe}
              onChange={(e) => setStufe(e.target.value as LifecycleStage)}
            >
              {Object.entries(STUFEN_TEXT).map(([wert, text]) => (
                <option key={wert} value={wert}>
                  {text}
                </option>
              ))}
            </select>
          </div>

          {mit > 0 && (
            <p className="erfassung-hinweis">
              Dazu {mit === 1 ? "geht eine weitere Angabe" : `gehen ${mit} weitere Angaben`} mit:{" "}
              {Object.keys(weitere).map((k) => FELDTEXT[k] ?? k).join(", ")}.
            </p>
          )}

          {anlegen.isError && <Fehler text={(anlegen.error as Error).message} />}

          <div className="btn-reihe" style={{ marginTop: "var(--am-raum-6)" }}>
            <button type="submit" className="btn btn-primaer" disabled={anlegen.isPending}>
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

/** Damit der Hinweis Feldnamen nennt, keine Spaltennamen. */
const FELDTEXT: Record<string, string> = {
  street: "Straße",
  postal_code: "PLZ",
  country: "Land",
  phone: "Telefon",
  website: "Website",
  linkedin_url: "LinkedIn",
  description: "Beschreibung",
};
