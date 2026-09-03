"use client";

import { useQuery } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { api, suchparameter } from "@/lib/api";
import { ANGEBOT_STATUS_ART, ANGEBOT_STATUS_TEXT, datum, euro } from "@/lib/format";
import type { Quote } from "@/lib/typen";
import { Seitenkopf } from "@/components/seitenkopf";
import { Fehler, Laedt, Leer } from "@/components/zustaende";

export default function AngeboteSeite() {
  const router = useRouter();
  const [status, setStatus] = useState("");

  const abfrage = useQuery({
    queryKey: ["angebote", status],
    queryFn: () => api.get<Quote[]>(`/api/quotes${suchparameter({ status })}`),
  });

  const draussen = abfrage.data?.filter((q) => q.status === "sent") ?? [];
  const summeDraussen = draussen.reduce((s, q) => s + q.gross_cents, 0);

  return (
    <>
      <Seitenkopf
        titel="Angebote"
        zahl={
          abfrage.data
            ? `${draussen.length} beim Kunden · ${euro(summeDraussen)} brutto`
            : undefined
        }
      />

      <div className="werkzeugleiste">
        <select value={status} onChange={(e) => setStatus(e.target.value)} aria-label="Status">
          <option value="">Alle</option>
          {Object.entries(ANGEBOT_STATUS_TEXT).map(([wert, text]) => (
            <option key={wert} value={wert}>
              {text}
            </option>
          ))}
        </select>
      </div>

      <div className="liste">
        {abfrage.isPending && <Laedt />}
        {abfrage.isError && <Fehler text={(abfrage.error as Error).message} />}
        {abfrage.data?.length === 0 && (
          <Leer titel="Noch kein Angebot" text="Angebote entstehen am Geschäft." />
        )}
        {abfrage.data && abfrage.data.length > 0 && (
          <div className="rollbar">
            <table className="tabelle" style={{ minInlineSize: "48rem" }}>
              <thead>
                <tr>
                  <th>Nummer</th>
                  <th>Firma</th>
                  <th>Geschäft</th>
                  <th>Status</th>
                  <th>Bindefrist</th>
                  <th style={{ textAlign: "right" }}>Netto</th>
                  <th style={{ textAlign: "right" }}>Brutto</th>
                </tr>
              </thead>
              <tbody>
                {abfrage.data.map((q) => {
                  const abgelaufen =
                    q.status === "sent" && q.valid_until && new Date(q.valid_until) < new Date();
                  return (
                    <tr key={q.id} onClick={() => router.push(`/angebote/${q.id}`)}>
                      <td className="haupt mono">{q.number}</td>
                      <td>{q.company_name ?? "—"}</td>
                      <td>{q.deal_name}</td>
                      <td>
                        <span className="stufe" data-art={ANGEBOT_STATUS_ART[q.status]}>
                          {ANGEBOT_STATUS_TEXT[q.status]}
                        </span>
                      </td>
                      <td style={abgelaufen ? { color: "var(--am-fehler)" } : undefined}>
                        {datum(q.valid_until)}
                        {abgelaufen && " · überfällig"}
                      </td>
                      <td className="zahl">{euro(q.taxable_cents)}</td>
                      <td className="zahl">{euro(q.gross_cents)}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </>
  );
}
