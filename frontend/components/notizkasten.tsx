"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Sparkles } from "lucide-react";
import { useState } from "react";
import { api } from "@/lib/api";
import { AKTIVITAET_TEXT, datum } from "@/lib/format";
import type {
  Aufgabenvorschlag,
  KIStatus,
  Notizvorschlag,
  Uebernahmebilanz,
} from "@/lib/typen";
import { Fehler } from "@/components/zustaende";

type Bezug = { company_id?: string; contact_id?: string; deal_id?: string; ticket_id?: string };

/**
 * Ein Kasten für die Gesprächsnotiz.
 *
 * Der Vorgang, der im Vertrieb am meisten Zeit frisst, ist nicht das
 * Gespräch — es ist das Nacharbeiten: Notiz ablegen, Aufgaben anlegen,
 * nächsten Schritt setzen, Qualifizierung nachziehen. Vier Masken für ein
 * Telefonat von drei Minuten.
 *
 * Hier gibt es einen Kasten. Was daraus wird, schlägt das Modell vor; was
 * davon bleibt, entscheidet ein Mensch — jede Zeile ist abwählbar.
 */
export function Notizkasten({ bezug }: { bezug: Bezug }) {
  const client = useQueryClient();
  const [text, setText] = useState("");
  const [vorschlag, setVorschlag] = useState<Notizvorschlag | null>(null);
  const [aufgaben, setAufgaben] = useState<(Aufgabenvorschlag & { an: boolean })[]>([]);
  const [schrittAn, setSchrittAn] = useState(true);
  const [qualAn, setQualAn] = useState(true);

  const kiStatus = useQuery({
    queryKey: ["ki-status"],
    queryFn: () => api.get<KIStatus>("/api/ki/status"),
    staleTime: 5 * 60_000,
  });

  const verarbeiten = useMutation({
    mutationFn: () => api.post<Notizvorschlag>("/api/notiz/verarbeiten", { ...bezug, text }),
    onSuccess: (v) => {
      setVorschlag(v);
      setAufgaben(v.aufgaben.map((a) => ({ ...a, an: true })));
      setSchrittAn(Boolean(v.naechster_schritt));
      setQualAn(Boolean(v.qualifikation_punkte));
    },
  });

  const uebernehmen = useMutation({
    mutationFn: () =>
      api.post<Uebernahmebilanz>("/api/notiz/uebernehmen", {
        ...bezug,
        art: vorschlag!.art,
        betreff: vorschlag!.betreff,
        text: vorschlag!.zusammenfassung,
        aufgaben: aufgaben.filter((a) => a.an).map(({ an, ...rest }) => (void an, rest)),
        naechster_schritt: schrittAn ? vorschlag!.naechster_schritt : null,
        qualifizierung: qualAn ? vorschlag!.qualifizierung : null,
      }),
    onSuccess: () => {
      setText("");
      setVorschlag(null);
      setAufgaben([]);
      client.invalidateQueries();
    },
  });

  const bereit = kiStatus.data?.ready ?? false;

  return (
    <section className="block">
      <div className="block-kopf">
        <h2>Notiz verarbeiten</h2>
      </div>
      <div className="block-inhalt">
        {!vorschlag && (
          <>
            <div className="notiz-feld">
              <textarea
                rows={5}
                value={text}
                onChange={(e) => setText(e.target.value)}
                placeholder="Tippen Sie das Gespräch hin, wie es war. Was daraus wird — Notiz, Aufgaben, nächster Schritt — schlägt die KI vor."
                aria-label="Gesprächsnotiz"
              />
            </div>
            <div className="btn-reihe" style={{ marginTop: "var(--am-raum-2)" }}>
              <button
                type="button"
                className="btn btn-primaer btn-klein"
                onClick={() => verarbeiten.mutate()}
                disabled={!bereit || text.trim().length < 10 || verarbeiten.isPending}
                title={bereit ? undefined : kiStatus.data?.hint}
              >
                <Sparkles size={14} aria-hidden="true" />
                {verarbeiten.isPending ? "Liest …" : "Verarbeiten"}
              </button>
              {!bereit && kiStatus.data?.hint && (
                <span style={{ fontSize: "0.75rem", color: "var(--am-text-gedaempft)" }}>
                  {kiStatus.data.hint}
                </span>
              )}
            </div>
            {verarbeiten.isError && <Fehler text={(verarbeiten.error as Error).message} />}
          </>
        )}

        {vorschlag && (
          <>
            <div className="hinweis" style={{ marginBottom: "var(--am-raum-4)" }}>
              <span>
                Vorschlag. Nichts davon ist gespeichert — wählen Sie ab, was nicht stimmt.
              </span>
            </div>

            <dl>
              <div className="eigenschaft">
                <dt>Art</dt>
                <dd>{AKTIVITAET_TEXT[vorschlag.art] ?? vorschlag.art}</dd>
              </div>
              <div className="eigenschaft">
                <dt>Betreff</dt>
                <dd>{vorschlag.betreff}</dd>
              </div>
            </dl>

            <div className="feld" style={{ marginTop: "var(--am-raum-4)" }}>
              <label htmlFor="zusammenfassung">Was festgehalten wird</label>
              <textarea
                id="zusammenfassung"
                rows={4}
                value={vorschlag.zusammenfassung}
                onChange={(e) =>
                  setVorschlag({ ...vorschlag, zusammenfassung: e.target.value })
                }
              />
            </div>

            {aufgaben.length > 0 && (
              <fieldset style={{ border: "none", padding: 0, margin: "0 0 var(--am-raum-4)" }}>
                <legend
                  style={{
                    fontSize: "0.75rem",
                    fontWeight: 600,
                    textTransform: "uppercase",
                    letterSpacing: "0.04em",
                    color: "var(--am-text-gedaempft)",
                    marginBottom: "var(--am-raum-2)",
                  }}
                >
                  Aufgaben
                </legend>
                {aufgaben.map((a, i) => (
                  <label
                    key={`${a.titel}-${i}`}
                    style={{
                      display: "flex",
                      alignItems: "center",
                      gap: "var(--am-raum-2)",
                      marginBottom: "var(--am-raum-2)",
                      fontSize: "0.875rem",
                    }}
                  >
                    <input
                      type="checkbox"
                      checked={a.an}
                      onChange={(e) =>
                        setAufgaben((alt) =>
                          alt.map((z, j) => (j === i ? { ...z, an: e.target.checked } : z)),
                        )
                      }
                    />
                    <span>{a.titel}</span>
                    <span style={{ color: "var(--am-text-gedaempft)", fontSize: "0.75rem" }}>
                      {a.faellig_am ? datum(a.faellig_am) : "ohne Frist"}
                    </span>
                  </label>
                ))}
              </fieldset>
            )}

            {vorschlag.naechster_schritt && (
              <label
                style={{
                  display: "flex",
                  alignItems: "flex-start",
                  gap: "var(--am-raum-2)",
                  marginBottom: "var(--am-raum-3)",
                  fontSize: "0.875rem",
                }}
              >
                <input
                  type="checkbox"
                  checked={schrittAn}
                  onChange={(e) => setSchrittAn(e.target.checked)}
                />
                <span>
                  <strong>Nächster Schritt:</strong> {vorschlag.naechster_schritt}
                </span>
              </label>
            )}

            {vorschlag.qualifikation_punkte ? (
              <label
                style={{
                  display: "flex",
                  alignItems: "flex-start",
                  gap: "var(--am-raum-2)",
                  marginBottom: "var(--am-raum-3)",
                  fontSize: "0.875rem",
                }}
              >
                <input
                  type="checkbox"
                  checked={qualAn}
                  onChange={(e) => setQualAn(e.target.checked)}
                />
                <span>
                  <strong>Qualifizierung ergänzen</strong> — {vorschlag.qualifikation_punkte}{" "}
                  Punkte aus dieser Notiz. Bestehende Angaben bleiben stehen.
                </span>
              </label>
            ) : null}

            {vorschlag.unbekannte_personen.length > 0 && (
              <div className="hinweis" data-art="achtung">
                <span>
                  Im Text genannt, im CRM nicht gefunden:{" "}
                  {vorschlag.unbekannte_personen.join(", ")}. Sie werden nicht angelegt — das
                  wäre geraten.
                </span>
              </div>
            )}

            {uebernehmen.isError && <Fehler text={(uebernehmen.error as Error).message} />}

            <div className="btn-reihe" style={{ marginTop: "var(--am-raum-4)" }}>
              <button
                type="button"
                className="btn btn-primaer btn-klein"
                onClick={() => uebernehmen.mutate()}
                disabled={uebernehmen.isPending}
              >
                {uebernehmen.isPending ? "Übernimmt …" : "Übernehmen"}
              </button>
              <button
                type="button"
                className="btn btn-still btn-klein"
                onClick={() => setVorschlag(null)}
              >
                Zurück zum Text
              </button>
            </div>
          </>
        )}
      </div>
    </section>
  );
}
