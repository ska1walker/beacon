"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { api, suchparameter } from "@/lib/api";
import { datum } from "@/lib/format";
import type {
  Eigenschaftsoption,
  Eigenschaftswert,
  Eigenschaftswerte,
  PropertyDefinition,
  PropertyEntity,
} from "@/lib/typen";
import { Mehrfachauswahl } from "@/components/mehrfachauswahl";
import { Fehler } from "@/components/zustaende";

/**
 * Die eigenen Eigenschaften eines Datensatzes — anzeigen und ändern.
 *
 * Gespeichert wird nur, was geändert wurde: Das Backend führt zusammen,
 * statt zu ersetzen. Ein leeres Feld schickt `null` und löscht damit den
 * Wert — anders bekommt man eine Eigenschaft nicht wieder leer. Für eine
 * Mehrfachauswahl heißt „leer" die leere Liste, und die wird beim
 * Speichern ebenfalls zu `null`: Sonst stünde im JSON ein `[]`, das „ist
 * leer" nicht als leer gelten ließe.
 */
export function Eigenschaftswerteblock({
  entity,
  id,
  werte,
  abfrageSchluessel,
}: {
  entity: PropertyEntity;
  id: string;
  werte: Eigenschaftswerte;
  abfrageSchluessel: unknown[];
}) {
  const client = useQueryClient();
  const [entwurf, setEntwurf] = useState<Record<string, string | string[]>>({});
  const [geaendert, setGeaendert] = useState<Set<string>>(new Set());

  const definitionen = useQuery({
    queryKey: ["eigenschaften", entity],
    queryFn: () =>
      api.get<PropertyDefinition[]>(`/api/eigenschaften${suchparameter({ entity })}`),
  });

  useEffect(() => {
    if (geaendert.size === 0) {
      setEntwurf(
        Object.fromEntries(
          Object.entries(werte).map(([k, v]) => [
            k,
            Array.isArray(v) ? v : v === null || v === undefined ? "" : String(v),
          ]),
        ),
      );
    }
  }, [werte, geaendert.size]);

  const pfad = { companies: "companies", contacts: "contacts", deals: "deals" }[entity];

  const speichern = useMutation({
    mutationFn: () => {
      const custom: Eigenschaftswerte = {};
      for (const key of geaendert) {
        const d = definitionen.data?.find((x) => x.key === key);
        const roh = entwurf[key] ?? "";
        if (d?.kind === "multiselect") {
          custom[key] = Array.isArray(roh) && roh.length > 0 ? roh : null;
        } else if (roh === "") custom[key] = null;
        else if (d?.kind === "bool") custom[key] = roh === "true";
        else if (d?.kind === "number") custom[key] = Number(roh);
        else custom[key] = String(roh);
      }
      return api.patch(`/api/${pfad}/${id}`, { custom });
    },
    onSuccess: () => {
      setGeaendert(new Set());
      client.invalidateQueries({ queryKey: abfrageSchluessel });
    },
  });

  const defs = definitionen.data ?? [];
  // Werte zu abgeschalteten Definitionen bleiben lesbar — sie sind nicht weg.
  const verwaist = Object.entries(werte).filter(
    ([k, v]) => v !== null && v !== "" && !defs.some((d) => d.key === k),
  );
  if (defs.length === 0 && verwaist.length === 0) return null;

  function setze(key: string, wert: string | string[]) {
    setEntwurf((alt) => ({ ...alt, [key]: wert }));
    setGeaendert((alt) => new Set(alt).add(key));
  }

  function text(key: string): string {
    const w = entwurf[key];
    return typeof w === "string" ? w : "";
  }

  return (
    <section className="block">
      <div className="block-kopf">
        <h2>Weitere Eigenschaften</h2>
      </div>
      <div className="block-inhalt">
        {defs.map((d) => (
          <div className="feld" key={d.key}>
            <label htmlFor={`eig-${d.key}`}>{d.label}</label>
            {d.kind === "bool" ? (
              <select id={`eig-${d.key}`} value={text(d.key)} onChange={(e) => setze(d.key, e.target.value)}>
                <option value="">—</option>
                <option value="true">Ja</option>
                <option value="false">Nein</option>
              </select>
            ) : d.kind === "select" ? (
              <select id={`eig-${d.key}`} value={text(d.key)} onChange={(e) => setze(d.key, e.target.value)}>
                <option value="">—</option>
                {waehlbar(d.options, text(d.key)).map((o) => (
                  <option key={o.wert} value={o.wert}>{o.text}</option>
                ))}
              </select>
            ) : d.kind === "multiselect" ? (
              <Mehrfachauswahl
                id={`eig-${d.key}`}
                ariaLabel={d.label}
                optionen={waehlbar(d.options, entwurf[d.key])}
                gewaehlt={Array.isArray(entwurf[d.key]) ? (entwurf[d.key] as string[]) : []}
                beiAendern={(neu) => setze(d.key, neu)}
              />
            ) : (
              <input
                id={`eig-${d.key}`}
                type={d.kind === "number" ? "number" : d.kind === "date" ? "date" : "text"}
                step={d.kind === "number" ? "any" : undefined}
                value={text(d.key)}
                onChange={(e) => setze(d.key, e.target.value)}
              />
            )}
            {d.description && <p className="feld-hinweis">{d.description}</p>}
          </div>
        ))}

        {verwaist.length > 0 && (
          <dl style={{ marginTop: "var(--am-raum-2)" }}>
            {verwaist.map(([k, v]) => (
              <div className="eigenschaft" key={k}>
                <dt>{k} <span className="optional">abgeschaltet</span></dt>
                <dd>{lesbar(v)}</dd>
              </div>
            ))}
          </dl>
        )}

        {speichern.isError && <Fehler text={(speichern.error as Error).message} />}
        {geaendert.size > 0 && (
          <div className="btn-reihe">
            <button type="button" className="btn btn-primaer btn-klein" onClick={() => speichern.mutate()} disabled={speichern.isPending}>
              {speichern.isPending ? "Speichert …" : "Speichern"}
            </button>
            <button type="button" className="btn btn-still btn-klein" onClick={() => setGeaendert(new Set())}>
              Verwerfen
            </button>
          </div>
        )}
      </div>
    </section>
  );
}

/**
 * Welche Optionen zur Wahl stehen.
 *
 * Archivierte fallen weg — außer sie stehen schon an diesem Datensatz.
 * Sonst verschwände der eingetragene Wert wortlos aus dem Feld, und der
 * nächste Speichervorgang nähme ihn mit.
 */
function waehlbar(
  optionen: Eigenschaftsoption[],
  gesetzt: string | string[] | undefined,
): { wert: string; text: string }[] {
  const drin = new Set(Array.isArray(gesetzt) ? gesetzt : gesetzt ? [gesetzt] : []);
  return optionen
    .filter((o) => !o.verborgen || drin.has(o.wert))
    .map((o) => ({ wert: o.wert, text: o.verborgen ? `${o.text} (archiviert)` : o.text }));
}

/** Ein gespeicherter Wert, wie ein Mensch ihn liest. */
function lesbar(v: Eigenschaftswert): string {
  if (Array.isArray(v)) return v.join(", ");
  if (typeof v === "boolean") return v ? "Ja" : "Nein";
  if (/^\d{4}-\d{2}-\d{2}$/.test(String(v))) return datum(String(v));
  return String(v);
}
