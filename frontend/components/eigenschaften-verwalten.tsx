"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api, suchparameter } from "@/lib/api";
import type { PropertyDefinition, PropertyEntity, PropertyKind } from "@/lib/typen";
import { Fehler, Laedt } from "@/components/zustaende";

const OBJEKTE: { wert: PropertyEntity; text: string }[] = [
  { wert: "companies", text: "Firmen" },
  { wert: "contacts", text: "Kontakte" },
  { wert: "deals", text: "Geschäfte" },
];

const TYPEN: { wert: PropertyKind; text: string }[] = [
  { wert: "text", text: "Text" },
  { wert: "number", text: "Zahl" },
  { wert: "date", text: "Datum" },
  { wert: "bool", text: "Ja / Nein" },
  { wert: "select", text: "Auswahl" },
];

export const TYP_TEXT: Record<string, string> = Object.fromEntries(TYPEN.map((t) => [t.wert, t.text]));

/**
 * Eigene Eigenschaften anlegen und pflegen.
 *
 * Typ und Schlüssel stehen nach dem Anlegen fest — beides hinge sonst
 * von Werten ab, die schon in Datensätzen liegen. Abschalten statt
 * löschen: Die Werte bleiben, sie werden nur nicht mehr gezeigt.
 */
export function Eigenschaftenblock() {
  const client = useQueryClient();
  const [objekt, setObjekt] = useState<PropertyEntity>("companies");
  const [label, setLabel] = useState("");
  const [typ, setTyp] = useState<PropertyKind>("text");
  const [optionen, setOptionen] = useState("");

  const definitionen = useQuery({
    queryKey: ["eigenschaften", objekt],
    queryFn: () =>
      api.get<PropertyDefinition[]>(`/api/eigenschaften${suchparameter({ entity: objekt })}`),
  });

  const anlegen = useMutation({
    mutationFn: () =>
      api.post<PropertyDefinition>("/api/eigenschaften", {
        entity: objekt,
        label,
        kind: typ,
        options: typ === "select" ? optionen.split(",").map((o) => o.trim()).filter(Boolean) : [],
        position: definitionen.data?.length ?? 0,
      }),
    onSuccess: () => {
      setLabel("");
      setOptionen("");
      client.invalidateQueries({ queryKey: ["eigenschaften"] });
    },
  });

  const abschalten = useMutation({
    mutationFn: (id: string) => api.del(`/api/eigenschaften/${id}`),
    onSuccess: () => client.invalidateQueries({ queryKey: ["eigenschaften"] }),
  });

  return (
    <section className="block">
      <div className="block-kopf">
        <h2>Eigene Eigenschaften</h2>
        <select
          className="input"
          style={{ width: "auto" }}
          value={objekt}
          onChange={(e) => setObjekt(e.target.value as PropertyEntity)}
          aria-label="Objekt"
        >
          {OBJEKTE.map((o) => (
            <option key={o.wert} value={o.wert}>{o.text}</option>
          ))}
        </select>
      </div>
      <div className="block-inhalt">
        <p style={{ fontSize: "0.875rem", color: "var(--am-text-sekundaer)", marginBottom: "var(--am-raum-4)" }}>
          Was nur dieser Vertrieb braucht — „Serverraum vorhanden", „Kammer", „Wartungsvertrag
          bis" — kommt hier dazu und erscheint dann an jedem Datensatz. Typ und Schlüssel stehen
          nach dem Anlegen fest; die Beschriftung lässt sich ändern.
        </p>

        {definitionen.isPending && <Laedt />}
        {definitionen.data && definitionen.data.length > 0 && (
          <table className="tabelle" style={{ marginBottom: "var(--am-raum-4)" }}>
            <thead>
              <tr>
                <th>Beschriftung</th>
                <th>Schlüssel</th>
                <th>Typ</th>
                <th>Auswahl</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {definitionen.data.map((d) => (
                <tr key={d.id} style={{ cursor: "default" }}>
                  <td className="haupt">{d.label}</td>
                  <td className="mono" style={{ fontSize: "0.8125rem" }}>{d.key}</td>
                  <td>{TYP_TEXT[d.kind]}</td>
                  <td style={{ fontSize: "0.8125rem" }}>{d.options.join(", ") || "—"}</td>
                  <td style={{ textAlign: "right" }}>
                    <button
                      type="button"
                      className="btn btn-still btn-klein"
                      onClick={() => abschalten.mutate(d.id)}
                      title="Werte bleiben in den Datensätzen erhalten"
                    >
                      Abschalten
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        {definitionen.data?.length === 0 && (
          <p style={{ fontSize: "0.875rem", color: "var(--am-text-gedaempft)", marginBottom: "var(--am-raum-4)" }}>
            Noch keine eigene Eigenschaft für {OBJEKTE.find((o) => o.wert === objekt)?.text}.
          </p>
        )}
        {abschalten.isError && <Fehler text={(abschalten.error as Error).message} />}

        <form
          onSubmit={(e) => {
            e.preventDefault();
            if (label.trim()) anlegen.mutate();
          }}
          style={{ display: "grid", gridTemplateColumns: "2fr 1fr", gap: "0 var(--am-raum-4)", alignItems: "end" }}
        >
          <div className="feld">
            <label htmlFor="eig-label">Neue Eigenschaft</label>
            <input id="eig-label" value={label} onChange={(e) => setLabel(e.target.value)} placeholder="Wartungsvertrag bis" />
          </div>
          <div className="feld">
            <label htmlFor="eig-typ">Typ</label>
            <select id="eig-typ" value={typ} onChange={(e) => setTyp(e.target.value as PropertyKind)}>
              {TYPEN.map((t) => (
                <option key={t.wert} value={t.wert}>{t.text}</option>
              ))}
            </select>
          </div>
          {typ === "select" && (
            <div className="feld" style={{ gridColumn: "1 / -1" }}>
              <label htmlFor="eig-optionen">Erlaubte Werte, durch Komma getrennt</label>
              <input id="eig-optionen" value={optionen} onChange={(e) => setOptionen(e.target.value)} placeholder="Nord, Süd, West" />
            </div>
          )}
          <div className="btn-reihe" style={{ gridColumn: "1 / -1" }}>
            <button type="submit" className="btn btn-primaer btn-klein" disabled={!label.trim() || anlegen.isPending}>
              {anlegen.isPending ? "Legt an …" : "Anlegen"}
            </button>
          </div>
        </form>
        {anlegen.isError && <Fehler text={(anlegen.error as Error).message} />}
      </div>
    </section>
  );
}
