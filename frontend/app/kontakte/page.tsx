"use client";

import { useQuery } from "@tanstack/react-query";
import { Search } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { api, suchparameter } from "@/lib/api";
import { personName } from "@/lib/format";
import type { Contact } from "@/lib/typen";
import { Seitenkopf } from "@/components/seitenkopf";
import { Stufenpille } from "@/components/stufe";
import { Fehler, Laedt, Leer } from "@/components/zustaende";

export default function KontakteSeite() {
  const router = useRouter();
  const [suche, setSuche] = useState("");

  const abfrage = useQuery({
    queryKey: ["kontakte", suche],
    queryFn: () => api.get<Contact[]>(`/api/contacts${suchparameter({ q: suche })}`),
  });

  return (
    <>
      <Seitenkopf
        titel="Kontakte"
        zahl={abfrage.data ? `${abfrage.data.length} Einträge` : undefined}
      />

      <div className="werkzeugleiste">
        <div className="suchfeld">
          <Search size={16} aria-hidden="true" />
          <input
            value={suche}
            onChange={(e) => setSuche(e.target.value)}
            placeholder="Name, E-Mail oder Firma"
            aria-label="Kontakte durchsuchen"
          />
        </div>
      </div>

      <div className="liste">
        {abfrage.isPending && <Laedt />}
        {abfrage.isError && <Fehler text={(abfrage.error as Error).message} />}
        {abfrage.data?.length === 0 && (
          <Leer titel="Kein Kontakt gefunden" text="Kontakte entstehen an der Firma." />
        )}
        {abfrage.data && abfrage.data.length > 0 && (
          <div className="rollbar">
            <table className="tabelle" style={{ minInlineSize: "42rem" }}>
              <thead>
                <tr>
                  <th>Name</th>
                  <th>Position</th>
                  <th>Firma</th>
                  <th>Kaufrolle</th>
                  <th>E-Mail</th>
                  <th>Stufe</th>
                </tr>
              </thead>
              <tbody>
                {abfrage.data.map((k) => (
                  <tr key={k.id} onClick={() => router.push(`/kontakte/${k.id}`)}>
                    <td className="haupt">{personName(k.first_name, k.last_name)}</td>
                    <td>{k.job_title ?? "—"}</td>
                    <td>{k.company_name ?? "—"}</td>
                    <td>{k.buying_role ?? "—"}</td>
                    <td>{k.email ?? "—"}</td>
                    <td>
                      <Stufenpille stufe={k.lifecycle_stage} />
                    </td>
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
