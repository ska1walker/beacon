"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Pencil, Sparkles, Trash2 } from "lucide-react";
import { useState } from "react";
import { api, suchparameter } from "@/lib/api";
import { AKTIVITAET_TEXT, datumZeit } from "@/lib/format";
import type { Activity, ActivityKind } from "@/lib/typen";
import { Fehler, Laedt, Leer } from "@/components/zustaende";

const ARTEN: ActivityKind[] = ["note", "call", "email", "meeting"];

export function Zeitleiste({
  bezug,
}: {
  bezug: { company_id?: string; contact_id?: string; deal_id?: string };
}) {
  const client = useQueryClient();
  const schluessel = ["aktivitaeten", bezug];
  const [text, setText] = useState("");
  const [art, setArt] = useState<ActivityKind>("note");
  const [bearbeite, setBearbeite] = useState<{ id: string; body: string } | null>(null);
  const MENSCHLICH: ActivityKind[] = ["note", "call", "email", "meeting", "task"];

  const aendern = useMutation({
    mutationFn: ({ id, body }: { id: string; body: string }) => api.patch(`/api/activities/${id}`, { body }),
    onSuccess: () => { setBearbeite(null); client.invalidateQueries({ queryKey: schluessel }); },
  });
  const zuruecknehmen = useMutation({
    mutationFn: (id: string) => api.del(`/api/activities/${id}`),
    onSuccess: () => client.invalidateQueries({ queryKey: schluessel }),
  });

  const abfrage = useQuery({
    queryKey: schluessel,
    queryFn: () => api.get<Activity[]>(`/api/activities${suchparameter(bezug)}`),
  });

  const anlegen = useMutation({
    mutationFn: (eingabe: { kind: ActivityKind; body: string }) =>
      api.post<Activity>("/api/activities", { ...bezug, ...eingabe }),
    onSuccess: () => {
      setText("");
      client.invalidateQueries({ queryKey: schluessel });
    },
  });

  return (
    <section className="block">
      <div className="block-kopf">
        <h2>Verlauf</h2>
      </div>

      <div className="block-inhalt">
        <form
          className="notiz-feld"
          onSubmit={(e) => {
            e.preventDefault();
            if (text.trim()) anlegen.mutate({ kind: art, body: text.trim() });
          }}
        >
          <textarea
            value={text}
            onChange={(e) => setText(e.target.value)}
            placeholder="Was ist passiert? Notiz, Telefonat, Termin …"
            aria-label="Neue Aktivität"
          />
          <div className="btn-reihe" style={{ marginTop: "var(--am-raum-2)" }}>
            <select
              value={art}
              onChange={(e) => setArt(e.target.value as ActivityKind)}
              aria-label="Art der Aktivität"
              className="input"
              style={{ width: "auto" }}
            >
              {ARTEN.map((a) => (
                <option key={a} value={a}>
                  {AKTIVITAET_TEXT[a]}
                </option>
              ))}
            </select>
            <button
              type="submit"
              className="btn btn-primaer btn-klein"
              disabled={!text.trim() || anlegen.isPending}
            >
              {anlegen.isPending ? "Wird gespeichert …" : "Festhalten"}
            </button>
          </div>
          {anlegen.isError && <Fehler text={(anlegen.error as Error).message} />}
        </form>

        <div style={{ marginTop: "var(--am-raum-6)" }}>
          {abfrage.isPending && <Laedt />}
          {abfrage.isError && <Fehler text={(abfrage.error as Error).message} />}
          {abfrage.data?.length === 0 && (
            <Leer titel="Noch nichts festgehalten" text="Die erste Notiz steht oben." />
          )}
          {abfrage.data && abfrage.data.length > 0 && (
            <ul className="zeitleiste">
              {abfrage.data.map((a) => (
                <li key={a.id} data-art={a.kind}>
                  <div className="zeitleiste-kopf">
                    <span className="zeitleiste-art">
                      {a.kind === "ai" && <Sparkles size={11} aria-hidden="true" />}{" "}
                      {AKTIVITAET_TEXT[a.kind] ?? a.kind}
                    </span>
                    {a.subject && <span className="zeitleiste-betreff">{a.subject}</span>}
                    <span className="zeitleiste-zeit">{datumZeit(a.occurred_at)}</span>
                  </div>
                  {bearbeite?.id === a.id ? (
                    <div className="notiz-feld">
                      <textarea rows={3} value={bearbeite.body} onChange={(e) => setBearbeite({ id: a.id, body: e.target.value })} aria-label="Eintrag bearbeiten" />
                      <div className="btn-reihe" style={{ marginTop: "var(--am-raum-2)" }}>
                        <button type="button" className="btn btn-primaer btn-klein" onClick={() => aendern.mutate(bearbeite)} disabled={aendern.isPending}>Speichern</button>
                        <button type="button" className="btn btn-still btn-klein" onClick={() => setBearbeite(null)}>Abbrechen</button>
                      </div>
                    </div>
                  ) : (
                    a.body && <p className="zeitleiste-text">{a.body}</p>
                  )}
                  {MENSCHLICH.includes(a.kind) && bearbeite?.id !== a.id && (
                    <div className="btn-reihe" style={{ marginTop: "var(--am-raum-1)" }}>
                      <button type="button" className="btn btn-still btn-klein" aria-label="Eintrag bearbeiten" onClick={() => setBearbeite({ id: a.id, body: a.body ?? "" })}><Pencil size={12} aria-hidden="true" /></button>
                      <button type="button" className="btn btn-still btn-klein" aria-label="Eintrag zurücknehmen" onClick={() => zuruecknehmen.mutate(a.id)}><Trash2 size={12} aria-hidden="true" /></button>
                    </div>
                  )}
                  {a.kind === "ai" && typeof a.payload?.modell === "string" && (
                    <p className="zeitleiste-text" style={{ color: "var(--am-text-deaktiviert)" }}>
                      Modell: {a.payload.modell}
                    </p>
                  )}
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
    </section>
  );
}
