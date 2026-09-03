"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Copy } from "lucide-react";
import { useState } from "react";
import { api } from "@/lib/api";
import { datumZeit } from "@/lib/format";
import type { Quelle, QuelleNeu } from "@/lib/typen";
import { Fehler, Laedt } from "@/components/zustaende";

/**
 * Quellen, die Ereignisse an dieses CRM schicken dürfen — zuerst Insilo.
 *
 * Das Geheimnis wird genau einmal gezeigt. Es später noch einmal
 * auszuliefern hieße, es dauerhaft ausliefern zu können.
 */
export function Quellenblock() {
  const client = useQueryClient();
  const [name, setName] = useState("Insilo auf dieser Box");
  const [neu, setNeu] = useState<QuelleNeu | null>(null);

  const quellen = useQuery({
    queryKey: ["quellen"],
    queryFn: () => api.get<Quelle[]>("/api/quellen"),
  });

  const anlegen = useMutation({
    mutationFn: () => api.post<QuelleNeu>("/api/quellen", { name, kind: "insilo" }),
    onSuccess: (q) => {
      setNeu(q);
      client.invalidateQueries({ queryKey: ["quellen"] });
    },
  });

  const abschalten = useMutation({
    mutationFn: (id: string) => api.del(`/api/quellen/${id}`),
    onSuccess: () => client.invalidateQueries({ queryKey: ["quellen"] }),
  });

  if (quellen.isPending) return <Laedt />;

  const basis = typeof window === "undefined" ? "" : window.location.origin;

  return (
    <section className="block">
      <div className="block-kopf">
        <h2>Eingehende Quellen</h2>
      </div>
      <div className="block-inhalt">
        <p style={{ fontSize: "0.875rem", color: "var(--am-text-sekundaer)", marginBottom: "var(--am-raum-4)" }}>
          Insilo schickt nach einer Besprechung ein signiertes Ereignis mit dem fertigen
          Protokoll. Legen Sie hier eine Quelle an und tragen Sie Adresse und Geheimnis in
          Insilo unter <em>Einstellungen → Webhooks</em> ein. Das Protokoll landet danach am
          passenden Geschäft; was mehrdeutig ist, wartet im Eingang.
        </p>

        {neu && (
          <div className="ki-block" style={{ marginBottom: "var(--am-raum-4)" }}>
            <div className="ki-block-kopf">Einmalig — jetzt kopieren</div>
            <dl>
              <div className="eigenschaft">
                <dt>Adresse</dt>
                <dd className="mono" style={{ wordBreak: "break-all" }}>
                  {basis}
                  {neu.pfad}
                </dd>
              </div>
              <div className="eigenschaft">
                <dt>Geheimnis</dt>
                <dd className="mono" style={{ wordBreak: "break-all" }}>
                  {neu.secret}
                </dd>
              </div>
            </dl>
            <div className="btn-reihe" style={{ marginTop: "var(--am-raum-3)" }}>
              <button
                type="button"
                className="btn btn-still btn-klein"
                onClick={() =>
                  navigator.clipboard.writeText(`${basis}${neu.pfad}\n${neu.secret}`)
                }
              >
                <Copy size={14} aria-hidden="true" />
                Beides kopieren
              </button>
              <button
                type="button"
                className="btn btn-still btn-klein"
                onClick={() => setNeu(null)}
              >
                Habe ich
              </button>
            </div>
            <p style={{ fontSize: "0.75rem", marginTop: "var(--am-raum-2)" }}>
              Das Geheimnis wird nicht wieder angezeigt. Wer es verliert, legt eine neue
              Quelle an und schaltet diese ab.
            </p>
          </div>
        )}

        {quellen.data && quellen.data.length > 0 && (
          <table className="tabelle" style={{ marginBottom: "var(--am-raum-4)" }}>
            <thead>
              <tr>
                <th>Name</th>
                <th>Art</th>
                <th>Zuletzt gehört</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {quellen.data
                .filter((q) => q.is_active)
                .map((q) => (
                  <tr key={q.id} style={{ cursor: "default" }}>
                    <td className="haupt">{q.name}</td>
                    <td>{q.kind}</td>
                    <td>{q.last_seen_at ? datumZeit(q.last_seen_at) : "noch nie"}</td>
                    <td style={{ textAlign: "right" }}>
                      <button
                        type="button"
                        className="btn btn-still btn-klein"
                        onClick={() => abschalten.mutate(q.id)}
                      >
                        Abschalten
                      </button>
                    </td>
                  </tr>
                ))}
            </tbody>
          </table>
        )}

        <form
          style={{ display: "flex", gap: "var(--am-raum-2)", alignItems: "flex-end" }}
          onSubmit={(e) => {
            e.preventDefault();
            anlegen.mutate();
          }}
        >
          <div className="feld" style={{ flex: 1, marginBottom: 0 }}>
            <label htmlFor="quellenname">Name der Quelle</label>
            <input id="quellenname" value={name} onChange={(e) => setName(e.target.value)} />
          </div>
          <button type="submit" className="btn btn-primaer" disabled={anlegen.isPending}>
            {anlegen.isPending ? "Legt an …" : "Quelle anlegen"}
          </button>
        </form>
        {anlegen.isError && <Fehler text={(anlegen.error as Error).message} />}
      </div>
    </section>
  );
}
