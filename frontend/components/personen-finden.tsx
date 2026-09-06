"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Search, Users } from "lucide-react";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { Contact, Personenliste, Personenvorschlag } from "@/lib/typen";
import { Fehler } from "@/components/zustaende";

/**
 * Ansprechpartner finden — wer bei dieser Firma genannt wird, als Wahl.
 *
 * Zwei Orte, ein Bauteil: Im Anlegen-Dialog der Firma läuft es von selbst
 * an, sobald eine Firma gewählt ist, und gibt die Auswahl nach oben; die
 * Kontakte entstehen dann mit der Firma. Auf der Firmenseite legt es die
 * gewählten Personen direkt an. Gefunden ist nur, wer mit Nachnamen in
 * einer Quelle steht; E-Mail und Telefon nur wörtlich.
 */
export function PersonenFinden({
  firma,
  firmaId,
  vonSelbst = false,
  beiAuswahl,
  vorhanden,
}: {
  firma: { name: string; website: string | null };
  /** Auf der Firmenseite: die gewählten Personen werden hier angelegt. */
  firmaId?: string;
  /** Im Anlegen-Dialog: sofort suchen, ohne Knopf. */
  vonSelbst?: boolean;
  /** Im Anlegen-Dialog: die Auswahl geht nach oben, angelegt wird mit der Firma. */
  beiAuswahl?: (personen: Personenvorschlag[]) => void;
  /** Wer schon als Kontakt da ist — wird gezeigt, aber nicht noch einmal angelegt. */
  vorhanden?: { first_name: string | null; last_name: string | null }[];
}) {
  const client = useQueryClient();
  const [wunsch, setWunsch] = useState("");
  const [gewaehlt, setGewaehlt] = useState<Set<string>>(new Set());
  const [angelegt, setAngelegt] = useState<number | null>(null);

  const suchen = useMutation({
    mutationFn: () =>
      api.post<Personenliste>("/api/finden/personen", {
        firma: { name: firma.name, website: firma.website || `https://${firma.name}` },
        wunsch: wunsch.trim() || undefined,
      }),
    onSuccess: (d) => {
      // Vorausgewählt ist, wer eine Rolle trägt und noch nicht da ist.
      const alle = new Set(d.personen.filter((p) => p.job_title && !schonDa(p)).map(schluessel));
      setGewaehlt(alle);
      setAngelegt(null);
    },
  });

  const anlegen = useMutation({
    mutationFn: async (personen: Personenvorschlag[]) => {
      let n = 0;
      for (const p of personen) {
        await api.post<Contact>("/api/contacts", {
          first_name: p.first_name || null,
          last_name: p.last_name,
          job_title: p.job_title || null,
          email: p.email ?? null,
          phone: p.phone ?? null,
          mobile: p.mobile ?? null,
          linkedin_url: p.linkedin_url ?? null,
          company_id: firmaId,
          source: "Recherche",
        });
        n += 1;
      }
      return n;
    },
    onSuccess: (n) => {
      setAngelegt(n);
      setGewaehlt(new Set());
      client.invalidateQueries({ queryKey: ["firma-kontakte", firmaId] });
      client.invalidateQueries({ queryKey: ["segment", "contacts"] });
    },
  });

  const daSchluessel = new Set((vorhanden ?? []).map((k) => `${k.first_name ?? ""}|${k.last_name ?? ""}`.toLowerCase()));
  function schonDa(p: Personenvorschlag): boolean {
    return daSchluessel.has(schluessel(p));
  }

  const auto = vonSelbst && !suchen.data && !suchen.isPending && !suchen.isError;
  useEffect(() => {
    if (auto) suchen.mutate();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [auto, firma.name, firma.website]);

  const personen = suchen.data?.personen ?? [];
  const auswahl = personen.filter((p) => gewaehlt.has(schluessel(p)));

  useEffect(() => {
    beiAuswahl?.(auswahl);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [gewaehlt, suchen.data]);

  function umschalten(p: Personenvorschlag) {
    setGewaehlt((g) => {
      const n = new Set(g);
      const k = schluessel(p);
      if (n.has(k)) n.delete(k);
      else n.add(k);
      return n;
    });
  }

  return (
    <div className="personen-finden">
      <div className="erfassung-leiste" style={{ marginTop: 0 }}>
        <Users size={14} aria-hidden="true" style={{ color: "var(--am-gold-beschriftung)", flex: "none" }} />
        <input
          className="input"
          value={wunsch}
          onChange={(e) => setWunsch(e.target.value)}
          placeholder="Wen suchen Sie? z. B. Einkauf, Geschäftsführung — leer heißt alle"
          aria-label="Gesuchte Rolle"
          style={{ flex: 1, minWidth: "12rem" }}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault();
              suchen.mutate();
            }
          }}
        />
        <button type="button" className="btn btn-sekundaer btn-klein" disabled={suchen.isPending} onClick={() => suchen.mutate()}>
          <Search size={14} aria-hidden="true" />
          {suchen.isPending ? "Sucht …" : suchen.data ? "Erneut suchen" : "Personen suchen"}
        </button>
      </div>

      {suchen.isPending && (
        <p className="erfassung-hinweis">Liest Team-, Kontakt- und Impressumsseite und die Suchtreffer — bis zu einer Minute.</p>
      )}
      {suchen.isError && <Fehler text={(suchen.error as Error).message} />}
      {anlegen.isError && <Fehler text={(anlegen.error as Error).message} />}

      {suchen.data && personen.length > 0 && (
        <ul className="finden-personen">
          {personen.map((p) => {
            const k = schluessel(p);
            const da = schonDa(p);
            const an = !da && gewaehlt.has(k);
            return (
              <li key={k}>
                <label className={`finden-person${an ? " aktiv" : ""}${da ? " schon-da" : ""}`}>
                  <input type="checkbox" checked={an} disabled={da} onChange={() => umschalten(p)} aria-label={`${p.first_name} ${p.last_name} übernehmen`} />
                  <span className="finden-kandidat-name">{[p.first_name, p.last_name].filter(Boolean).join(" ")}{da && <span className="stufe" style={{ marginLeft: "var(--am-raum-2)" }}>schon im Bestand</span>}</span>
                  <span className="finden-kandidat-unter">
                    {[p.job_title, p.email, p.phone].filter(Boolean).join(" · ")}
                    {" — "}
                    <a href={p.quelle} target="_blank" rel="noreferrer noopener">{host(p.quelle)}</a>
                  </span>
                </label>
              </li>
            );
          })}
        </ul>
      )}
      {suchen.data?.hinweise.map((h) => (
        <p key={h} className="erfassung-hinweis warnung">{h}</p>
      ))}

      {suchen.data && personen.length > 0 && (
        <div className="erfassung-leiste">
          {firmaId ? (
            <button type="button" className="btn btn-primaer btn-klein" disabled={auswahl.length === 0 || anlegen.isPending} onClick={() => anlegen.mutate(auswahl)}>
              {anlegen.isPending ? "Legt an …" : auswahl.length <= 1 ? "Als Kontakt anlegen" : `${auswahl.length} als Kontakte anlegen`}
            </button>
          ) : (
            <span className="erfassung-tipp">
              {auswahl.length === 0 ? "Niemand gewählt" : auswahl.length === 1 ? "Eine Person wird mit der Firma angelegt" : `${auswahl.length} Personen werden mit der Firma angelegt`}
            </span>
          )}
          {angelegt !== null && <span className="erfassung-tipp">{angelegt === 1 ? "Ein Kontakt angelegt." : `${angelegt} Kontakte angelegt.`}</span>}
        </div>
      )}
    </div>
  );
}

function schluessel(p: Personenvorschlag): string {
  return `${p.first_name}|${p.last_name}`.toLowerCase();
}

function host(url: string): string {
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return url;
  }
}
