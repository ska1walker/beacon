"use client";

import { Plus, X } from "lucide-react";
import { OHNE_WERT, OPERATOR_TEXT } from "@/lib/format";
import { Mehrfachauswahl } from "@/components/mehrfachauswahl";
import type { Bedingung, Feldauskunft, Segmentfeld } from "@/lib/typen";

/**
 * Bedingungen bauen: Feld, Operator, Wert — beliebig oft untereinander.
 *
 * Die Felder kommen vom Server, samt der Operatoren, die zu ihnen passen.
 * Deshalb steht hier keine Liste von Feldnamen: Eine selbst angelegte
 * Eigenschaft erscheint von allein, sobald jemand sie anlegt.
 */
export function Filterbau({
  auskunft,
  bedingungen,
  verknuepfung,
  beiAendern,
  beiVerknuepfung,
}: {
  auskunft: Feldauskunft;
  bedingungen: Bedingung[];
  verknuepfung: "und" | "oder";
  beiAendern: (neu: Bedingung[]) => void;
  beiVerknuepfung: (v: "und" | "oder") => void;
}) {
  const filterbar = auskunft.felder.filter((f) => f.filterbar);

  function feldVon(schluessel: string): Segmentfeld | undefined {
    return auskunft.felder.find((f) => f.schluessel === schluessel);
  }

  function setze(i: number, teil: Partial<Bedingung>) {
    beiAendern(bedingungen.map((b, j) => (j === i ? { ...b, ...teil } : b)));
  }

  function hinzu() {
    const erstes = filterbar[0];
    beiAendern([
      ...bedingungen,
      { feld: erstes.schluessel, operator: erstes.operatoren[0], wert: "" },
    ]);
  }

  return (
    <div className="filterbau">
      {bedingungen.length === 0 && (
        <p className="filterbau-leer">
          Ohne Bedingung steht hier alles. Eine Bedingung macht daraus eine Frage an den
          Bestand — und die lässt sich als Ansicht behalten.
        </p>
      )}

      {bedingungen.map((b, i) => {
        const feld = feldVon(b.feld);
        const braucht = !OHNE_WERT.has(b.operator);
        return (
          <div className="filterzeile" key={i}>
            {i > 0 && (
              <select
                className="filter-verknuepfung"
                value={verknuepfung}
                onChange={(e) => beiVerknuepfung(e.target.value as "und" | "oder")}
                aria-label="Verknüpfung"
              >
                <option value="und">und</option>
                <option value="oder">oder</option>
              </select>
            )}
            {i === 0 && <span className="filter-verknuepfung leer">wenn</span>}

            <select
              value={b.feld}
              aria-label="Feld"
              onChange={(e) => {
                const neu = feldVon(e.target.value);
                const op = neu?.operatoren[0] ?? "ist";
                setze(i, { feld: e.target.value, operator: op, wert: MEHRWERTIG.has(op) ? [] : "" });
              }}
            >
              {filterbar.map((f) => (
                <option key={f.schluessel} value={f.schluessel}>
                  {f.text}
                  {f.eigen ? " (eigen)" : ""}
                </option>
              ))}
            </select>

            <select
              value={b.operator}
              aria-label="Operator"
              onChange={(e) =>
                setze(i, {
                  operator: e.target.value,
                  wert: MEHRWERTIG.has(e.target.value) ? [] : "",
                })
              }
            >
              {(feld?.operatoren ?? []).map((o) => (
                <option key={o} value={o}>
                  {OPERATOR_TEXT[o] ?? o}
                </option>
              ))}
            </select>

            {braucht && <Wertfeld feld={feld} bedingung={b} auskunft={auskunft} setze={(w) => setze(i, { wert: w })} />}

            <button
              type="button"
              className="btn btn-still btn-klein"
              aria-label="Bedingung entfernen"
              onClick={() => beiAendern(bedingungen.filter((_, j) => j !== i))}
            >
              <X size={14} aria-hidden="true" />
            </button>
          </div>
        );
      })}

      <button type="button" className="btn btn-still btn-klein" onClick={hinzu}>
        <Plus size={14} aria-hidden="true" />
        Bedingung
      </button>
    </div>
  );
}

/** Vergleiche, die mehrere Werte entgegennehmen. */
const MEHRWERTIG = new Set([
  "ist_eines_von",
  "hat_eines_von",
  "hat_alle_von",
  "hat_keines_von",
  "hat_nicht_alle_von",
]);

/** Das Eingabefeld richtet sich nach der Art des Feldes — und nach dem Operator. */
function Wertfeld({
  feld,
  bedingung,
  auskunft,
  setze,
}: {
  feld: Segmentfeld | undefined;
  bedingung: Bedingung;
  auskunft: Feldauskunft;
  setze: (wert: Bedingung["wert"]) => void;
}) {
  const wert = bedingung.wert;

  // „in den letzten … Tagen" ist eine Zahl, auch an einem Datumsfeld.
  if (bedingung.operator === "letzte_tage" || bedingung.operator === "aelter_als_tage") {
    return (
      <input
        type="number"
        min={0}
        value={typeof wert === "number" || typeof wert === "string" ? wert : ""}
        onChange={(e) => setze(e.target.value)}
        aria-label="Anzahl Tage"
        style={{ maxWidth: "7rem" }}
      />
    );
  }

  // Alle Vergleiche, die auf mehrere Werte gehen — „ist eines von" an
  // einer Auswahl ebenso wie die Listenoperatoren einer Mehrfachauswahl.
  // Eine Reihe Kontrollkästchen stand hier vorher und wurde bei vierzig
  // Optionen zur Tapete.
  if (MEHRWERTIG.has(bedingung.operator)) {
    const gewaehlt = Array.isArray(wert) ? wert : wert ? [String(wert)] : [];
    return (
      <Mehrfachauswahl
        kompakt
        ariaLabel="Werte"
        platzhalter="Werte wählen …"
        optionen={(feld?.optionen ?? []).map((o) => ({
          wert: o.wert,
          // Archivierte Werte bleiben wählbar: Wer eine Option aus dem
          // Verkehr zieht, will die Datensätze, die sie noch tragen,
          // gerade dann finden.
          text: o.verborgen ? `${o.text} (archiviert)` : o.text,
        }))}
        gewaehlt={gewaehlt}
        beiAendern={setze}
      />
    );
  }

  if (feld?.art === "person") {
    return (
      <select value={String(wert ?? "")} onChange={(e) => setze(e.target.value)} aria-label="Person">
        <option value="">— wählen —</option>
        {auskunft.personen.map((p) => (
          <option key={p.id} value={p.id}>
            {p.name}
          </option>
        ))}
      </select>
    );
  }

  if (feld?.art === "auswahl" && feld.optionen.length > 0) {
    return (
      <select value={String(wert ?? "")} onChange={(e) => setze(e.target.value)} aria-label="Wert">
        <option value="">— wählen —</option>
        {feld.optionen.map((o) => (
          <option key={o.wert} value={o.wert}>
            {o.text}
          </option>
        ))}
      </select>
    );
  }

  return (
    <input
      type={feld?.art === "zahl" ? "number" : feld?.art === "datum" ? "date" : "text"}
      value={typeof wert === "string" || typeof wert === "number" ? wert : ""}
      onChange={(e) => setze(e.target.value)}
      aria-label="Wert"
      placeholder="Wert"
    />
  );
}
