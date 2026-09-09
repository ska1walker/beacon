"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { use, useState } from "react";
import { api, suchparameter } from "@/lib/api";
import {
  ANGEBOT_STATUS_ART,
  ANGEBOT_STATUS_TEXT,
  datum,
  euro,
  PRODUKT_TEXT,
  prozent,
  vorgangswort,
} from "@/lib/format";
import type { Board, Company, Deal, Mitglied, Quote, Verlustgrund } from "@/lib/typen";
import { Beteiligtenblock } from "@/components/beteiligte";
import { Seitenkopf } from "@/components/seitenkopf";
import { Dealstufe } from "@/components/stufe";
import { Zeitleiste } from "@/components/zeitleiste";
import { KiKnopf } from "@/components/ki-knopf";
import { Podcastblock } from "@/components/podcast";
import { Fehler, Laedt } from "@/components/zustaende";
import { AngebotAnlegen } from "@/components/angebot-anlegen";
import { Qualifizierungsblock } from "@/components/qualifizierung";
import { Eigenschaftswerteblock } from "@/components/eigenschaften";
import { Stammdaten } from "@/components/stammdaten";
import { Notizkasten } from "@/components/notizkasten";
import { Dokumente } from "@/components/dokumente";

export default function DealSeite({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const client = useQueryClient();
  const [angebotOffen, setAngebotOffen] = useState(false);
  // Beim Verlieren wird nach dem Grund gefragt. Ohne ihn ist die
  // Verlustanalyse in der Prognose eine Liste aus „ohne Kategorie".
  const [verlorenStufe, setVerlorenStufe] = useState<string | null>(null);
  const [grund, setGrund] = useState("");
  const [grundText, setGrundText] = useState("");

  const deal = useQuery({
    queryKey: ["deal", id],
    queryFn: () => api.get<Deal>(`/api/deals/${id}`),
  });

  // Für die nachträgliche Zuordnung. Ein Lead entsteht oft, bevor
  // feststeht, welche Firma dahintersteht.
  const firmen = useQuery({
    queryKey: ["firmen-auswahl"],
    queryFn: () => api.get<Company[]>("/api/companies?limit=200"),
  });

  const angebote = useQuery({
    queryKey: ["angebote", "deal", id],
    queryFn: () => api.get<Quote[]>(`/api/quotes${suchparameter({ deal_id: id })}`),
  });

  const board = useQuery({
    queryKey: ["board"],
    queryFn: () => api.get<Board>("/api/board"),
  });

  const mitglieder = useQuery({
    queryKey: ["mitglieder"],
    queryFn: () => api.get<Mitglied[]>("/api/mitglieder"),
  });

  const zustaendig = useMutation({
    mutationFn: (owner_id: string | null) => api.patch<Deal>(`/api/deals/${id}`, { owner_id }),
    onSuccess: () => {
      client.invalidateQueries({ queryKey: ["deal", id] });
      client.invalidateQueries({ queryKey: ["board"] });
    },
  });

  const verlustgruende = useQuery({
    queryKey: ["verlustgruende"],
    queryFn: () => api.get<Verlustgrund[]>("/api/verlustgruende"),
  });

  const verlorenMelden = useMutation({
    mutationFn: async (stageId: string) => {
      await api.post<Deal>(`/api/deals/${id}/stage`, { stage_id: stageId });
      await api.post(`/api/deals/${id}/verloren`, {
        lost_reason_id: grund || null,
        lost_reason: grundText || null,
      });
    },
    onSuccess: () => {
      setVerlorenStufe(null);
      setGrund("");
      setGrundText("");
      client.invalidateQueries({ queryKey: ["deal", id] });
      client.invalidateQueries({ queryKey: ["aktivitaeten"] });
      client.invalidateQueries({ queryKey: ["board"] });
      client.invalidateQueries({ queryKey: ["prognose"] });
    },
  });

  const verschieben = useMutation({
    mutationFn: (stageId: string) => api.post<Deal>(`/api/deals/${id}/stage`, { stage_id: stageId }),
    onSuccess: () => {
      client.invalidateQueries({ queryKey: ["deal", id] });
      client.invalidateQueries({ queryKey: ["aktivitaeten"] });
      client.invalidateQueries({ queryKey: ["board"] });
    },
  });

  if (deal.isPending) return <Laedt />;
  if (deal.isError) return <Fehler text={(deal.error as Error).message} />;

  const d = deal.data!;
  // Offen ist ein Lead, gewonnen ein Deal. Das Wort folgt der Stufe,
  // damit auf der Seite nichts steht, was noch nicht stimmt.
  const wort = vorgangswort(d.stage_kind);
  const ueberfaellig =
    d.stage_kind === "open" && d.close_date && new Date(d.close_date) < new Date();

  return (
    <>
      <Seitenkopf
        titel={d.name}
        zahl={`${wort} · ${euro(d.amount_cents)} · ${PRODUKT_TEXT[d.product]}`}
        pfad={{ text: "← Pipeline", href: "/deals" }}
      >
        <KiKnopf
          pfad={`/api/ki/deals/${id}/naechster-schritt`}
          text="Nächsten Schritt vorschlagen"
          invalidiert={["deal", id]}
        />
      </Seitenkopf>

      {angebotOffen && (
        <AngebotAnlegen dealId={id} beiSchliessen={() => setAngebotOffen(false)} />
      )}

      {verlorenStufe && (
        <div className="dialog-schicht" role="dialog" aria-modal="true" aria-label="Verlustgrund">
          <div className="karte" style={{ maxWidth: "440px", width: "100%" }}>
            <h2 style={{ marginBottom: "var(--am-raum-4)", fontSize: "1.125rem" }}>
              Woran ist es gescheitert?
            </h2>
            <p style={{ fontSize: "0.875rem", color: "var(--am-text-sekundaer)", marginBottom: "var(--am-raum-6)" }}>
              Der Grund ist die einzige Frage, die aus einem verlorenen Geschäft noch etwas
              macht. Er steht später in der Prognose.
            </p>

            <div className="feld">
              <label htmlFor="verlustgrund">Grund</label>
              <select id="verlustgrund" value={grund} onChange={(e) => setGrund(e.target.value)}>
                <option value="">— noch offen —</option>
                {verlustgruende.data?.map((g) => (
                  <option key={g.id} value={g.id}>
                    {g.name}
                  </option>
                ))}
              </select>
            </div>

            <div className="feld">
              <label htmlFor="verlusttext">
                Was genau <span className="optional">optional</span>
              </label>
              <textarea
                id="verlusttext"
                rows={3}
                value={grundText}
                onChange={(e) => setGrundText(e.target.value)}
                placeholder="20 % über dem Mitbewerber, Entscheidung im Vorstand gekippt …"
              />
            </div>

            {verlorenMelden.isError && (
              <Fehler text={(verlorenMelden.error as Error).message} />
            )}

            <div className="btn-reihe">
              <button
                type="button"
                className="btn btn-primaer"
                onClick={() => verlorenMelden.mutate(verlorenStufe)}
                disabled={verlorenMelden.isPending}
              >
                {verlorenMelden.isPending ? "Speichert …" : "Als verloren vermerken"}
              </button>
              <button
                type="button"
                className="btn btn-still"
                onClick={() => setVerlorenStufe(null)}
              >
                Abbrechen
              </button>
            </div>
          </div>
        </div>
      )}

      <div className="datensatz">
        <div>
          <Stammdaten
            titel={`Über diesen ${wort}`}
            pfad={`/api/deals/${id}`}
            abfrageSchluessel={["deal", id]}
            zurueckNach="/deals"
            loeschtext={`Der ${wort} verschwindet vom Board und aus der Prognose. Verlauf und Angebote bleiben 30 Tage wiederherstellbar.`}
            kopfrechts={<Dealstufe name={d.stage_name} art={d.stage_kind} />}
            werte={d as unknown as Record<string, unknown>}
            felder={[
              { key: "name", text: "Bezeichnung" },
              {
                key: "company_id",
                text: "Firma",
                art: "select",
                optionen: (firmen.data ?? []).map((f) => ({ wert: f.id, text: f.name })),
                auchLeer: true,
                // Angezeigt wird der Name als Verweis, bearbeitet die
                // Kennung: Ein Lead ohne Firma soll sich zuordnen lassen,
                // ohne dass jemand eine UUID abtippt.
                zeige: () =>
                  d.company_id ? (
                    <Link href={`/firmen/${d.company_id}`} style={{ textDecoration: "underline", textUnderlineOffset: "2px" }}>
                      {d.company_name}
                    </Link>
                  ) : (
                    <span className="ohne-zuordnung">noch keine — über „Bearbeiten“ zuordnen</span>
                  ),
              },
              { key: "product", text: "Produkt", art: "select", optionen: Object.entries(PRODUKT_TEXT).map(([wert, text]) => ({ wert, text })) },
              { key: "amount_cents", text: "Betrag netto", art: "number", skala: 100, zeige: (v) => euro(Number(v)) },
              { key: "probability", text: "Wahrscheinlichkeit", zeige: (v) => prozent(Number(v)) },
              { key: "close_date", text: "Abschluss geplant", art: "date", zeige: (v) => <span style={ueberfaellig ? { color: "var(--am-fehler)" } : undefined}>{datum(String(v))}{ueberfaellig && " · überfällig"}</span> },
              { key: "service_days", text: "Servicetage", art: "number" },
              { key: "next_step", text: "Nächster Schritt", art: "textarea" },
              { key: "owner_id", text: "Zuständig", art: "select", optionen: (mitglieder.data ?? []).map((m) => ({ wert: m.id, text: m.display_name ?? m.olares_username })) },
              { key: "lost_reason", text: "Grund für die Absage", art: "textarea" },
            ]}
          />

          <Beteiligtenblock dealId={id} />

          <Eigenschaftswerteblock entity="deals" id={id} werte={d.custom} abfrageSchluessel={["deal", id]} />

          <Qualifizierungsblock dealId={id} />

          <section className="block">
            <div className="block-kopf">
              <h2>Stufe wechseln</h2>
            </div>
            <div className="block-inhalt">
              <div className="btn-reihe">
                {board.data?.pipeline.stages.map((s) => (
                  <button
                    key={s.id}
                    type="button"
                    className={`btn btn-klein ${s.id === d.stage_id ? "btn-primaer" : "btn-sekundaer"}`}
                    disabled={s.id === d.stage_id || verschieben.isPending}
                    onClick={() =>
                      s.kind === "lost" ? setVerlorenStufe(s.id) : verschieben.mutate(s.id)
                    }
                  >
                    {s.name}
                  </button>
                ))}
              </div>
              {verschieben.isError && <Fehler text={(verschieben.error as Error).message} />}
            </div>
          </section>

          {d.ai_summary && (
            <section className="block">
              <div className="block-inhalt">
                <div className="ki-block">
                  <div className="ki-block-kopf">Vorschlag der KI</div>
                  <p className="ki-block-text">{d.ai_summary}</p>
                </div>
              </div>
            </section>
          )}

          <Podcastblock entity="deals" entityId={id} />
        </div>

        <div>
          <Notizkasten bezug={{ deal_id: id, company_id: d.company_id ?? undefined }} />
          <Zeitleiste bezug={{ deal_id: id }} />
        </div>

        <div>
          <section className="block">
            <div className="block-kopf">
              <h2>Angebote</h2>
              <button
                type="button"
                className="btn btn-still btn-klein"
                onClick={() => setAngebotOffen(true)}
              >
                Anlegen
              </button>
            </div>
            <div className="block-inhalt">
              {angebote.data?.length === 0 && (
                <p style={{ fontSize: "0.875rem", color: "var(--am-text-gedaempft)" }}>
                  Noch kein Angebot.
                </p>
              )}
              {angebote.data?.map((a) => (
                <Link
                  key={a.id}
                  href={`/angebote/${a.id}`}
                  className="deal-karte"
                  style={{ marginBottom: "var(--am-raum-2)" }}
                >
                  <div className="deal-karte-name mono">{a.number}</div>
                  <div className="deal-karte-fuss">
                    <span className="deal-karte-betrag">{euro(a.gross_cents)}</span>
                    <span className="stufe" data-art={ANGEBOT_STATUS_ART[a.status]}>
                      {ANGEBOT_STATUS_TEXT[a.status]}
                    </span>
                  </div>
                </Link>
              ))}
            </div>
          </section>

          <section className="block">
            <div className="block-kopf">
              <h2>Verlauf des {wort}s</h2>
            </div>
            <div className="block-inhalt">
              <dl>
                <div className="eigenschaft">
                  <dt>Angelegt</dt>
                  <dd>{datum(d.created_at)}</dd>
                </div>
                <div className="eigenschaft">
                  <dt>Zuletzt bewegt</dt>
                  <dd>{datum(d.updated_at)}</dd>
                </div>
                <div className="eigenschaft">
                  <dt>Geschlossen</dt>
                  <dd>{d.closed_at ? datum(d.closed_at) : "offen"}</dd>
                </div>
              </dl>
            </div>
          </section>

          {/* Dokumente ganz unten: gesucht wird hier selten, gefunden dafür immer. */}
          <Dokumente bezug={{ deal_id: id }} />
        </div>
      </div>
    </>
  );
}
