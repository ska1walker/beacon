"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { use } from "react";
import { api } from "@/lib/api";
import { datumZeit, frist, PRIORITAET_TEXT, QUELLE_TEXT } from "@/lib/format";
import type { Mitglied, Ticket, Ticketkategorie, Ticketpipeline } from "@/lib/typen";
import { Seitenkopf } from "@/components/seitenkopf";
import { Zeitleiste } from "@/components/zeitleiste";
import { Notizkasten } from "@/components/notizkasten";
import { Stammdaten } from "@/components/stammdaten";
import { Prioritaetspille } from "@/components/prioritaet";
import { Fehler, Laedt } from "@/components/zustaende";

export default function TicketSeite({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const client = useQueryClient();

  const ticket = useQuery({
    queryKey: ["ticket", id],
    queryFn: () => api.get<Ticket>(`/api/tickets/${id}`),
  });

  const pipelines = useQuery({
    queryKey: ["ticket-pipelines"],
    queryFn: () => api.get<Ticketpipeline[]>("/api/tickets/pipelines"),
  });

  const mitglieder = useQuery({
    queryKey: ["mitglieder"],
    queryFn: () => api.get<Mitglied[]>("/api/mitglieder"),
  });

  const kategorien = useQuery({
    queryKey: ["ticket-kategorien"],
    queryFn: () => api.get<Ticketkategorie[]>("/api/tickets/kategorien"),
  });

  const frisch = () => {
    client.invalidateQueries({ queryKey: ["ticket", id] });
    client.invalidateQueries({ queryKey: ["ticket-brett"] });
    client.invalidateQueries({ queryKey: ["aktivitaeten"] });
  };

  const stufeSetzen = useMutation({
    mutationFn: (stage_id: string) => api.post<Ticket>(`/api/tickets/${id}/stufe`, { stage_id }),
    onSuccess: frisch,
  });

  const feldSetzen = useMutation({
    mutationFn: (teil: Record<string, unknown>) => api.patch<Ticket>(`/api/tickets/${id}`, teil),
    onSuccess: frisch,
  });

  if (ticket.isPending) return <Laedt />;
  if (ticket.isError) return <Fehler text={(ticket.error as Error).message} />;

  const t = ticket.data!;
  const pipeline = pipelines.data?.find((p) => p.id === t.pipeline_id);

  return (
    <>
      <Seitenkopf
        titel={t.betreff}
        zahl={`${t.kennung} · ${QUELLE_TEXT[t.quelle] ?? t.quelle}`}
        pfad={{ text: "← Tickets", href: "/tickets" }}
      >
        <Prioritaetspille prioritaet={t.prioritaet} />
        {t.offen && (
          <span className="frist" data-ueberfaellig={t.ueberfaellig ? "true" : undefined}>
            {frist(t.faellig_am)}
          </span>
        )}
      </Seitenkopf>

      {/* Die Stufen als Leiste: Wo steht das Anliegen, und was ist der
          nächste Schritt — ein Klick, kein Menü. */}
      {pipeline && (
        <div className="stufenleiste" role="group" aria-label="Stufe">
          {pipeline.stufen.map((s) => (
            <button
              key={s.id}
              type="button"
              className={`stufenschritt${s.id === t.stage_id ? " aktiv" : ""}`}
              aria-current={s.id === t.stage_id ? "step" : undefined}
              disabled={stufeSetzen.isPending}
              onClick={() => s.id !== t.stage_id && stufeSetzen.mutate(s.id)}
            >
              {s.name}
            </button>
          ))}
        </div>
      )}

      {stufeSetzen.isError && (
        <div style={{ padding: "0 var(--am-raum-8)" }}>
          <Fehler text={(stufeSetzen.error as Error).message} />
        </div>
      )}

      <div className="datensatz">
        <div>
          <Stammdaten
            titel="Über dieses Ticket"
            pfad={`/api/tickets/${id}`}
            abfrageSchluessel={["ticket", id]}
            zurueckNach="/tickets"
            loeschtext="Das Ticket wird aus allen Listen genommen. Verlauf und Aufgaben bleiben 30 Tage wiederherstellbar."
            werte={t as unknown as Record<string, unknown>}
            felder={[
              { key: "betreff", text: "Betreff" },
              { key: "beschreibung", text: "Beschreibung", art: "textarea" },
              {
                key: "prioritaet",
                text: "Dringlichkeit",
                art: "select",
                optionen: Object.entries(PRIORITAET_TEXT).map(([wert, text]) => ({ wert, text })),
              },
              {
                key: "kategorie",
                text: "Kategorie",
                art: "select",
                optionen: [
                  { wert: "", text: "— keine —" },
                  ...(kategorien.data ?? []).map((c) => ({ wert: c.name, text: c.name })),
                ],
              },
            ]}
          />

          <section className="block">
            <div className="block-kopf">
              <h2>Zuständig und Bezug</h2>
            </div>
            <div className="block-inhalt">
              <div className="feld">
                <label htmlFor="zustaendig">Zuständig</label>
                <select
                  id="zustaendig"
                  value={t.owner_id ?? ""}
                  onChange={(e) => feldSetzen.mutate({ owner_id: e.target.value || null })}
                >
                  <option value="">— niemand —</option>
                  {mitglieder.data?.map((m) => (
                    <option key={m.id} value={m.id}>
                      {m.display_name ?? m.olares_username}
                    </option>
                  ))}
                </select>
                {!t.owner_id && (
                  <p className="feld-hinweis">
                    Ohne Zuständige ist das Ticket eine Warteschlange, keine Arbeit.
                  </p>
                )}
              </div>

              <dl>
                <div className="eigenschaft">
                  <dt>Firma</dt>
                  <dd>
                    {t.company_id ? (
                      <Link href={`/firmen/${t.company_id}`} className="zellen-link">
                        {t.firma_name}
                      </Link>
                    ) : (
                      "—"
                    )}
                  </dd>
                </div>
                <div className="eigenschaft">
                  <dt>Kontakt</dt>
                  <dd>
                    {t.contact_id ? (
                      <Link href={`/kontakte/${t.contact_id}`} className="zellen-link">
                        {t.kontakt_name?.trim() || t.kontakt_email}
                      </Link>
                    ) : (
                      "—"
                    )}
                  </dd>
                </div>
                <div className="eigenschaft">
                  <dt>Geschäft</dt>
                  <dd>
                    {t.deal_id ? (
                      <Link href={`/deals/${t.deal_id}`} className="zellen-link">
                        zum Geschäft
                      </Link>
                    ) : (
                      "—"
                    )}
                  </dd>
                </div>
              </dl>
            </div>
          </section>

          <section className="block">
            <div className="block-kopf">
              <h2>Die Uhr</h2>
            </div>
            <div className="block-inhalt">
              <dl>
                <div className="eigenschaft">
                  <dt>Eingegangen</dt>
                  <dd>{datumZeit(t.created_at)}</dd>
                </div>
                <div className="eigenschaft">
                  <dt>Frist</dt>
                  <dd>
                    {t.faellig_am ? `${datumZeit(t.faellig_am)} · ${frist(t.faellig_am)}` : "ohne"}
                  </dd>
                </div>
                <div className="eigenschaft">
                  <dt>Erste Antwort</dt>
                  <dd>{t.erste_antwort_am ? datumZeit(t.erste_antwort_am) : "steht aus"}</dd>
                </div>
                <div className="eigenschaft">
                  <dt>Geschlossen</dt>
                  <dd>{t.geschlossen_am ? datumZeit(t.geschlossen_am) : "offen"}</dd>
                </div>
              </dl>
              {t.stufe_art === "wartet_auf_kontakt" && (
                <p style={{ fontSize: "0.8125rem", color: "var(--am-text-sekundaer)", marginTop: "var(--am-raum-3)" }}>
                  Die Frist pausiert, solange wir auf den Kontakt warten. Die Zeit des Kunden ist
                  nicht unsere Frist.
                </p>
              )}
            </div>
          </section>
        </div>

        <div>
          <Notizkasten bezug={{ ticket_id: id }} />
          <Zeitleiste bezug={{ ticket_id: id }} />
        </div>
      </div>
    </>
  );
}
