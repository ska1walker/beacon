"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus, X } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { api } from "@/lib/api";
import type { Beteiligter, Contact } from "@/lib/typen";
import { Fehler, Laedt } from "@/components/zustaende";

/**
 * Wer an diesem Lead beteiligt ist.
 *
 * Ein Lead entsteht oft vor allem anderen — ein Anruf, eine Anfrage über
 * das Formular, ein Gespräch auf einer Messe. Firma und Ansprechpartner
 * stehen dann noch nicht fest, und sie später einzutragen ist der
 * Normalfall, nicht die Ausnahme.
 *
 * Die Rolle steht frei daneben, statt aus einer Liste zu kommen: Wer
 * „Entscheider", „Fachliche Prüfung" oder „Bremst" schreibt, weiß besser
 * als ein Vorgabewert, was gemeint ist.
 */
export function Beteiligtenblock({ dealId }: { dealId: string }) {
  const client = useQueryClient();
  const [offen, setOffen] = useState(false);
  const [kontakt, setKontakt] = useState("");
  const [rolle, setRolle] = useState("");

  const beteiligte = useQuery({
    queryKey: ["beteiligte", dealId],
    queryFn: () => api.get<Beteiligter[]>(`/api/deals/${dealId}/beteiligte`),
  });

  const kontakte = useQuery({
    enabled: offen,
    queryKey: ["kontakte-auswahl"],
    queryFn: () => api.get<Contact[]>("/api/contacts?limit=200"),
  });

  const frisch = () => {
    client.invalidateQueries({ queryKey: ["beteiligte", dealId] });
    // Der erste Beteiligte kann die Firma an den Lead vererben.
    client.invalidateQueries({ queryKey: ["deal", dealId] });
  };

  const hinzu = useMutation({
    mutationFn: () =>
      api.post<Beteiligter[]>(`/api/deals/${dealId}/beteiligte`, {
        contact_id: kontakt,
        role: rolle.trim() || null,
      }),
    onSuccess: () => {
      setKontakt("");
      setRolle("");
      setOffen(false);
      frisch();
    },
  });

  const weg = useMutation({
    mutationFn: (id: string) => api.del(`/api/deals/${dealId}/beteiligte/${id}`),
    onSuccess: frisch,
  });

  const schonDrin = new Set((beteiligte.data ?? []).map((b) => b.contact_id));
  const waehlbar = (kontakte.data ?? []).filter((k) => !schonDrin.has(k.id));

  return (
    <section className="block">
      <div className="block-kopf">
        <h2>Beteiligte</h2>
        <button
          type="button"
          className="btn btn-still btn-klein"
          aria-expanded={offen}
          onClick={() => setOffen((o) => !o)}
        >
          <Plus size={14} aria-hidden="true" />
          Kontakt
        </button>
      </div>
      <div className="block-inhalt">
        {beteiligte.isPending && <Laedt />}
        {beteiligte.isError && <Fehler text={(beteiligte.error as Error).message} />}

        {beteiligte.data?.length === 0 && !offen && (
          <p className="feld-hinweis" style={{ margin: 0 }}>
            Noch niemand zugeordnet. Das ist bei einem frischen Lead normal — nachtragen lässt
            es sich jederzeit.
          </p>
        )}

        {(beteiligte.data?.length ?? 0) > 0 && (
          <ul className="beteiligtenliste">
            {beteiligte.data?.map((b) => (
              <li key={b.contact_id}>
                <div className="beteiligter-text">
                  <Link href={`/kontakte/${b.contact_id}`} className="zellen-link">
                    {b.name || "Kontakt"}
                  </Link>
                  <span>
                    {[b.role, b.job_title, b.company_name].filter(Boolean).join(" · ") || "—"}
                  </span>
                </div>
                {b.email && (
                  <a href={`mailto:${b.email}`} className="zellen-link beteiligter-mail">
                    {b.email}
                  </a>
                )}
                <button
                  type="button"
                  className="btn btn-still btn-klein"
                  aria-label={`${b.name} lösen`}
                  title="Verknüpfung lösen — der Kontakt bleibt bestehen"
                  disabled={weg.isPending}
                  onClick={() => weg.mutate(b.contact_id)}
                >
                  <X size={14} aria-hidden="true" />
                </button>
              </li>
            ))}
          </ul>
        )}

        {offen && (
          <form
            className="beteiligter-neu"
            onSubmit={(e) => {
              e.preventDefault();
              if (kontakt) hinzu.mutate();
            }}
          >
            <select
              value={kontakt}
              onChange={(e) => setKontakt(e.target.value)}
              aria-label="Kontakt"
            >
              <option value="">— wählen —</option>
              {waehlbar.map((k) => (
                <option key={k.id} value={k.id}>
                  {[k.first_name, k.last_name].filter(Boolean).join(" ") || k.email || "Kontakt"}
                  {k.company_name ? ` · ${k.company_name}` : ""}
                </option>
              ))}
            </select>
            <input
              value={rolle}
              onChange={(e) => setRolle(e.target.value)}
              placeholder="Rolle, etwa Entscheiderin"
              aria-label="Rolle"
            />
            <button
              type="submit"
              className="btn btn-primaer btn-klein"
              disabled={!kontakt || hinzu.isPending}
            >
              {hinzu.isPending ? "Fügt hinzu …" : "Hinzufügen"}
            </button>
          </form>
        )}
        {weg.isError && <Fehler text={(weg.error as Error).message} />}
        {hinzu.isError && <Fehler text={(hinzu.error as Error).message} />}
      </div>
    </section>
  );
}
