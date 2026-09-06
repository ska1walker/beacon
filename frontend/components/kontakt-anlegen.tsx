"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "@/lib/api";
import { firmenschluessel } from "@/lib/format";
import type { Company, Contact, Erfassungsvorschlag } from "@/lib/typen";
import { Erfassung } from "@/components/erfassung";
import { Finden, Wegwahl } from "@/components/finden";
import { Fehler } from "@/components/zustaende";

const LEER = {
  first_name: "",
  last_name: "",
  email: "",
  phone: "",
  mobile: "",
  job_title: "",
  buying_role: "",
  linkedin_url: "",
  notes: "",
  company_id: "",
};

export function KontaktAnlegen({
  firmaId,
  beiSchliessen,
  beiErfolg,
}: {
  firmaId?: string;
  beiSchliessen: () => void;
  beiErfolg: (id: string) => void;
}) {
  const client = useQueryClient();
  const [werte, setWerte] = useState({ ...LEER, company_id: firmaId ?? "" });
  // Die Firma aus der Signatur, die es im Bestand noch nicht gibt. Sie
  // wegzuwerfen wäre die schlechteste Antwort: Sie stand da.
  const [neueFirma, setNeueFirma] = useState<Record<string, string> | null>(null);
  const [weg, setWeg] = useState<"finden" | "werfen">("finden");

  const firmen = useQuery({
    queryKey: ["firmen-auswahl"],
    queryFn: () => api.get<Company[]>("/api/companies?limit=200"),
    enabled: !firmaId,
  });
  // Von der Firmenseite aus steht die Firma fest — dann sucht „Beschreiben“
  // nur noch die Person, und braucht dafür Name und Website.
  const feste = useQuery({
    queryKey: ["firma", firmaId],
    queryFn: () => api.get<Company>(`/api/companies/${firmaId}`),
    enabled: Boolean(firmaId),
  });

  const anlegen = useMutation({
    mutationFn: () =>
      api.post<Contact>("/api/contacts", {
        ...Object.fromEntries(Object.entries(werte).map(([k, v]) => [k, v || null])),
      }),
    onSuccess: (k) => beiErfolg(k.id),
  });

  /** Die genannte Firma anlegen und gleich verknüpfen. */
  const firmaAnlegen = useMutation({
    mutationFn: () =>
      api.post<Company>("/api/companies", {
        name: neueFirma!.firma_name,
        domain: neueFirma!.firma_domain || null,
        street: neueFirma!.firma_strasse || null,
        postal_code: neueFirma!.firma_plz || null,
        city: neueFirma!.firma_ort || null,
        phone: neueFirma!.firma_telefon || null,
      }),
    onSuccess: (f) => {
      setWerte((a) => ({ ...a, company_id: f.id }));
      setNeueFirma(null);
      client.invalidateQueries({ queryKey: ["firmen-auswahl"] });
      client.invalidateQueries({ queryKey: ["segment", "companies"] });
    },
  });

  const setze =
    (k: keyof typeof werte) =>
    (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement>) =>
      setWerte((a) => ({ ...a, [k]: e.target.value }));

  /**
   * Das Gelesene in die Maske übernehmen.
   *
   * Überschrieben wird nur, was leer ist. Wer schon getippt hat, soll
   * das nicht an eine zweite Signatur verlieren.
   */
  function uebernehmen(v: Erfassungsvorschlag) {
    const f = v.felder;
    setWerte((a) => {
      const neu = { ...a };
      for (const k of Object.keys(LEER) as (keyof typeof LEER)[]) {
        if (!neu[k] && f[k]) neu[k] = f[k];
      }
      if (!neu.notes && v.rest) neu.notes = v.rest;

      const treffer = passendeFirma(firmen.data, f);
      if (!neu.company_id && treffer) neu.company_id = treffer.id;
      return neu;
    });

    setNeueFirma(f.firma_name && !passendeFirma(firmen.data, f) && !firmaId ? f : null);
  }

  return (
    <div className="dialog-schicht" role="dialog" aria-modal="true" aria-label="Kontakt anlegen">
      <div className="karte dialog-karte" style={{ maxWidth: "520px", width: "100%" }}>
        <h2 style={{ marginBottom: "var(--am-raum-4)", fontSize: "1.125rem" }}>Kontakt anlegen</h2>

        <Wegwahl weg={weg} setWeg={setWeg} />
        {weg === "finden" ? (
          <Finden
            art="contact"
            firma={firmaId && feste.data ? { name: feste.data.name, website: feste.data.website || feste.data.domain } : undefined}
            beiErgebnis={uebernehmen}
          />
        ) : (
          <Erfassung art="contact" beiErgebnis={uebernehmen} />
        )}

        {neueFirma && (
          <p className="erfassung-hinweis">
            „{neueFirma.firma_name}“ steht noch nicht im Bestand.{" "}
            <button
              type="button"
              className="alsLink"
              disabled={firmaAnlegen.isPending}
              onClick={() => firmaAnlegen.mutate()}
            >
              {firmaAnlegen.isPending ? "Legt an …" : "Anlegen und verknüpfen"}
            </button>
          </p>
        )}
        {firmaAnlegen.isError && <Fehler text={(firmaAnlegen.error as Error).message} />}

        <form onSubmit={(e) => { e.preventDefault(); anlegen.mutate(); }}>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "0 var(--am-raum-4)" }}>
            <div className="feld"><label htmlFor="k-vn">Vorname</label><input id="k-vn" value={werte.first_name} onChange={setze("first_name")} /></div>
            <div className="feld"><label htmlFor="k-nn">Nachname</label><input id="k-nn" value={werte.last_name} onChange={setze("last_name")} required /></div>
          </div>
          <div className="feld"><label htmlFor="k-mail">E-Mail <span className="optional">optional</span></label><input id="k-mail" type="email" value={werte.email} onChange={setze("email")} /></div>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "0 var(--am-raum-4)" }}>
            <div className="feld"><label htmlFor="k-tel">Telefon <span className="optional">optional</span></label><input id="k-tel" value={werte.phone} onChange={setze("phone")} /></div>
            <div className="feld"><label htmlFor="k-mob">Mobil <span className="optional">optional</span></label><input id="k-mob" value={werte.mobile} onChange={setze("mobile")} /></div>
          </div>
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
          {werte.linkedin_url && (
            <div className="feld"><label htmlFor="k-li">LinkedIn</label><input id="k-li" value={werte.linkedin_url} onChange={setze("linkedin_url")} /></div>
          )}
          <div className="feld">
            <label htmlFor="k-notiz">Notizen <span className="optional">optional</span></label>
            <textarea id="k-notiz" rows={2} value={werte.notes} onChange={setze("notes")} />
          </div>
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

/**
 * Die genannte Firma im Bestand finden.
 *
 * Zuerst über die Domain — die ist eindeutig. Dann über den Namen ohne
 * Rechtsform, weil eine Signatur „mbB" schreibt und der Bestand meist
 * nicht.
 */
function passendeFirma(
  firmen: Company[] | undefined,
  f: Record<string, string>,
): Company | undefined {
  if (!firmen) return undefined;
  if (f.firma_domain) {
    const ueberDomain = firmen.find(
      (x) => x.domain?.toLowerCase() === f.firma_domain.toLowerCase(),
    );
    if (ueberDomain) return ueberDomain;
  }
  if (!f.firma_name) return undefined;
  const gesucht = firmenschluessel(f.firma_name);
  return firmen.find((x) => firmenschluessel(x.name) === gesucht);
}
