"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { Absender, OrgSettings } from "@/lib/typen";
import { Fehler, Laedt } from "@/components/zustaende";

/**
 * Der Briefkopf. Steht unter jedem Angebot, das das Haus verlässt.
 *
 * Die Felder stehen als Liste und nicht als einzeln getipptes Formular:
 * Eine neue Pflichtangabe soll an einer Stelle dazukommen, nicht an drei.
 */
const FELDER: { schluessel: keyof Absender; text: string; hinweis?: string; spalte?: 1 | 2 }[] = [
  { schluessel: "absender_name", text: "Firmenname" },
  { schluessel: "absender_strasse", text: "Straße und Hausnummer" },
  { schluessel: "absender_plz", text: "PLZ", spalte: 1 },
  { schluessel: "absender_ort", text: "Ort", spalte: 2 },
  { schluessel: "absender_telefon", text: "Telefon", spalte: 1 },
  { schluessel: "absender_email", text: "E-Mail", spalte: 2 },
  { schluessel: "absender_website", text: "Website" },
  { schluessel: "vertretung", text: "Vertreten durch", hinweis: "Erscheint im Fuß des Angebots." },
  { schluessel: "registergericht", text: "Registergericht und -nummer" },
  { schluessel: "ust_id", text: "Umsatzsteuer-Identifikationsnummer" },
  { schluessel: "bank_name", text: "Bank", spalte: 1 },
  { schluessel: "bank_iban", text: "IBAN", spalte: 2 },
];

export function Absenderblock() {
  const client = useQueryClient();
  const [werte, setWerte] = useState<Partial<Absender>>({});
  const [geaendert, setGeaendert] = useState(false);

  const abfrage = useQuery({
    queryKey: ["einstellungen"],
    queryFn: () => api.get<OrgSettings>("/api/settings"),
  });

  useEffect(() => {
    if (abfrage.data && !geaendert) {
      const { llm_base_url, llm_model, llm_api_key_set, llm_ready, ...rest } = abfrage.data;
      void llm_base_url;
      void llm_model;
      void llm_api_key_set;
      void llm_ready;
      setWerte(rest);
    }
  }, [abfrage.data, geaendert]);

  const speichern = useMutation({
    mutationFn: () => api.put<OrgSettings>("/api/settings", werte),
    onSuccess: () => {
      setGeaendert(false);
      client.invalidateQueries({ queryKey: ["einstellungen"] });
    },
  });

  if (abfrage.isPending) return <Laedt />;

  const fehlend = FELDER.filter(
    (f) => ["absender_name", "absender_strasse", "absender_ort", "ust_id"].includes(f.schluessel) &&
      !werte[f.schluessel],
  );

  function setze(schluessel: keyof Absender, wert: string) {
    setGeaendert(true);
    setWerte((alt) => ({ ...alt, [schluessel]: wert }));
  }

  return (
    <section className="block">
      <div className="block-kopf">
        <h2>Absender für Angebote</h2>
        {fehlend.length > 0 && (
          <span className="stufe" data-art="lost">
            {fehlend.length} Angaben fehlen
          </span>
        )}
      </div>
      <div className="block-inhalt">
        <p style={{ fontSize: "0.875rem", color: "var(--am-text-sekundaer)", marginBottom: "var(--am-raum-6)" }}>
          Diese Angaben stehen auf jedem Angebot, das das Haus verlässt. Ohne sie ist die
          Druckfassung kein versandfähiges Dokument.
        </p>

        <form
          onSubmit={(e) => {
            e.preventDefault();
            speichern.mutate();
          }}
        >
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))",
              gap: "0 var(--am-raum-4)",
            }}
          >
            {FELDER.map((f) => (
              <div
                className="feld"
                key={f.schluessel}
                style={f.spalte ? undefined : { gridColumn: "1 / -1" }}
              >
                <label htmlFor={f.schluessel}>{f.text}</label>
                <input
                  id={f.schluessel}
                  value={(werte[f.schluessel] as string) ?? ""}
                  onChange={(e) => setze(f.schluessel, e.target.value)}
                />
                {f.hinweis && <p className="feld-hinweis">{f.hinweis}</p>}
              </div>
            ))}
          </div>

          <div className="feld">
            <label htmlFor="bindefrist_tage">Bindefrist in Tagen</label>
            <input
              id="bindefrist_tage"
              type="number"
              min="1"
              max="365"
              value={werte.bindefrist_tage ?? 30}
              onChange={(e) => {
                setGeaendert(true);
                setWerte((alt) => ({ ...alt, bindefrist_tage: Number(e.target.value) }));
              }}
            />
            <p className="feld-hinweis">
              Füllt das Datum bei neuen Angeboten vor. Verbindlich ist, was im Angebot steht.
            </p>
          </div>

          <div className="feld">
            <label htmlFor="standard_bedingungen">Bedingungen</label>
            <textarea
              id="standard_bedingungen"
              rows={4}
              value={werte.standard_bedingungen ?? ""}
              onChange={(e) => setze("standard_bedingungen", e.target.value)}
              placeholder="Zahlungsziel, Lieferzeit, Gerichtsstand …"
            />
            <p className="feld-hinweis">
              Steht unter jedem Angebot. Es gibt bewusst keine Vorgabe — das wäre eine
              Rechtsauskunft.
            </p>
          </div>

          {speichern.isError && <Fehler text={(speichern.error as Error).message} />}

          <div className="btn-reihe">
            <button
              type="submit"
              className="btn btn-primaer"
              disabled={speichern.isPending || !geaendert}
            >
              {speichern.isPending ? "Speichert …" : "Speichern"}
            </button>
            {speichern.isSuccess && !geaendert && (
              <span style={{ fontSize: "0.8125rem", color: "var(--am-erfolg)" }}>Gespeichert.</span>
            )}
          </div>
        </form>
      </div>
    </section>
  );
}
