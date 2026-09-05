"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Copy } from "lucide-react";
import { useState } from "react";
import { api } from "@/lib/api";
import { datumZeit } from "@/lib/format";
import type { Quelle, Quellenart, QuelleNeu } from "@/lib/typen";
import { Fehler, Laedt } from "@/components/zustaende";
import { Erklaerung } from "@/components/erklaerung";

/** Wie eine Quelle heißt, die kein Mensch ist. */
const ART_TEXT: Record<string, string> = {
  insilo: "Insilo — Besprechungen",
  api: "Schnittstelle — Tickets",
  bot: "Bot — Tickets",
  formular: "Formular — Tickets",
};

/**
 * Quellen, die Ereignisse an dieses CRM schicken dürfen.
 *
 * Das Geheimnis wird genau einmal gezeigt. Es später noch einmal
 * auszuliefern hieße, es dauerhaft ausliefern zu können.
 */
export function Quellenblock() {
  const client = useQueryClient();
  const [name, setName] = useState("Insilo auf dieser Box");
  const [art, setArt] = useState<Quellenart>("insilo");
  const [direkt, setDirekt] = useState(true);
  const [neu, setNeu] = useState<QuelleNeu | null>(null);

  const quellen = useQuery({
    queryKey: ["quellen"],
    queryFn: () => api.get<Quelle[]>("/api/quellen"),
  });

  const anlegen = useMutation({
    mutationFn: () =>
      api.post<QuelleNeu>("/api/quellen", { name, kind: art, tickets_direkt: direkt }),
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
        <h2>Verbundene Programme</h2>
      </div>
      <div className="block-inhalt">
        <Erklaerung kurz="Andere Programme, die Beacon etwas schicken dürfen — Protokolle, Tickets, Ereignisse." lang={<>Wer hier eingetragen ist, darf Ereignisse schicken: Insilo ein fertiges
          Besprechungsprotokoll, eine Schnittstelle oder ein Bot ein Ticket. Jede Quelle
          bekommt eine eigene Adresse und ein eigenes Geheimnis; ohne gültige Signatur kommt
          nichts durch.</>} />

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
                <th>Tickets</th>
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
                    <td>{ART_TEXT[q.kind] ?? q.kind}</td>
                    <td style={{ fontSize: "0.8125rem" }}>
                      {q.tickets_direkt ? "legt Tickets an" : "wartet im Eingang"}
                    </td>
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
          <div className="feld" style={{ flex: "2 1 14rem", marginBottom: 0 }}>
            <label htmlFor="quellenname">Name der Quelle</label>
            <input id="quellenname" value={name} onChange={(e) => setName(e.target.value)} />
          </div>
          <div className="feld" style={{ flex: "0 0 12rem", marginBottom: 0 }}>
            <label htmlFor="quellenart">Art</label>
            <select
              id="quellenart"
              value={art}
              onChange={(e) => {
                const a = e.target.value as Quellenart;
                setArt(a);
                // Ein Formular kann kein Geheimnis halten. Was von dort
                // kommt, wartet in der Vorgabe im Eingang.
                setDirekt(a !== "formular");
              }}
            >
              {(Object.keys(ART_TEXT) as Quellenart[]).map((a) => (
                <option key={a} value={a}>
                  {ART_TEXT[a]}
                </option>
              ))}
            </select>
          </div>
          <button type="submit" className="btn btn-primaer" disabled={anlegen.isPending}>
            {anlegen.isPending ? "Legt an …" : "Quelle anlegen"}
          </button>
        </form>

        {art !== "insilo" && (
          <label className="quelle-freigabe">
            <input
              type="checkbox"
              checked={direkt}
              onChange={(e) => setDirekt(e.target.checked)}
            />
            <span>
              Legt Tickets unmittelbar an.
              {" "}
              <span style={{ color: "var(--am-text-gedaempft)" }}>
                Abgeschaltet wartet jede Meldung im Eingang, bis jemand sie ansieht — das ist
                die richtige Einstellung für alles, was aus dem offenen Netz kommt.
              </span>
            </span>
          </label>
        )}
        {anlegen.isError && <Fehler text={(anlegen.error as Error).message} />}
      </div>
    </section>
  );
}
