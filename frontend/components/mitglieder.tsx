"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "@/lib/api";
import { datumZeit } from "@/lib/format";
import type { Mitglied, Wer } from "@/lib/typen";
import { Fehler, Laedt } from "@/components/zustaende";

export function Mitgliederblock() {
  const client = useQueryClient();
  const [name, setName] = useState("");

  const mitglieder = useQuery({
    queryKey: ["mitglieder"],
    queryFn: () => api.get<Mitglied[]>("/api/mitglieder"),
  });

  const wer = useQuery({
    queryKey: ["wer"],
    queryFn: () => api.get<Wer>("/api/mitglieder/wer"),
  });

  const anlegen = useMutation({
    mutationFn: () => api.post<Mitglied>("/api/mitglieder", { display_name: name }),
    onSuccess: () => {
      setName("");
      client.invalidateQueries({ queryKey: ["mitglieder"] });
    },
  });

  const entfernen = useMutation({
    mutationFn: (id: string) => api.del(`/api/mitglieder/${id}`),
    onSuccess: () => client.invalidateQueries({ queryKey: ["mitglieder"] }),
  });

  if (mitglieder.isPending) return <Laedt />;

  return (
    <section className="block">
      <div className="block-kopf">
        <h2>Wer hier arbeitet</h2>
        {wer.data && (
          <span style={{ fontSize: "0.75rem", color: "var(--am-text-gedaempft)" }}>
            Zugang: {wer.data.login_username}
          </span>
        )}
      </div>
      <div className="block-inhalt">
        <p style={{ fontSize: "0.875rem", color: "var(--am-text-sekundaer)", marginBottom: "var(--am-raum-4)" }}>
          Olares installiert Apps pro Nutzer und lässt an einem Zugang keinen zweiten
          Menschen zusätzlich herein. Wer zu zweit dasselbe CRM benutzt, teilt deshalb einen
          Olares-Zugang — und aicrm unterscheidet die Personen selbst.
        </p>
        <div className="hinweis" data-art="achtung" style={{ marginBottom: "var(--am-raum-4)" }}>
          <span>
            Der Sitzplatz ist <strong>Zuschreibung, keine Anmeldung.</strong> Wer den
            geteilten Zugang hat, kann jeden Platz wählen. Er entscheidet, wem Besitz,
            Zuordnung und Protokolleinträge zugeschrieben werden — nicht, wer hereinkommt.
            Das Protokoll hält beides fest: die Person und den Zugang.
          </span>
        </div>

        <table className="tabelle" style={{ marginBottom: "var(--am-raum-4)" }}>
          <thead>
            <tr>
              <th>Person</th>
              <th>Kennung</th>
              <th>Art</th>
              <th>Zuletzt gesehen</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {mitglieder.data!.map((m) => (
              <tr key={m.id} style={{ cursor: "default" }}>
                <td className="haupt">{m.display_name ?? m.olares_username}</td>
                <td className="mono" style={{ fontSize: "0.8125rem" }}>
                  {m.olares_username}
                </td>
                <td>
                  <span className="stufe" data-art={m.zugang === "olares" ? "won" : undefined}>
                    {m.zugang === "olares" ? "eigener Zugang" : "Sitzplatz"}
                  </span>
                </td>
                <td>{m.last_seen_at ? datumZeit(m.last_seen_at) : "—"}</td>
                <td style={{ textAlign: "right" }}>
                  {m.zugang === "sitzplatz" && m.id !== wer.data?.user_id && (
                    <button
                      type="button"
                      className="btn btn-still btn-klein"
                      onClick={() => entfernen.mutate(m.id)}
                    >
                      Entfernen
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>

        {entfernen.isError && <Fehler text={(entfernen.error as Error).message} />}

        <form
          style={{ display: "flex", gap: "var(--am-raum-2)", alignItems: "flex-end" }}
          onSubmit={(e) => {
            e.preventDefault();
            if (name.trim().length >= 2) anlegen.mutate();
          }}
        >
          <div className="feld" style={{ flex: 1, marginBottom: 0 }}>
            <label htmlFor="mitgliedname">Person hinzufügen</label>
            <input
              id="mitgliedname"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="Marc Bayer"
            />
            <p className="feld-hinweis">
              Bekommt sie später einen eigenen Olares-Zugang mit derselben Kennung, wird aus
              dem Sitzplatz automatisch eine angemeldete Person — Besitz und Protokoll bleiben,
              wie sie sind.
            </p>
          </div>
          <button
            type="submit"
            className="btn btn-primaer"
            disabled={name.trim().length < 2 || anlegen.isPending}
          >
            {anlegen.isPending ? "Legt an …" : "Hinzufügen"}
          </button>
        </form>
        {anlegen.isError && <Fehler text={(anlegen.error as Error).message} />}

        <p style={{ fontSize: "0.75rem", color: "var(--am-text-gedaempft)", marginTop: "var(--am-raum-3)" }}>
          Beide sehen und ändern alles. Besitz ist Arbeitsteilung, keine Schranke.
        </p>
      </div>
    </section>
  );
}
