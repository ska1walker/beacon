"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Archive, ArchiveRestore, ArrowDown, ArrowUp, Plus, X } from "lucide-react";
import { Fragment, useState } from "react";
import { api, suchparameter } from "@/lib/api";
import type {
  Eigenschaftsoption,
  PropertyDefinition,
  PropertyEntity,
  PropertyKind,
} from "@/lib/typen";
import { Fehler, Laedt } from "@/components/zustaende";
import { Erklaerung } from "@/components/erklaerung";

const OBJEKTE: { wert: PropertyEntity; text: string }[] = [
  { wert: "companies", text: "Firmen" },
  { wert: "contacts", text: "Kontakte" },
  { wert: "deals", text: "Leads" },
];

const TYPEN: { wert: PropertyKind; text: string; hinweis?: string }[] = [
  { wert: "text", text: "Text" },
  { wert: "number", text: "Zahl" },
  { wert: "date", text: "Datum" },
  { wert: "bool", text: "Ja / Nein" },
  { wert: "select", text: "Auswahl", hinweis: "genau ein Wert" },
  { wert: "multiselect", text: "Mehrfachauswahl", hinweis: "beliebig viele Werte" },
];

export const TYP_TEXT: Record<string, string> = Object.fromEntries(TYPEN.map((t) => [t.wert, t.text]));

/** Beide Typen führen eine Werteliste. */
const MIT_OPTIONEN: PropertyKind[] = ["select", "multiselect"];

/**
 * Eigene Eigenschaften anlegen und pflegen.
 *
 * Typ und Schlüssel stehen nach dem Anlegen fest — beides hinge sonst
 * von Werten ab, die schon in Datensätzen liegen. Abschalten statt
 * löschen: Die Werte bleiben, sie werden nur nicht mehr gezeigt.
 *
 * Die Werteliste dagegen ist änderbar, denn sie wächst im Betrieb: Eine
 * neue Zertifizierung, eine neue Messe. Was noch an Datensätzen hängt,
 * lässt das Backend nicht streichen — ein entfernter Wert wäre sonst
 * lesbar, aber der Datensatz nicht mehr speicherbar.
 */
