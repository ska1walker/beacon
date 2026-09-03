"use client";

import { useQuery } from "@tanstack/react-query";
import { Search } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { api, suchparameter } from "@/lib/api";
import { euro, STUFEN_TEXT } from "@/lib/format";
import type { Company } from "@/lib/typen";
import { Seitenkopf } from "@/components/seitenkopf";
import { Stufenpille } from "@/components/stufe";
import { Fehler, Laedt, Leer } from "@/components/zustaende";
import { FirmaAnlegen } from "@/components/firma-anlegen";

export default function FirmenSeite() {
  const router = useRouter();
  const [suche, setSuche] = useState("");
  const [stufe, setStufe] = useState("");
  const [offen, setOffen] = useState(false);

  const abfrage = useQuery({
    queryKey: ["firmen", suche, stufe],
    queryFn: () => api.get<Company[]>(`/api/companies${suchparameter({ q: suche, stage: stufe })}`),
  });

  return (
    <>
      <Seitenkopf titel="Firmen" zahl={abfrage.data ? `${abfrage.data.length} Einträge` : undefined}>
        <button type="button" className="btn btn-primaer" onClick={() => setOffen(true)}>
          Firma anlegen
        </button>
      </Seitenkopf>

      {offen && (
        <FirmaAnlegen
          beiSchliessen={() => setOffen(false)}
          beiErfolg={(id) => {
            setOffen(false);
            router.push(`/firmen/${id}`);
          }}
        />
      )}

      <div className="werkzeugleiste">
        <div className="suchfeld">
          <Search size={16} aria-hidden="true" />
          <input
            value={suche}
            onChange={(e) => setSuche(e.target.value)}
            placeholder="Name, Domain oder Ort"
            aria-label="Firmen durchsuchen"
          />
        </div>
        <select value={stufe} onChange={(e) => setStufe(e.target.value)} aria-label="Stufe filtern">
          <option value="">Alle Stufen</option>
          {Object.entries(STUFEN_TEXT).map(([wert, text]) => (
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
          <Leer
            titel="Keine Firma gefunden"
            text="Entweder ist die Suche zu eng, oder hier ist noch nichts angelegt."
          />
        )}
        {abfrage.data && abfrage.data.length > 0 && (
          <div className="rollbar">
            <table className="tabelle" style={{ minInlineSize: "44rem" }}>
              <thead>
                <tr>
                  <th>Firma</th>
                  <th>Branche</th>
                  <th>Ort</th>
                  <th>Stufe</th>
                  <th style={{ textAlign: "right" }}>Kontakte</th>
                  <th style={{ textAlign: "right" }}>Offene Deals</th>
                  <th style={{ textAlign: "right" }}>Offener Wert</th>
                </tr>
              </thead>
              <tbody>
                {abfrage.data.map((f) => (
                  <tr key={f.id} onClick={() => router.push(`/firmen/${f.id}`)}>
                    <td className="haupt">{f.name}</td>
                    <td>{f.industry ?? "—"}</td>
                    <td>{f.city ?? "—"}</td>
                    <td>
                      <Stufenpille stufe={f.lifecycle_stage} />
                    </td>
                    <td className="zahl">{f.contact_count}</td>
                    <td className="zahl">{f.open_deal_count}</td>
                    <td className="zahl">{euro(f.open_amount_cents)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </>
  );
}
