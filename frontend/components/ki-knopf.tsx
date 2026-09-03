"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Sparkles } from "lucide-react";
import { api } from "@/lib/api";
import type { KIErgebnis, KIStatus } from "@/lib/typen";

/**
 * Löst eine Modellanfrage aus. Ist kein Endpunkt eingerichtet, ist der
 * Knopf gesperrt und sagt warum — statt in einen Verbindungsfehler zu
 * laufen, den niemand deuten kann.
 */
export function KiKnopf({
  pfad,
  text,
  invalidiert,
}: {
  pfad: string;
  text: string;
  invalidiert: unknown[];
}) {
  const client = useQueryClient();

  const status = useQuery({
    queryKey: ["ki-status"],
    queryFn: () => api.get<KIStatus>("/api/ki/status"),
    staleTime: 5 * 60_000,
  });

  const lauf = useMutation({
    mutationFn: () => api.post<KIErgebnis>(pfad),
    onSuccess: () => {
      client.invalidateQueries({ queryKey: invalidiert });
      client.invalidateQueries({ queryKey: ["aktivitaeten"] });
    },
  });

  const bereit = status.data?.ready ?? false;

  return (
    <>
      <button
        type="button"
        className="btn btn-sekundaer btn-klein"
        onClick={() => lauf.mutate()}
        disabled={!bereit || lauf.isPending}
        title={bereit ? undefined : status.data?.hint}
      >
        <Sparkles size={14} aria-hidden="true" />
        {lauf.isPending ? "Denkt nach …" : text}
      </button>
      {!bereit && status.data?.hint && (
        <span style={{ fontSize: "0.75rem", color: "var(--am-text-gedaempft)" }}>
          {status.data.hint}
        </span>
      )}
      {lauf.isError && (
        <span style={{ fontSize: "0.75rem", color: "var(--am-fehler)" }}>
          {(lauf.error as Error).message}
        </span>
      )}
    </>
  );
}
