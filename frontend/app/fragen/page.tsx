"use client";

import { useMutation } from "@tanstack/react-query";
import { Search, Sparkles } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { api } from "@/lib/api";
import type { Frageantwort } from "@/lib/typen";
import { Seitenkopf } from "@/components/seitenkopf";
import { Fehler } from "@/components/zustaende";

const BEISPIELE = [
  "Welche Geschäfte hängen an einer Compliance-Auflage?",
  "Wer entscheidet bei Meyer Präzisionstechnik?",
  "Was war der letzte Stand bei Nordlicht?",
  "Wo haben wir wegen des Preises verloren?",
];

/** Aus der Art einer Fundstelle wird der Weg dorthin. */
function pfad(art: string, id: string | null): string | null {
  if (!id) return null;
  if (art === "Firma") return `/firmen/${id}`;
  if (art === "Kontakt") return `/kontakte/${id}`;
  if (art === "Geschäft") return `/deals/${id}`;
  return null;
}

export default function FragenSeite() {
  const [frage, setFrage] = useState("");

  const stellen = useMutation({
    mutationFn: (f: string) => api.post<Frageantwort>("/api/fragen", { frage: f }),
  });

  return (
    <>
      <Seitenkopf titel="Fragen" zahl="Auskunft aus dem eigenen Bestand" />

      <div className="werkzeugleiste">
        <form
          style={{ display: "flex", gap: "var(--am-raum-2)", flex: "1 1 420px" }}
          onSubmit={(e) => {
            e.preventDefault();
            if (frage.trim().length >= 3) stellen.mutate(frage.trim());
          }}
        >
          <div className="suchfeld" style={{ maxWidth: "none", flex: 1 }}>
            <Search size={16} aria-hidden="true" />
            <input
              value={frage}
              onChange={(e) => setFrage(e.target.value)}
              placeholder="Was möchten Sie wissen?"
              aria-label="Frage"
            />
          </div>
          <button
            type="submit"
            className="btn btn-primaer"
            disabled={stellen.isPending || frage.trim().length < 3}
          >
            <Sparkles size={14} aria-hidden="true" />
            {stellen.isPending ? "Sucht …" : "Fragen"}
          </button>
        </form>
      </div>

      <div className="datensatz" style={{ gridTemplateColumns: "minmax(0, 1fr)" }}>
        {!stellen.data && !stellen.isPending && (
          <section className="block">
            <div className="block-kopf">
              <h2>Zum Beispiel</h2>
            </div>
            <div className="block-inhalt">
              <p
                style={{
                  fontSize: "0.875rem",
                  color: "var(--am-text-sekundaer)",
                  marginBottom: "var(--am-raum-4)",
                }}
              >
                Gesucht wird in Firmen, Kontakten, Geschäften und im gesamten Verlauf.
                Geantwortet wird ausschließlich aus dem, was gefunden wurde — findet sich
                nichts, wird kein Modell gefragt.
              </p>
              <div className="btn-reihe">
                {BEISPIELE.map((b) => (
                  <button
                    key={b}
                    type="button"
                    className="btn btn-sekundaer btn-klein"
                    onClick={() => {
                      setFrage(b);
                      stellen.mutate(b);
                    }}
                  >
                    {b}
                  </button>
                ))}
              </div>
            </div>
          </section>
        )}

        {stellen.isError && (
          <div style={{ padding: "0 var(--am-raum-8)" }}>
            <Fehler text={(stellen.error as Error).message} />
          </div>
        )}

        {stellen.data && (
          <>
            {stellen.data.antwort && (
              <section className="block">
                <div className="block-kopf">
                  <h2>Antwort</h2>
                  <span style={{ fontSize: "0.75rem", color: "var(--am-text-gedaempft)" }}>
                    {stellen.data.modell}
                  </span>
                </div>
                <div className="block-inhalt">
                  <div className="ki-block">
                    <div className="ki-block-kopf">
                      <Sparkles size={11} aria-hidden="true" /> Aus dem Bestand beantwortet
                    </div>
                    <p className="ki-block-text">{stellen.data.antwort}</p>
                  </div>
                </div>
              </section>
            )}

            {stellen.data.hinweis && (
              <div style={{ padding: "0 var(--am-raum-8)" }}>
                <div className="hinweis" data-art={stellen.data.fundstellen.length ? undefined : "achtung"}>
                  <span>{stellen.data.hinweis}</span>
                </div>
              </div>
            )}

            {stellen.data.fundstellen.length > 0 && (
              <section className="block">
                <div className="block-kopf">
                  <h2>Fundstellen</h2>
                  <span className="board-spalte-anzahl">{stellen.data.fundstellen.length}</span>
                </div>
                <div className="block-inhalt">
                  <ol className="fundstellen">
                    {stellen.data.fundstellen.map((f, i) => {
                      const ziel = pfad(f.art, f.id);
                      return (
                        <li key={`${f.art}-${f.id}-${i}`}>
                          <div className="fundstelle-kopf">
                            <span className="fundstelle-nummer">[{i + 1}]</span>
                            <span className="zeitleiste-art">{f.art}</span>
                            {ziel ? (
                              <Link href={ziel} className="fundstelle-titel">
                                {f.titel}
                              </Link>
                            ) : (
                              <span className="fundstelle-titel">{f.titel}</span>
                            )}
                          </div>
                          <p className="zeitleiste-text">{f.text}</p>
                        </li>
                      );
                    })}
                  </ol>
                </div>
              </section>
            )}
          </>
        )}
      </div>
    </>
  );
}
