"use client";

import { useMutation } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "@/lib/api";
import { STUFEN_TEXT } from "@/lib/format";
import type { Company, LifecycleStage } from "@/lib/typen";
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

  const anlegen = useMutation({
    mutationFn: () =>
      api.post<Company>("/api/companies", {
        name,
        domain: domain || null,
        industry: branche || null,
        city: ort || null,
        lifecycle_stage: stufe,
      }),
    onSuccess: (firma) => beiErfolg(firma.id),
  });

  return (
    <div className="dialog-schicht" role="dialog" aria-modal="true" aria-label="Firma anlegen">
      <div className="karte" style={{ maxWidth: "440px", width: "100%" }}>
        <h2 style={{ marginBottom: "var(--am-raum-6)", fontSize: "1.125rem" }}>Firma anlegen</h2>
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
