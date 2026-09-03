"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Sparkles } from "lucide-react";
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
                  {a.body && <p className="zeitleiste-text">{a.body}</p>}
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
