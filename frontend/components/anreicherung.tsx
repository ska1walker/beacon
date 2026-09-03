"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Sparkles } from "lucide-react";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { anzahl, datumZeit } from "@/lib/format";
import type { Anreicherung, AnreicherungStatus } from "@/lib/typen";
import { Fehler } from "@/components/zustaende";

/** Feldnamen, wie sie am Datensatz heißen. */
const FELD_TEXT: Record<string, string> = {
  website: "Website",
  linkedin_url: "LinkedIn",
  industry: "Branche",
  employee_count: "Mitarbeiter",
  street: "Straße",
  postal_code: "PLZ",
  city: "Ort",
  country: "Land",
  phone: "Telefon",
  mobile: "Mobil",
  email: "E-Mail",
  job_title: "Position",
  description: "Beschreibung",
};

function host(url: string): string {
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return url;
  }
}

/**
 * Was über eine Firma oder Person öffentlich zu finden ist — Website,
 * Suchtreffer, LinkedIn über die Treffer. Leere Felder füllt der Lauf
 * von selbst, wenn das so eingestellt ist; alles andere ist ein
 * Vorschlag mit Quelle, den ein Mensch übernimmt oder verwirft.
 */
export function Anreicherungsblock({
  entity,
  id,
  werte,
  abfrageSchluessel,
}: {
  entity: "companies" | "contacts";
  id: string;
  werte: Record<string, unknown>;
  abfrageSchluessel: unknown[];
}) {
  const client = useQueryClient();
  const [gewaehlt, setGewaehlt] = useState<string[]>([]);

  const status = useQuery({
    queryKey: ["anreicherung-status"],
    queryFn: () => api.get<AnreicherungStatus>("/api/anreicherung/status"),
    staleTime: 5 * 60_000,
  });

  const laeufe = useQuery({
    queryKey: ["anreicherungen", entity, id],
    queryFn: () => api.get<Anreicherung[]>(`/api/anreicherungen?entity=${entity}&entity_id=${id}&limit=3`),
    // Ein Lauf im Hintergrund braucht ein paar Sekunden — solange einer
    // läuft, wird nachgesehen.
    refetchInterval: (q) => (q.state.data?.some((l) => l.status === "laeuft") ? 3000 : false),
  });

  const letzter = laeufe.data?.[0];
  const felder = letzter?.status === "vorschlag" ? Object.entries(letzter.vorschlag) : [];

  useEffect(() => {
    // Vorgabe: Was leer war, ist angehakt. Was abweicht, muss man wollen.
    setGewaehlt(felder.filter(([, v]) => v.lage === "neu").map(([k]) => k));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [letzter?.id, letzter?.status]);

  const frisch = () => {
    client.invalidateQueries({ queryKey: ["anreicherungen", entity, id] });
    client.invalidateQueries({ queryKey: abfrageSchluessel });
    client.invalidateQueries({ queryKey: ["aktivitaeten"] });
  };

  const anreichern = useMutation({
    mutationFn: () => api.post<Anreicherung>(`/api/${entity}/${id}/anreichern`),
    onSuccess: frisch,
  });
  const uebernehmen = useMutation({
    mutationFn: () => api.post<Anreicherung>(`/api/anreicherungen/${letzter!.id}/uebernehmen`, { felder: gewaehlt }),
    onSuccess: frisch,
  });
  const verwerfen = useMutation({
    mutationFn: () => api.post<Anreicherung>(`/api/anreicherungen/${letzter!.id}/verwerfen`),
    onSuccess: frisch,
  });

  const bereit = status.data?.llm_ready ?? false;
  const laeuft = anreichern.isPending || letzter?.status === "laeuft";

  return (
    <section className="block">
      <div className="block-kopf">
        <h2>Aus öffentlichen Quellen</h2>
        <button
          type="button"
          className="btn btn-sekundaer btn-klein"
          onClick={() => anreichern.mutate()}
          disabled={!bereit || laeuft}
          title={bereit ? undefined : status.data?.hint}
        >
          <Sparkles size={14} aria-hidden="true" />
          {laeuft ? "Liest …" : "Anreichern"}
        </button>
      </div>
      <div className="block-inhalt">
        {status.data?.hint && (
          <p style={{ fontSize: "0.8125rem", color: "var(--am-text-gedaempft)", marginBottom: "var(--am-raum-4)" }}>
            {status.data.hint}
          </p>
        )}
        {anreichern.isError && <Fehler text={(anreichern.error as Error).message} />}

        {!letzter && !laeuft && (
          <p style={{ fontSize: "0.875rem", color: "var(--am-text-gedaempft)" }}>
            Noch nichts gelesen.
          </p>
        )}

        {letzter?.status === "laeuft" && (
          <p style={{ fontSize: "0.875rem", color: "var(--am-text-sekundaer)" }}>
            Liest Website und Suchtreffer …
          </p>
        )}

        {letzter && felder.length > 0 && (
          <>
            {/* Eine Liste, keine Tabelle: Der Block sitzt in der schmalen
                linken Spalte, und eine Beschreibung mit drei Sätzen braucht
                die ganze Breite. */}
            <ul style={{ listStyle: "none", margin: "0 0 var(--am-raum-4)", padding: 0, fontSize: "0.875rem" }}>
              {felder.map(([feld, v]) => (
                <li key={feld} style={{ padding: "var(--am-raum-3) 0", borderBottom: "1px solid var(--am-trennlinie)" }}>
                  <label style={{ display: "flex", gap: "var(--am-raum-3)", alignItems: "flex-start", cursor: "pointer" }}>
                    <input
                      type="checkbox"
                      style={{ marginTop: 3 }}
                      aria-label={`${FELD_TEXT[feld] ?? feld} übernehmen`}
                      checked={gewaehlt.includes(feld)}
                      onChange={(ev) =>
                        setGewaehlt((alt) => (ev.target.checked ? [...alt, feld] : alt.filter((f) => f !== feld)))
                      }
                    />
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <div style={{ display: "flex", justifyContent: "space-between", gap: "var(--am-raum-3)" }}>
                        <strong style={{ fontWeight: 600 }}>{FELD_TEXT[feld] ?? feld}</strong>
                        <a
                          href={v.quelle}
                          target="_blank"
                          rel="noreferrer noopener"
                          onClick={(ev) => ev.stopPropagation()}
                          style={{ fontSize: "0.75rem", color: "var(--am-text-gedaempft)", textDecoration: "underline", textUnderlineOffset: "2px", whiteSpace: "nowrap" }}
                        >
                          {host(v.quelle)}
                        </a>
                      </div>
                      {v.lage === "abweichend" && (
                        <div style={{ fontSize: "0.8125rem", color: "var(--am-text-gedaempft)", overflowWrap: "anywhere" }}>
                          Bisher: {String(werte[feld] ?? "—")}
                        </div>
                      )}
                      <div style={{ overflowWrap: "anywhere" }}>
                        {String(v.wert)}
                        {!v.belegt && (
                          <span style={{ marginLeft: "var(--am-raum-2)", fontSize: "0.75rem", color: "var(--am-text-gedaempft)" }}>
                            gefolgert
                          </span>
                        )}
                      </div>
                    </div>
                  </label>
                </li>
              ))}
            </ul>
            {(uebernehmen.isError || verwerfen.isError) && (
              <Fehler text={((uebernehmen.error ?? verwerfen.error) as Error).message} />
            )}
            <div className="btn-reihe">
              <button
                type="button"
                className="btn btn-primaer btn-klein"
                onClick={() => uebernehmen.mutate()}
                disabled={gewaehlt.length === 0 || uebernehmen.isPending}
              >
                {anzahl(gewaehlt.length, "Feld", "Felder")} übernehmen
              </button>
              <button type="button" className="btn btn-still btn-klein" onClick={() => verwerfen.mutate()} disabled={verwerfen.isPending}>
                Verwerfen
              </button>
            </div>
          </>
        )}

        {letzter && letzter.status !== "laeuft" && (
          <p style={{ fontSize: "0.8125rem", color: "var(--am-text-gedaempft)", marginTop: felder.length ? "var(--am-raum-4)" : 0 }}>
            {datumZeit(letzter.updated_at)} ·{" "}
            {Object.keys(letzter.uebernommen).length > 0 && (
              <>
                {anzahl(Object.keys(letzter.uebernommen).length, "Feld", "Felder")} übernommen
                {" ("}
                {Object.keys(letzter.uebernommen).map((f) => FELD_TEXT[f] ?? f).join(", ")}
                {")"}
                {" · "}
              </>
            )}
            {letzter.status === "verworfen" && "Vorschlag verworfen · "}
            {letzter.status === "leer" && "nichts gefunden · "}
            {letzter.status === "fehler" && "fehlgeschlagen · "}
            {anzahl(letzter.quellen.length, "Quelle", "Quellen")} gelesen
            {letzter.modell ? ` · ${letzter.modell}` : ""}
          </p>
        )}
        {letzter?.fehler && (letzter.status === "leer" || letzter.status === "fehler") && (
          <p style={{ fontSize: "0.8125rem", color: "var(--am-text-sekundaer)" }}>{letzter.fehler}</p>
        )}

        {letzter && letzter.quellen.length > 0 && (
          <details style={{ marginTop: "var(--am-raum-3)", fontSize: "0.8125rem" }}>
            <summary style={{ cursor: "pointer", color: "var(--am-text-sekundaer)" }}>Was gelesen wurde</summary>
            <ul style={{ margin: "var(--am-raum-2) 0 0", paddingLeft: "var(--am-raum-5)" }}>
              {letzter.quellen.map((q) => (
                <li key={q.url + (q.anfrage ?? "")}>
                  <a href={q.url} target="_blank" rel="noreferrer noopener" style={{ textDecoration: "underline", textUnderlineOffset: "2px" }}>
                    {q.titel || q.url}
                  </a>
                  <span style={{ color: "var(--am-text-gedaempft)" }}>
                    {" "}· {q.art === "suche" ? `Suchtreffer für „${q.anfrage}"` : `${q.bytes.toLocaleString("de-DE")} Bytes`}
                  </span>
                </li>
              ))}
            </ul>
          </details>
        )}
      </div>
    </section>
  );
}
