"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { use } from "react";
import { api, suchparameter } from "@/lib/api";
import { datum, euro, personName } from "@/lib/format";
import type { Company, Contact, Deal } from "@/lib/typen";
import { Seitenkopf } from "@/components/seitenkopf";
import { Stufenpille, Dealstufe } from "@/components/stufe";
import { Zeitleiste } from "@/components/zeitleiste";
import { KiKnopf } from "@/components/ki-knopf";
import { Notizkasten } from "@/components/notizkasten";
import { Eigenschaftswerteblock } from "@/components/eigenschaften";
import { Stammdaten } from "@/components/stammdaten";
import { KontaktAnlegen } from "@/components/kontakt-anlegen";
import { DealAnlegen } from "@/components/deal-anlegen";
import { useQueryClient } from "@tanstack/react-query";
import type { Pipeline } from "@/lib/typen";
import { STUFEN_TEXT } from "@/lib/format";
import { useState } from "react";
import { Fehler, Laedt } from "@/components/zustaende";

function Eigenschaft({ name, wert }: { name: string; wert: React.ReactNode }) {
  return (
    <div className="eigenschaft">
      <dt>{name}</dt>
      <dd>{wert || "—"}</dd>
    </div>
  );
}

export default function FirmaSeite({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const [kontaktOffen, setKontaktOffen] = useState(false);
  const [dealOffen, setDealOffen] = useState(false);
  const client = useQueryClient();
  const pipelines = useQuery({ queryKey: ["pipelines"], queryFn: () => api.get<Pipeline[]>("/api/pipelines") });
  const standard = pipelines.data?.find((p) => p.is_default) ?? pipelines.data?.[0];

  const firma = useQuery({
    queryKey: ["firma", id],
    queryFn: () => api.get<Company>(`/api/companies/${id}`),
  });

  const kontakte = useQuery({
    queryKey: ["firma-kontakte", id],
    queryFn: () => api.get<Contact[]>(`/api/contacts${suchparameter({ company_id: id })}`),
  });

  const deals = useQuery({
    queryKey: ["firma-deals", id],
    queryFn: () => api.get<Deal[]>(`/api/deals${suchparameter({ company_id: id })}`),
  });

  if (firma.isPending) return <Laedt />;
  if (firma.isError) return <Fehler text={(firma.error as Error).message} />;

  const f = firma.data!;

  return (
    <>
      <Seitenkopf titel={f.name} pfad={{ text: "← Firmen", href: "/firmen" }}>
        <KiKnopf
          pfad={`/api/ki/companies/${id}/zusammenfassung`}
          text="Stand zusammenfassen"
          invalidiert={["firma", id]}
        />
      </Seitenkopf>

      {dealOffen && standard && (
        <DealAnlegen
          pipelineId={standard.id}
          stufen={standard.stages}
          firmaId={id}
          beiSchliessen={() => setDealOffen(false)}
          beiErfolg={() => { setDealOffen(false); client.invalidateQueries({ queryKey: ["firma-deals", id] }); client.invalidateQueries({ queryKey: ["firma", id] }); }}
        />
      )}

      {kontaktOffen && (
        <KontaktAnlegen firmaId={id} beiSchliessen={() => setKontaktOffen(false)} beiErfolg={() => { setKontaktOffen(false); kontakte.refetch(); }} />
      )}

      <div className="datensatz">
        {/* Links: was die Firma ist */}
        <div>
          <Stammdaten
            titel="Über diese Firma"
            pfad={`/api/companies/${id}`}
            abfrageSchluessel={["firma", id]}
            zurueckNach="/firmen"
            loeschtext="Die Firma wird aus allen Listen genommen. Kontakte und Geschäfte bleiben bestehen und lassen sich 30 Tage wiederherstellen."
            kopfrechts={<Stufenpille stufe={f.lifecycle_stage} />}
            werte={f as unknown as Record<string, unknown>}
            felder={[
              { key: "name", text: "Name" },
              { key: "domain", text: "Domain", zeige: (v) => <a href={`https://${String(v)}`} target="_blank" rel="noreferrer noopener" style={{ textDecoration: "underline", textUnderlineOffset: "2px" }}>{String(v)}</a> },
              { key: "industry", text: "Branche" },
              { key: "employee_count", text: "Mitarbeiter", art: "number" },
              { key: "street", text: "Straße" },
              { key: "postal_code", text: "PLZ" },
              { key: "city", text: "Ort" },
              { key: "phone", text: "Telefon" },
              { key: "lifecycle_stage", text: "Stufe", art: "select", optionen: Object.entries(STUFEN_TEXT).map(([wert, text]) => ({ wert, text })) },
              { key: "source", text: "Herkunft" },
              { key: "description", text: "Beschreibung", art: "textarea" },
            ]}
          />

          <Eigenschaftswerteblock entity="companies" id={id} werte={f.custom} abfrageSchluessel={["firma", id]} />

          {f.ai_summary && (
            <section className="block">
              <div className="block-inhalt">
                <div className="ki-block">
                  <div className="ki-block-kopf">
                    Von der KI · {datum(f.ai_summary_at)}
                  </div>
                  <p className="ki-block-text">{f.ai_summary}</p>
                </div>
              </div>
            </section>
          )}
        </div>

        {/* Mitte: was passiert ist */}
        <div>
          <Notizkasten bezug={{ company_id: id }} />
          <Zeitleiste bezug={{ company_id: id }} />
        </div>

        {/* Rechts: was daranhängt */}
        <div>
          <section className="block">
            <div className="block-kopf">
              <h2>Deals</h2>
              <button type="button" className="btn btn-still btn-klein" onClick={() => setDealOffen(true)} disabled={!standard}>Anlegen</button>
            </div>
            <div className="block-inhalt">
              {deals.data?.length === 0 && (
                <p style={{ fontSize: "0.875rem", color: "var(--am-text-gedaempft)" }}>
                  Noch kein Geschäft.
                </p>
              )}
              {deals.data?.map((d) => (
                <Link
                  key={d.id}
                  href={`/deals/${d.id}`}
                  className="deal-karte"
                  style={{ marginBottom: "var(--am-raum-2)" }}
                >
                  <div className="deal-karte-name">{d.name}</div>
                  <div className="deal-karte-fuss">
                    <span className="deal-karte-betrag">{euro(d.amount_cents)}</span>
                    <Dealstufe name={d.stage_name} art={d.stage_kind} />
                  </div>
                </Link>
              ))}
            </div>
          </section>

          <section className="block">
            <div className="block-kopf">
              <h2>Kontakte</h2>
              <button type="button" className="btn btn-still btn-klein" onClick={() => setKontaktOffen(true)}>Anlegen</button>
            </div>
            <div className="block-inhalt">
              {kontakte.data?.length === 0 && (
                <p style={{ fontSize: "0.875rem", color: "var(--am-text-gedaempft)" }}>
                  Noch niemand hinterlegt.
                </p>
              )}
              <dl>
                {kontakte.data?.map((k) => (
                  <div className="eigenschaft" key={k.id}>
                    <dt>{k.job_title ?? "Rolle unbekannt"}</dt>
                    <dd>
                      <Link
                        href={`/kontakte/${k.id}`}
                        style={{ textDecoration: "underline", textUnderlineOffset: "2px" }}
                      >
                        {personName(k.first_name, k.last_name)}
                      </Link>
                      {k.buying_role && (
                        <span
                          style={{
                            marginLeft: "var(--am-raum-2)",
                            fontSize: "0.75rem",
                            color: "var(--am-text-gedaempft)",
                          }}
                        >
                          {k.buying_role}
                        </span>
                      )}
                    </dd>
                  </div>
                ))}
              </dl>
            </div>
          </section>
        </div>
      </div>
    </>
  );
}