export function Eigenschaftenblock() {
  const client = useQueryClient();
  const [objekt, setObjekt] = useState<PropertyEntity>("companies");
  const [label, setLabel] = useState("");
  const [typ, setTyp] = useState<PropertyKind>("text");
  const [optionen, setOptionen] = useState<Eigenschaftsoption[]>([leereOption()]);
  const [bearbeitet, setBearbeitet] = useState<string | null>(null);

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
        options: MIT_OPTIONEN.includes(typ) ? sauber(optionen) : [],
        position: definitionen.data?.length ?? 0,
      }),
    onSuccess: () => {
      setLabel("");
      setOptionen([leereOption()]);
      client.invalidateQueries({ queryKey: ["eigenschaften"] });
    },
  });

  const abschalten = useMutation({
    mutationFn: (id: string) => api.del(`/api/eigenschaften/${id}`),
    onSuccess: () => client.invalidateQueries({ queryKey: ["eigenschaften"] }),
  });

  const werteSetzen = useMutation({
    mutationFn: ({ id, options }: { id: string; options: Eigenschaftsoption[] }) =>
      api.patch<PropertyDefinition>(`/api/eigenschaften/${id}`, { options }),
    onSuccess: () => {
      setBearbeitet(null);
      client.invalidateQueries({ queryKey: ["eigenschaften"] });
    },
  });

  const braucht = MIT_OPTIONEN.includes(typ);
  const genug = label.trim() && (!braucht || sauber(optionen).length > 0);

  return (
    <section className="block">
      <div className="block-kopf">
        <h2>Eigene Felder</h2>
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
        <Erklaerung kurz="Eigene Felder für das, was nur Ihr Vertrieb braucht." lang={<>Was nur dieser Vertrieb braucht — „Serverraum vorhanden“, „Kammer“, „Wartungsvertrag
          bis“ — kommt hier dazu und erscheint dann an jedem Datensatz. Typ und Schlüssel stehen
          nach dem Anlegen fest; Beschriftung und Werteliste lassen sich ändern.</>} />

        {definitionen.isPending && <Laedt />}
        {definitionen.data && definitionen.data.length > 0 && (
          <table className="tabelle" style={{ marginBottom: "var(--am-raum-4)" }}>
            <thead>
              <tr>
                <th>Beschriftung</th>
                <th>Schlüssel</th>
                <th>Typ</th>
                <th>Werte</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {definitionen.data.map((d) => (
                // Der Werte-Editor bekommt eine eigene Zeile über die volle
                // Breite. In der Spalte selbst hätte er die Tabelle über den
                // Rand des Blocks hinausgeschoben.
                <Fragment key={d.id}>
                  <tr style={{ cursor: "default" }}>
                    <td className="haupt">{d.label}</td>
                    <td className="mono" style={{ fontSize: "0.8125rem" }}>{d.key}</td>
                    <td>{TYP_TEXT[d.kind]}</td>
                    <td style={{ fontSize: "0.8125rem" }}>
                      {MIT_OPTIONEN.includes(d.kind) ? (
                        <button
                          type="button"
                          className="zellen-link"
                          aria-expanded={bearbeitet === d.id}
                          onClick={() => setBearbeitet(bearbeitet === d.id ? null : d.id)}
                          style={{ border: 0, background: "transparent", padding: 0, cursor: "pointer", textAlign: "left" }}
                        >
                          {zusammenfassung(d.options)}
                        </button>
                      ) : (
                        "—"
                      )}
                    </td>
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
                  {bearbeitet === d.id && (
                    <tr style={{ cursor: "default" }}>
                      <td colSpan={5} style={{ background: "var(--am-flaeche-1)" }}>
                        <Werteliste
                          werte={d.options}
                          laeuft={werteSetzen.isPending}
                          beiSichern={(options) => werteSetzen.mutate({ id: d.id, options })}
                          beiAbbruch={() => setBearbeitet(null)}
                        />
                      </td>
                    </tr>
                  )}
                </Fragment>
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
        {werteSetzen.isError && <Fehler text={(werteSetzen.error as Error).message} />}

        <form
          onSubmit={(e) => {
            e.preventDefault();
            if (genug) anlegen.mutate();
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
                <option key={t.wert} value={t.wert}>
                  {t.text}
                  {t.hinweis ? ` — ${t.hinweis}` : ""}
                </option>
              ))}
            </select>
          </div>
          {braucht && (
            <div className="feld" style={{ gridColumn: "1 / -1" }}>
              <label>Erlaubte Werte</label>
              <Optionsfelder werte={optionen} beiAendern={setOptionen} />
              <p className="feld-hinweis">
                {typ === "multiselect"
                  ? "An jedem Datensatz lassen sich beliebig viele davon setzen."
                  : "An jedem Datensatz gilt genau einer davon."}
              </p>
            </div>
          )}
          <div className="btn-reihe" style={{ gridColumn: "1 / -1" }}>
            <button type="submit" className="btn btn-primaer btn-klein" disabled={!genug || anlegen.isPending}>
              {anlegen.isPending ? "Legt an …" : "Anlegen"}
            </button>
          </div>
        </form>
        {anlegen.isError && <Fehler text={(anlegen.error as Error).message} />}
      </div>
    </section>
  );
}

function leereOption(): Eigenschaftsoption {
  return { wert: "", text: "", verborgen: false };
}

/** Nur Zeilen mit Beschriftung; der Wert kommt beim Anlegen vom Server. */
function sauber(werte: Eigenschaftsoption[]): Eigenschaftsoption[] {
  return werte
    .map((o) => ({ ...o, text: o.text.trim(), wert: o.wert.trim() }))
    .filter((o) => o.text);
}

/** Was in der Übersichtszeile steht. */
function zusammenfassung(optionen: Eigenschaftsoption[]): string {
  if (optionen.length === 0) return "Werte festlegen";
  const offen = optionen.filter((o) => !o.verborgen);
  const archiviert = optionen.length - offen.length;
  const liste = offen.map((o) => o.text).join(", ") || "alle archiviert";
  return archiviert > 0 ? `${liste} · ${archiviert} archiviert` : liste;
}

/**
 * Die Werteliste als Zeilen, nicht als Komma-Text.
 *
 * Ein Feld „Nord, Süd, West“ liest sich harmlos und geht schief, sobald
 * ein Wert selbst ein Komma enthält („Meyer, Schmidt & Partner“). Zeilen
 * haben das Problem nicht, und die Reihenfolge wird nebenbei sichtbar —
 * sie ist die, in der die Werte später überall erscheinen.
 *
 * Geändert wird die **Beschriftung**. Der gespeicherte Wert steht daneben
 * und bleibt, was er ist: Er hängt an jedem Datensatz, der die Option
 * trägt. Wer eine Option aus dem Verkehr ziehen will, archiviert sie —
 * dann wird sie nicht mehr angeboten und bleibt dort trotzdem gültig.
 */
function Optionsfelder({
  werte,
  beiAendern,
}: {
  werte: Eigenschaftsoption[];
  beiAendern: (neu: Eigenschaftsoption[]) => void;
}) {
  function setze(i: number, teil: Partial<Eigenschaftsoption>) {
    beiAendern(werte.map((o, j) => (j === i ? { ...o, ...teil } : o)));
  }

  function schieben(i: number, um: number) {
    const ziel = i + um;
    if (ziel < 0 || ziel >= werte.length) return;
    const neu = [...werte];
    [neu[i], neu[ziel]] = [neu[ziel], neu[i]];
    beiAendern(neu);
  }

  // Eingefügte Zeilen oder Kommas werden aufgeteilt: Wer eine Liste aus
  // einer Tabelle kopiert, soll sie nicht einzeln abtippen.
  function einfuegen(i: number, text: string) {
    const teile = text.split(/[\n;,]/).map((t) => t.trim()).filter(Boolean);
    if (teile.length <= 1) return false;
    beiAendern([
      ...werte.slice(0, i),
      ...teile.map((t) => ({ wert: "", text: t, verborgen: false })),
      ...werte.slice(i + 1),
    ]);
    return true;
  }

  return (
    <div className="optionsliste">
      {werte.map((o, i) => (
        <div className="optionszeile" key={i} data-archiviert={o.verborgen ? "true" : undefined}>
          <input
            value={o.text}
            aria-label={`Beschriftung ${i + 1}`}
            placeholder="Beschriftung"
            onChange={(e) => setze(i, { text: e.target.value })}
            onPaste={(e) => {
              if (einfuegen(i, e.clipboardData.getData("text"))) e.preventDefault();
            }}
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                e.preventDefault();
                beiAendern([...werte.slice(0, i + 1), leereOption(), ...werte.slice(i + 1)]);
              }
            }}
          />
          {o.wert && o.wert !== o.text && (
            <span className="optionswert mono" title="Gespeicherter Wert — steht in den Datensätzen und ändert sich nicht">
              {o.wert}
            </span>
          )}
          <button type="button" className="btn btn-still btn-klein btn-symbol" aria-label="Nach oben" disabled={i === 0} onClick={() => schieben(i, -1)}>
            <ArrowUp size={14} aria-hidden="true" />
          </button>
          <button type="button" className="btn btn-still btn-klein btn-symbol" aria-label="Nach unten" disabled={i === werte.length - 1} onClick={() => schieben(i, 1)}>
            <ArrowDown size={14} aria-hidden="true" />
          </button>
          {o.wert ? (
            <button
              type="button"
              className="btn btn-still btn-klein btn-symbol"
              aria-label={o.verborgen ? "Wieder anbieten" : "Archivieren"}
              title={
                o.verborgen
                  ? "Wieder zur Wahl stellen"
                  : "Nicht mehr anbieten — an vorhandenen Datensätzen bleibt der Wert gültig"
              }
              onClick={() => setze(i, { verborgen: !o.verborgen })}
            >
              {o.verborgen ? <ArchiveRestore size={14} aria-hidden="true" /> : <Archive size={14} aria-hidden="true" />}
            </button>
          ) : null}
          <button
            type="button"
            className="btn btn-still btn-klein btn-symbol"
            aria-label="Zeile entfernen"
            onClick={() => beiAendern(werte.length === 1 ? [leereOption()] : werte.filter((_, j) => j !== i))}
          >
            <X size={14} aria-hidden="true" />
          </button>
        </div>
      ))}
      <button type="button" className="btn btn-still btn-klein" onClick={() => beiAendern([...werte, leereOption()])}>
        <Plus size={14} aria-hidden="true" />
        Wert
      </button>
    </div>
  );
}

/** Werteliste einer bestehenden Eigenschaft ändern. */
function Werteliste({
  werte,
  laeuft,
  beiSichern,
  beiAbbruch,
}: {
  werte: Eigenschaftsoption[];
  laeuft: boolean;
  beiSichern: (neu: Eigenschaftsoption[]) => void;
  beiAbbruch: () => void;
}) {
  const [entwurf, setEntwurf] = useState<Eigenschaftsoption[]>(
    werte.length ? werte : [leereOption()],
  );
  const fertig = sauber(entwurf);

  return (
    <div>
      <Optionsfelder werte={entwurf} beiAendern={setEntwurf} />
      <div className="btn-reihe" style={{ marginTop: "var(--am-raum-2)" }}>
        <button
          type="button"
          className="btn btn-primaer btn-klein"
          disabled={laeuft || fertig.length === 0 || fertig.every((o) => o.verborgen)}
          onClick={() => beiSichern(fertig)}
        >
          {laeuft ? "Speichert …" : "Speichern"}
        </button>
        <button type="button" className="btn btn-still btn-klein" onClick={beiAbbruch}>
          Abbrechen
        </button>
      </div>
    </div>
  );
}
