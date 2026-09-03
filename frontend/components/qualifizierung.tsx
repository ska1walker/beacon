"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, Sparkles } from "lucide-react";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import type {
  KIStatus,
  Qualifizierung,
  QualifizierungAntwort,
  Qualifizierungsvorschlag,
} from "@/lib/typen";
import { Fehler, Laedt } from "@/components/zustaende";

interface Schemafeld {
  feld: keyof Qualifizierung;
  gewicht: number;
  frage: string;
  art: "text" | "ja_nein";
}

/** Kurzbeschriftung über dem Feld. Die Frage steht darunter. */
const BESCHRIFTUNG: Record<string, string> = {
  bedarf: "Bedarf",
  entscheider: "Entscheider",
  ausloeser: "Auslöser",
  zeitrahmen: "Zeitrahmen",
  budget_geklaert: "Budget ist geklärt",
  standort_geklaert: "Standort geklärt — Platz, Strom, Netz",
};

export function Qualifizierungsblock({ dealId }: { dealId: string }) {
  const client = useQueryClient();
  const [werte, setWerte] = useState<Qualifizierung | null>(null);
  const [geaendert, setGeaendert] = useState(false);
  const [belege, setBelege] = useState<Record<string, string>>({});

  const abfrage = useQuery({
    queryKey: ["qualifizierung", dealId],
    queryFn: () => api.get<QualifizierungAntwort>(`/api/deals/${dealId}/qualifizierung`),
  });

  const schema = useQuery({
    queryKey: ["qualifizierung-schema"],
    queryFn: () => api.get<Schemafeld[]>("/api/qualifizierung/schema"),
    // Ändert sich nur mit einer neuen Fassung der Anwendung.
    staleTime: Infinity,
  });

  const kiStatus = useQuery({
    queryKey: ["ki-status"],
    queryFn: () => api.get<KIStatus>("/api/ki/status"),
    staleTime: 5 * 60_000,
  });

  useEffect(() => {
    if (abfrage.data && !geaendert) {
      const { punkte, qualifikation_am, offen, ...rest } = abfrage.data;
      void punkte;
      void qualifikation_am;
      void offen;
      setWerte(rest);
    }
  }, [abfrage.data, geaendert]);

  const ziehen = useMutation({
    mutationFn: () =>
      api.post<Qualifizierungsvorschlag>(`/api/ki/deals/${dealId}/qualifizieren`),
    onSuccess: (v) => {
      const { punkte, offen, belege: b, modell, ...rest } = v;
      void punkte;
      void offen;
      void modell;
      // Der Vorschlag füllt die Maske. Gespeichert wird er nicht — das
      // tut ein Mensch, nachdem er ihn gelesen hat.
      setWerte(rest);
      setBelege(b);
      setGeaendert(true);
      client.invalidateQueries({ queryKey: ["aktivitaeten"] });
    },
  });

  const speichern = useMutation({
    mutationFn: () => api.put<QualifizierungAntwort>(`/api/deals/${dealId}/qualifizierung`, werte),
    onSuccess: () => {
      setGeaendert(false);
      setBelege({});
      client.invalidateQueries({ queryKey: ["qualifizierung", dealId] });
    },
  });

  if (abfrage.isPending || schema.isPending || !werte) return <Laedt />;

  const felder = schema.data!;
  const punkte = geaendert ? schaetzePunkte(werte, felder) : abfrage.data!.punkte;
  const offen = geaendert ? [] : abfrage.data!.offen;
  const bereit = kiStatus.data?.ready ?? false;

  function setze(schluessel: keyof Qualifizierung, wert: string | boolean) {
    setGeaendert(true);
    setWerte((alt) => (alt ? { ...alt, [schluessel]: wert } : alt));
  }

  return (
    <section className="block">
      <div className="block-kopf">
        <h2>Qualifizierung</h2>
        <span className="stufe" data-art={punkte >= 70 ? "won" : punkte >= 40 ? "open" : "lost"}>
          {punkte} von 100
        </span>
      </div>

      <div className="block-inhalt">
        <div className="btn-reihe" style={{ marginBottom: "var(--am-raum-4)" }}>
          <button
            type="button"
            className="btn btn-sekundaer btn-klein"
            onClick={() => ziehen.mutate()}
            disabled={!bereit || ziehen.isPending}
            title={bereit ? undefined : kiStatus.data?.hint}
          >
            <Sparkles size={14} aria-hidden="true" />
            {ziehen.isPending ? "Liest den Verlauf …" : "Aus dem Verlauf ziehen"}
          </button>
        </div>

        {ziehen.isError && <Fehler text={(ziehen.error as Error).message} />}
        {ziehen.isSuccess && geaendert && (
          <div className="hinweis" style={{ marginBottom: "var(--am-raum-4)" }}>
            <span>
              Vorschlag eingetragen, noch nicht gespeichert. Prüfen Sie die Zitate unter den
              Feldern — sie stammen aus Ihrem Verlauf.
            </span>
          </div>
        )}

        {offen.length > 0 && (
          <div className="hinweis" data-art="achtung" style={{ marginBottom: "var(--am-raum-4)" }}>
            <span>
              <strong>Noch zu klären:</strong>
              <ul style={{ margin: "var(--am-raum-1) 0 0 var(--am-raum-4)" }}>
                {offen.map((f) => (
                  <li key={f}>{f}</li>
                ))}
              </ul>
            </span>
          </div>
        )}

        <form
          onSubmit={(e) => {
            e.preventDefault();
            speichern.mutate();
          }}
        >
          {felder
            .filter((f) => f.art === "text")
            .map((f) => (
              <div className="feld" key={f.feld}>
                <label htmlFor={`q-${f.feld}`}>
                  {BESCHRIFTUNG[f.feld] ?? f.feld}{" "}
                  <span className="optional">{f.gewicht} Punkte</span>
                </label>
                <textarea
                  id={`q-${f.feld}`}
                  rows={2}
                  value={(werte[f.feld] as string) ?? ""}
                  onChange={(e) => setze(f.feld, e.target.value)}
                  placeholder={f.frage}
                />
                {belege[f.feld] && (
                  <p className="feld-hinweis" style={{ fontStyle: "italic" }}>
                    Beleg: „{belege[f.feld]}“
                  </p>
                )}
              </div>
            ))}

          {felder
            .filter((f) => f.art === "ja_nein")
            .map((f) => (
              <label
                key={f.feld}
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: "var(--am-raum-2)",
                  marginBottom: "var(--am-raum-3)",
                  fontSize: "0.875rem",
                }}
                title={f.frage}
              >
                <input
                  type="checkbox"
                  checked={Boolean(werte[f.feld])}
                  onChange={(e) => setze(f.feld, e.target.checked)}
                />
                {BESCHRIFTUNG[f.feld] ?? f.frage}
              </label>
            ))}

          {speichern.isError && <Fehler text={(speichern.error as Error).message} />}

          <div className="btn-reihe">
            <button
              type="submit"
              className="btn btn-primaer btn-klein"
              disabled={!geaendert || speichern.isPending}
            >
              {speichern.isPending ? "Speichert …" : "Speichern"}
            </button>
            {!geaendert && abfrage.data!.qualifikation_am && (
              <span
                style={{
                  fontSize: "0.75rem",
                  color: "var(--am-text-gedaempft)",
                  display: "inline-flex",
                  alignItems: "center",
                  gap: "var(--am-raum-1)",
                }}
              >
                <Check size={12} aria-hidden="true" />
                gespeichert
              </span>
            )}
          </div>
        </form>
      </div>
    </section>
  );
}

/**
 * Vorschau der Punktzahl während des Tippens.
 *
 * Die Gewichte kommen aus dem Backend (/api/qualifizierung/schema) und
 * stehen hier bewusst nicht noch einmal: Zwei Listen, die dasselbe
 * bedeuten sollen, laufen auseinander — und dann zeigt die Maske 70 an,
 * während die Prognose mit 55 rechnet.
 */
function schaetzePunkte(q: Qualifizierung, felder: Schemafeld[]): number {
  const gefuellt = (w: unknown) =>
    typeof w === "boolean" ? w : Boolean(w && String(w).trim());
  return felder.reduce((summe, f) => summe + (gefuellt(q[f.feld]) ? f.gewicht : 0), 0);
}
