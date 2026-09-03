"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { api, suchparameter } from "@/lib/api";
import { datum } from "@/lib/format";
import type { Eigenschaftswerte, PropertyDefinition, PropertyEntity } from "@/lib/typen";
import { Fehler } from "@/components/zustaende";

/**
 * Die eigenen Eigenschaften eines Datensatzes — anzeigen und ändern.
 *
 * Gespeichert wird nur, was geändert wurde: Das Backend führt zusammen,
 * statt zu ersetzen. Ein leeres Feld schickt `null` und löscht damit den
 * Wert — anders bekommt man eine Eigenschaft nicht wieder leer.
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
  const [entwurf, setEntwurf] = useState<Record<string, string>>({});
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
          Object.entries(werte).map(([k, v]) => [k, v === null || v === undefined ? "" : String(v)]),
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
        if (roh === "") custom[key] = null;
        else if (d?.kind === "bool") custom[key] = roh === "true";
        else if (d?.kind === "number") custom[key] = Number(roh);
        else custom[key] = roh;
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

  function setze(key: string, wert: string) {
    setEntwurf((alt) => ({ ...alt, [key]: wert }));
    setGeaendert((alt) => new Set(alt).add(key));
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
              <select id={`eig-${d.key}`} value={entwurf[d.key] ?? ""} onChange={(e) => setze(d.key, e.target.value)}>
                <option value="">—</option>
                <option value="true">Ja</option>
                <option value="false">Nein</option>
              </select>
            ) : d.kind === "select" ? (
              <select id={`eig-${d.key}`} value={entwurf[d.key] ?? ""} onChange={(e) => setze(d.key, e.target.value)}>
                <option value="">—</option>
                {d.options.map((o) => (
                  <option key={o} value={o}>{o}</option>
                ))}
              </select>
            ) : (
              <input
                id={`eig-${d.key}`}
                type={d.kind === "number" ? "number" : d.kind === "date" ? "date" : "text"}
                step={d.kind === "number" ? "any" : undefined}
                value={entwurf[d.key] ?? ""}
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
                <dd>{typeof v === "boolean" ? (v ? "Ja" : "Nein") : /^\d{4}-\d{2}-\d{2}$/.test(String(v)) ? datum(String(v)) : String(v)}</dd>
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
