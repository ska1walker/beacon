"use client";

import { useMutation, useQuery } from "@tanstack/react-query";
import { Sparkles } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { api } from "@/lib/api";
import { euro } from "@/lib/format";
import type {
  Angebotsvorschlag,
  KIStatus,
  OrgSettings,
  Product,
  Quote,
  QuoteItemIn,
} from "@/lib/typen";
import { Fehler } from "@/components/zustaende";

/**
 * Legt ein Angebot zu einem Lead an — leer oder aus einem
 * KI-Vorschlag. Der Vorschlag füllt nur das Formular; abgeschickt wird
 * er erst, wenn ein Mensch ihn gesehen hat.
 */
export function AngebotAnlegen({
  dealId,
  beiSchliessen,
}: {
  dealId: string;
  beiSchliessen: () => void;
}) {
  const router = useRouter();
  const [positionen, setPositionen] = useState<QuoteItemIn[]>([]);
  const [anschreiben, setAnschreiben] = useState("");
  const [offenePunkte, setOffenePunkte] = useState<string[]>([]);
  const [frist, setFrist] = useState("");

  const produkte = useQuery({
    queryKey: ["produkte"],
    queryFn: () => api.get<Product[]>("/api/products"),
  });

  const einstellungen = useQuery({
    queryKey: ["einstellungen"],
    queryFn: () => api.get<OrgSettings>("/api/settings"),
  });

  const kiStatus = useQuery({
    queryKey: ["ki-status"],
    queryFn: () => api.get<KIStatus>("/api/ki/status"),
    staleTime: 5 * 60_000,
  });

  const vorschlag = useMutation({
    mutationFn: () => api.post<Angebotsvorschlag>(`/api/ki/deals/${dealId}/angebotsvorschlag`),
    onSuccess: (v) => {
      setAnschreiben(v.anschreiben);
      setOffenePunkte(v.offene_punkte);
      setPositionen(
        v.positionen.map((p, i) => ({
          title: p.titel,
          description: p.beschreibung,
          quantity: p.menge,
          unit_price_cents: p.einzelpreis_cents,
          product_id: produkte.data?.find((x) => x.key === p.produkt_key)?.id ?? null,
          position: i,
        })),
      );
    },
  });

  const anlegen = useMutation({
    mutationFn: () =>
      api.post<Quote>("/api/quotes", {
        deal_id: dealId,
        intro_text: anschreiben || null,
        terms_text: einstellungen.data?.standard_bedingungen ?? null,
        valid_until: frist || vorgabefrist(einstellungen.data?.bindefrist_tage),
        items: positionen,
      }),
    onSuccess: (q) => router.push(`/angebote/${q.id}`),
  });

  const bereit = kiStatus.data?.ready ?? false;

  return (
    <div className="dialog-schicht" role="dialog" aria-modal="true" aria-label="Angebot anlegen">
      <div className="karte" style={{ maxWidth: "620px", width: "100%" }}>
        <h2 style={{ marginBottom: "var(--am-raum-4)", fontSize: "1.125rem" }}>Angebot anlegen</h2>

        <div className="btn-reihe" style={{ marginBottom: "var(--am-raum-4)" }}>
          <button
            type="button"
            className="btn btn-sekundaer btn-klein"
            onClick={() => vorschlag.mutate()}
            disabled={!bereit || vorschlag.isPending}
            title={bereit ? undefined : kiStatus.data?.hint}
          >
            <Sparkles size={14} aria-hidden="true" />
            {vorschlag.isPending ? "Denkt nach …" : "Vorschlag erzeugen"}
          </button>
          <button
            type="button"
            className="btn btn-still btn-klein"
            onClick={() =>
              setPositionen((alt) => [
                ...alt,
                { title: "", quantity: 1, unit_price_cents: 0, position: alt.length },
              ])
            }
          >
            Leere Position
          </button>
        </div>

        {!bereit && kiStatus.data?.hint && (
          <p style={{ fontSize: "0.75rem", color: "var(--am-text-gedaempft)" }}>
            {kiStatus.data.hint}
          </p>
        )}
        {vorschlag.isError && <Fehler text={(vorschlag.error as Error).message} />}

        {offenePunkte.length > 0 && (
          <div className="hinweis" data-art="achtung" style={{ marginBottom: "var(--am-raum-4)" }}>
            <span>
              <strong>Offen geblieben:</strong>
              <ul style={{ margin: "var(--am-raum-1) 0 0 var(--am-raum-4)" }}>
                {offenePunkte.map((p) => (
                  <li key={p}>{p}</li>
                ))}
              </ul>
            </span>
          </div>
        )}

        {positionen.length > 0 && (
          <table className="tabelle" style={{ marginBottom: "var(--am-raum-4)" }}>
            <thead>
              <tr>
                <th>Position</th>
                <th style={{ textAlign: "right", width: "4rem" }}>Menge</th>
                <th style={{ textAlign: "right", width: "7rem" }}>Einzelpreis</th>
              </tr>
            </thead>
            <tbody>
              {positionen.map((p, i) => (
                <tr key={i} style={{ cursor: "default" }}>
                  <td>
                    <input
                      className="input"
                      value={p.title}
                      placeholder="Bezeichnung"
                      aria-label={`Bezeichnung Position ${i + 1}`}
                      onChange={(e) =>
                        setPositionen((alt) =>
                          alt.map((z, j) => (j === i ? { ...z, title: e.target.value } : z)),
                        )
                      }
                    />
                  </td>
                  <td className="zahl">
                    <input
                      className="input"
                      type="number"
                      min="0.5"
                      step="0.5"
                      value={p.quantity}
                      aria-label={`Menge Position ${i + 1}`}
                      onChange={(e) =>
                        setPositionen((alt) =>
                          alt.map((z, j) =>
                            j === i ? { ...z, quantity: Number(e.target.value) } : z,
                          ),
                        )
                      }
                    />
                  </td>
                  <td className="zahl">
                    <input
                      className="input"
                      type="number"
                      min="0"
                      step="100"
                      value={p.unit_price_cents / 100}
                      aria-label={`Einzelpreis Position ${i + 1}`}
                      onChange={(e) =>
                        setPositionen((alt) =>
                          alt.map((z, j) =>
                            j === i
                              ? { ...z, unit_price_cents: Math.round(Number(e.target.value) * 100) }
                              : z,
                          ),
                        )
                      }
                    />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}

        {positionen.length > 0 && (
          <p style={{ textAlign: "right", fontFamily: "var(--am-schrift-mono)" }}>
            Netto {euro(positionen.reduce((s, p) => s + p.quantity * p.unit_price_cents, 0))}
          </p>
        )}

        <div className="feld">
          <label htmlFor="anschreiben">
            Anschreiben <span className="optional">optional</span>
          </label>
          <textarea
            id="anschreiben"
            rows={4}
            value={anschreiben}
            onChange={(e) => setAnschreiben(e.target.value)}
            placeholder="Steht oben im Angebot."
          />
        </div>

        <div className="feld">
          <label htmlFor="frist">Bindefrist</label>
          <input
            id="frist"
            type="date"
            value={frist || (vorgabefrist(einstellungen.data?.bindefrist_tage) ?? "")}
            onChange={(e) => setFrist(e.target.value)}
          />
        </div>

        {anlegen.isError && <Fehler text={(anlegen.error as Error).message} />}

        <div className="btn-reihe">
          <button
            type="button"
            className="btn btn-primaer"
            onClick={() => anlegen.mutate()}
            disabled={anlegen.isPending}
          >
            {anlegen.isPending ? "Legt an …" : "Als Entwurf anlegen"}
          </button>
          <button type="button" className="btn btn-still" onClick={beiSchliessen}>
            Abbrechen
          </button>
        </div>
      </div>
    </div>
  );
}

/** Vorgabefrist ab heute, im Format, das ein date-Feld versteht. */
function vorgabefrist(tage: number | null | undefined): string | null {
  if (!tage) return null;
  const d = new Date();
  d.setDate(d.getDate() + tage);
  return d.toISOString().slice(0, 10);
}
