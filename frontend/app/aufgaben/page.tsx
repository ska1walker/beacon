"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "@/lib/api";
import { datumZeit } from "@/lib/format";
import type { Task } from "@/lib/typen";
import { Seitenkopf } from "@/components/seitenkopf";
import { Fehler, Laedt, Leer } from "@/components/zustaende";

export default function AufgabenSeite() {
  const client = useQueryClient();
  const [titel, setTitel] = useState("");

  const abfrage = useQuery({
    queryKey: ["aufgaben", "open"],
    queryFn: () => api.get<Task[]>("/api/tasks?status=open"),
  });

  const anlegen = useMutation({
    mutationFn: () => api.post<Task>("/api/tasks", { title: titel }),
    onSuccess: () => {
      setTitel("");
      client.invalidateQueries({ queryKey: ["aufgaben"] });
    },
  });

  const erledigen = useMutation({
    mutationFn: (id: string) => api.patch<Task>(`/api/tasks/${id}`, { status: "done" }),
    onSuccess: () => client.invalidateQueries({ queryKey: ["aufgaben"] }),
  });

  return (
    <>
      <Seitenkopf titel="Aufgaben" zahl={abfrage.data ? `${abfrage.data.length} offen` : undefined} />

      <div className="werkzeugleiste">
        <form
          style={{ display: "flex", gap: "var(--am-raum-2)", flex: "1 1 320px" }}
          onSubmit={(e) => {
            e.preventDefault();
            if (titel.trim()) anlegen.mutate();
          }}
        >
          <input
            className="input"
            value={titel}
            onChange={(e) => setTitel(e.target.value)}
            placeholder="Was ist zu tun?"
            aria-label="Neue Aufgabe"
          />
          <button type="submit" className="btn btn-primaer" disabled={!titel.trim()}>
            Anlegen
          </button>
        </form>
      </div>

      <div className="liste">
        {abfrage.isPending && <Laedt />}
        {abfrage.isError && <Fehler text={(abfrage.error as Error).message} />}
        {abfrage.data?.length === 0 && <Leer titel="Nichts offen" text="Alles abgearbeitet." />}
        {abfrage.data && abfrage.data.length > 0 && (
          <table className="tabelle">
            <thead>
              <tr>
                <th style={{ width: "3rem" }}>
                  <span className="nur-vorleser">Erledigt</span>
                </th>
                <th>Aufgabe</th>
                <th>Fällig</th>
              </tr>
            </thead>
            <tbody>
              {abfrage.data.map((a) => (
                <tr key={a.id}>
                  <td>
                    <input
                      type="checkbox"
                      aria-label={`„${a.title}" erledigt`}
                      onChange={() => erledigen.mutate(a.id)}
                      checked={false}
                    />
                  </td>
                  <td className="haupt">{a.title}</td>
                  <td>{a.due_at ? datumZeit(a.due_at) : "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </>
  );
}
