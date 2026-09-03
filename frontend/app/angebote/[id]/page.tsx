"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { Plus, Printer, Trash2 } from "lucide-react";
import { use, useEffect, useState } from "react";
import { api } from "@/lib/api";
import { ANGEBOT_STATUS_ART, ANGEBOT_STATUS_TEXT, datum, datumZeit, euroGenau } from "@/lib/format";
import type { Product, Quote, QuoteItemIn, QuoteStatus } from "@/lib/typen";
import { Seitenkopf } from "@/components/seitenkopf";
import { Fehler, Laedt } from "@/components/zustaende";

/** Eine Zeile im Bearbeitungszustand. */
type Zeile = QuoteItemIn & { schluessel: string };

function zeilenbetrag(z: Zeile): number {
  // Dieselbe Formel wie im Backend: erst multiplizieren, dann runden.
  // Sie steht hier nur zur Anzeige — verbindlich ist, was die API rechnet.
  return Math.round(z.quantity * z.unit_price_cents * (1 - (z.discount_percent ?? 0) / 100));
}

export default function AngebotSeite({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const client = useQueryClient();

  const angebot = useQuery({
    queryKey: ["angebot", id],
    queryFn: () => api.get<Quote>(`/api/quotes/${id}`),
  });

  const produkte = useQuery({
    queryKey: ["produkte"],
    queryFn: () => api.get<Product[]>("/api/products"),
  });

  const [zeilen, setZeilen] = useState<Zeile[]>([]);
  const [geaendert, setGeaendert] = useState(false);

  useEffect(() => {
    if (angebot.data && !geaendert) {
      setZeilen(
        angebot.data.items.map((i) => ({
          schluessel: i.id,
          product_id: i.product_id,
          title: i.title,
          description: i.description,
          quantity: i.quantity,
          unit_price_cents: i.unit_price_cents,
          discount_percent: i.discount_percent,
        })),
      );
    }
  }, [angebot.data, geaendert]);

  const speichern = useMutation({
    mutationFn: () =>
      api.put<Quote>(
        `/api/quotes/${id}/positionen`,
        zeilen.map((z, i) => ({ ...z, position: i, schluessel: undefined })),
      ),
    onSuccess: () => {
      setGeaendert(false);
      client.invalidateQueries({ queryKey: ["angebot", id] });
    },
  });

  const statusSetzen = useMutation({
    mutationFn: (status: QuoteStatus) => api.post<Quote>(`/api/quotes/${id}/status`, { status }),
    onSuccess: () => {
      client.invalidateQueries({ queryKey: ["angebot", id] });
      client.invalidateQueries({ queryKey: ["angebote"] });
      client.invalidateQueries({ queryKey: ["aktivitaeten"] });
    },
  });

  if (angebot.isPending) return <Laedt />;
  if (angebot.isError) return <Fehler text={(angebot.error as Error).message} />;

  const q = angebot.data!;
  const entwurf = q.status === "draft";

  // Vorschau der Summen aus den bearbeiteten Zeilen. Verbindlich bleibt,
  // was die API nach dem Speichern zurückgibt.
  const netto = zeilen.reduce((s, z) => s + zeilenbetrag(z), 0);
  const nachlass = Math.min(q.discount_cents, netto);
  const steuer = Math.round((netto - nachlass) * q.tax_rate);

  function aendern(index: number, teil: Partial<Zeile>) {
    setGeaendert(true);
    setZeilen((alt) => alt.map((z, i) => (i === index ? { ...z, ...teil } : z)));
  }

  return (
    <>
      <Seitenkopf
        titel={`${q.number} — ${q.title}`}
        zahl={[q.company_name, q.deal_name].filter(Boolean).join(" · ")}
        pfad={{ text: "← Angebote", href: "/angebote" }}
      >
        <span className="stufe" data-art={ANGEBOT_STATUS_ART[q.status]}>
          {ANGEBOT_STATUS_TEXT[q.status]}
        </span>
        <Link className="btn btn-sekundaer btn-klein" href={`/angebote/${id}/druck`}>
          <Printer size={14} aria-hidden="true" />
          Druckfassung
        </Link>
      </Seitenkopf>

      <div className="datensatz" style={{ gridTemplateColumns: "minmax(0, 1fr) 260px" }}>
        <section className="block">
          <div className="block-kopf">
            <h2>Positionen</h2>
            {entwurf && (
              <button
                type="button"
                className="btn btn-still btn-klein"
                onClick={() => {
                  setGeaendert(true);
                  setZeilen((alt) => [
                    ...alt,
                    {
                      schluessel: `neu-${Date.now()}`,
                      title: "",
                      quantity: 1,
                      unit_price_cents: 0,
                      discount_percent: 0,
                    },
                  ]);
                }}
              >
                <Plus size={14} aria-hidden="true" />
                Position
              </button>
            )}
          </div>

          <div className="block-inhalt">
            {!entwurf && (
              <div className="hinweis" style={{ marginBottom: "var(--am-raum-4)" }}>
                <span>
                  Dieses Angebot ist heraus. Was beim Kunden liegt, wird nicht nachträglich
                  geändert — für eine neue Fassung legen Sie ein neues Angebot an.
                </span>
              </div>
            )}

            <div className="rollbar">
              <table className="tabelle" style={{ minInlineSize: "48rem" }}>
                <thead>
                  <tr>
                    <th>Position</th>
                    <th style={{ width: "6rem", textAlign: "right" }}>Menge</th>
                    <th style={{ width: "9rem", textAlign: "right" }}>Einzelpreis</th>
                    <th style={{ width: "6rem", textAlign: "right" }}>Nachlass %</th>
                    <th style={{ width: "8rem", textAlign: "right" }}>Betrag</th>
                    {entwurf && <th style={{ width: "2rem" }} />}
                  </tr>
                </thead>
                <tbody>
                  {zeilen.map((z, i) => (
                    <tr key={z.schluessel} style={{ cursor: "default" }}>
                      <td>
                        {entwurf ? (
                          <>
                            <select
                              className="input"
                              style={{ marginBottom: "var(--am-raum-1)" }}
                              value={z.product_id ?? ""}
                              onChange={(e) => {
                                const p = produkte.data?.find((x) => x.id === e.target.value);
                                aendern(i, {
                                  product_id: e.target.value || null,
                                  // Der Preis wird aus dem Katalog übernommen,
                                  // nicht gebunden: Ändert sich der Listenpreis
                                  // später, bleibt dieses Angebot, wie es war.
                                  ...(p
                                    ? { title: p.name, unit_price_cents: p.list_price_cents }
                                    : {}),
                                });
                              }}
                              aria-label="Produkt"
                            >
                              <option value="">Freie Position</option>
                              {produkte.data?.map((p) => (
                                <option key={p.id} value={p.id}>
                                  {p.name}
                                </option>
                              ))}
                            </select>
                            <input
                              className="input"
                              value={z.title}
                              onChange={(e) => aendern(i, { title: e.target.value })}
                              placeholder="Bezeichnung"
                              aria-label="Bezeichnung"
                            />
                          </>
                        ) : (
                          <>
                            <div className="haupt">{z.title}</div>
                            {z.description && (
                              <div style={{ fontSize: "0.8125rem" }}>{z.description}</div>
                            )}
                          </>
                        )}
                      </td>
                      <td className="zahl">
                        {entwurf ? (
                          <input
                            className="input"
                            type="number"
                            min="0.01"
                            step="0.5"
                            value={z.quantity}
                            onChange={(e) => aendern(i, { quantity: Number(e.target.value) })}
                            aria-label="Menge"
                          />
                        ) : (
                          z.quantity
                        )}
                      </td>
                      <td className="zahl">
                        {entwurf ? (
                          <input
                            className="input"
                            type="number"
                            min="0"
                            step="100"
                            value={z.unit_price_cents / 100}
                            onChange={(e) =>
                              aendern(i, {
                                unit_price_cents: Math.round(Number(e.target.value) * 100),
                              })
                            }
                            aria-label="Einzelpreis in Euro"
                          />
                        ) : (
                          euroGenau(z.unit_price_cents)
                        )}
                      </td>
                      <td className="zahl">
                        {entwurf ? (
                          <input
                            className="input"
                            type="number"
                            min="0"
                            max="100"
                            step="1"
                            value={z.discount_percent ?? 0}
                            onChange={(e) =>
                              aendern(i, { discount_percent: Number(e.target.value) })
                            }
                            aria-label="Nachlass in Prozent"
                          />
                        ) : (
                          `${z.discount_percent ?? 0} %`
                        )}
                      </td>
                      <td className="zahl">{euroGenau(zeilenbetrag(z))}</td>
                      {entwurf && (
                        <td>
                          <button
                            type="button"
                            className="btn btn-still btn-klein"
                            aria-label={`Position „${z.title}" entfernen`}
                            onClick={() => {
                              setGeaendert(true);
                              setZeilen((alt) => alt.filter((_, j) => j !== i));
                            }}
                          >
                            <Trash2 size={14} aria-hidden="true" />
                          </button>
                        </td>
                      )}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            {zeilen.length === 0 && (
              <p style={{ fontSize: "0.875rem", color: "var(--am-text-gedaempft)" }}>
                Noch keine Position.
              </p>
            )}

            {entwurf && geaendert && (
              <div className="btn-reihe" style={{ marginTop: "var(--am-raum-4)" }}>
                <button
                  type="button"
                  className="btn btn-primaer btn-klein"
                  onClick={() => speichern.mutate()}
                  disabled={speichern.isPending}
                >
                  {speichern.isPending ? "Speichert …" : "Positionen speichern"}
                </button>
                <button
                  type="button"
                  className="btn btn-still btn-klein"
                  onClick={() => setGeaendert(false)}
                >
                  Verwerfen
                </button>
              </div>
            )}
            {speichern.isError && <Fehler text={(speichern.error as Error).message} />}
          </div>
        </section>

        <div>
          <section className="block">
            <div className="block-kopf">
              <h2>Summe</h2>
            </div>
            <div className="block-inhalt">
              <dl>
                <div className="eigenschaft">
                  <dt>Netto</dt>
                  <dd className="am-zahl">{euroGenau(geaendert ? netto : q.net_cents)}</dd>
                </div>
                {(geaendert ? nachlass : q.discount_total_cents) > 0 && (
                  <div className="eigenschaft">
                    <dt>Nachlass</dt>
                    <dd className="am-zahl">
                      − {euroGenau(geaendert ? nachlass : q.discount_total_cents)}
                    </dd>
                  </div>
                )}
                <div className="eigenschaft">
                  <dt>Umsatzsteuer {Math.round(q.tax_rate * 100)} %</dt>
                  <dd className="am-zahl">{euroGenau(geaendert ? steuer : q.tax_cents)}</dd>
                </div>
                <div className="eigenschaft">
                  <dt>Brutto</dt>
                  <dd className="am-zahl" style={{ fontWeight: 600 }}>
                    {euroGenau(geaendert ? netto - nachlass + steuer : q.gross_cents)}
                  </dd>
                </div>
              </dl>
              {geaendert && (
                <p style={{ fontSize: "0.75rem", color: "var(--am-text-gedaempft)" }}>
                  Vorschau. Verbindlich ist, was nach dem Speichern hier steht.
                </p>
              )}
            </div>
          </section>

          <section className="block">
            <div className="block-kopf">
              <h2>Stand</h2>
            </div>
            <div className="block-inhalt">
              <dl>
                <div className="eigenschaft">
                  <dt>Bindefrist</dt>
                  <dd>{datum(q.valid_until)}</dd>
                </div>
                <div className="eigenschaft">
                  <dt>Verschickt</dt>
                  <dd>{q.sent_at ? datumZeit(q.sent_at) : "—"}</dd>
                </div>
                <div className="eigenschaft">
                  <dt>Entschieden</dt>
                  <dd>{q.decided_at ? datumZeit(q.decided_at) : "offen"}</dd>
                </div>
                {q.decision_note && (
                  <div className="eigenschaft">
                    <dt>Vermerk</dt>
                    <dd>{q.decision_note}</dd>
                  </div>
                )}
              </dl>

              <div className="btn-reihe" style={{ marginTop: "var(--am-raum-4)" }}>
                {entwurf && (
                  <button
                    type="button"
                    className="btn btn-primaer btn-klein"
                    onClick={() => statusSetzen.mutate("sent")}
                    disabled={statusSetzen.isPending || zeilen.length === 0}
                  >
                    Als verschickt vermerken
                  </button>
                )}
                {q.status === "sent" && (
                  <>
                    <button
                      type="button"
                      className="btn btn-primaer btn-klein"
                      onClick={() => statusSetzen.mutate("accepted")}
                    >
                      Angenommen
                    </button>
                    <button
                      type="button"
                      className="btn btn-sekundaer btn-klein"
                      onClick={() => statusSetzen.mutate("rejected")}
                    >
                      Abgelehnt
                    </button>
                  </>
                )}
              </div>
              {statusSetzen.isError && <Fehler text={(statusSetzen.error as Error).message} />}
            </div>
          </section>

          <section className="block">
            <div className="block-kopf">
              <h2>Gehört zu</h2>
            </div>
            <div className="block-inhalt">
              <Link
                href={`/deals/${q.deal_id}`}
                style={{ textDecoration: "underline", textUnderlineOffset: "2px" }}
              >
                {q.deal_name}
              </Link>
            </div>
          </section>
        </div>
      </div>
    </>
  );
}
