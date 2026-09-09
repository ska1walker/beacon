"use client";

// Kontakte und Firmen aus einer CSV.
//
// Zwei Schritte, nicht vier: sehen, was passieren würde, und es dann tun.
// Dazwischen bleibt die Datei im Browser liegen und geht beim Anwenden
// noch einmal mit — der Server bewahrt nichts auf.
//
// Der Bildschirm dazwischen ist der eigentliche Punkt der Sache. Ein
// Import ohne Vorschau ist ein Sprung ins Dunkle: Man sieht erst
// hinterher, dass die Spalte „Telefon" auf „Mobil" gelegt wurde.

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, Download, Upload } from "lucide-react";
import Link from "next/link";
import { useRef, useState } from "react";
import { api } from "@/lib/api";
import { anzahl, datumZeit, EINFUHR_GRUND_TEXT, OBJEKT_TEXT } from "@/lib/format";
import type {
  Einfuhr,
  Einfuhrergebnis,
  Einfuhrvorschau,
  EinfuhrGrund,
  Objektart,
  Wer,
} from "@/lib/typen";
import { Erklaerung } from "@/components/erklaerung";
import { Fehler } from "@/components/zustaende";

const KODIERUNGSNAME: Record<string, string> = {
  "utf-8": "UTF-8",
  "utf-8-sig": "UTF-8 mit BOM",
  "utf-16": "UTF-16",
  cp1252: "Windows-1252",
  "latin-1": "Latin-1",
};

function grundText(grund: EinfuhrGrund | null): string {
  return grund ? (EINFUHR_GRUND_TEXT[grund] ?? grund) : "Übersprungen";
}

/** Die Ausschlüsse, nach Grund gebündelt und aufklappbar. */
function Gruende({
  gruende,
  details,
}: {
  gruende: Partial<Record<EinfuhrGrund, number>>;
  details: { zeile: number; grund: EinfuhrGrund | null; text: string | null }[];
}) {
  const eintraege = Object.entries(gruende) as [EinfuhrGrund, number][];
  if (eintraege.length === 0) return null;
  return (
    <div style={{ display: "grid", gap: "var(--am-raum-1)", marginTop: "var(--am-raum-2)" }}>
      {eintraege.map(([grund, wie_viele]) => (
        <details key={grund}>
          <summary style={{ cursor: "pointer", fontSize: "0.8125rem" }}>
            {wie_viele}× {grundText(grund)}
          </summary>
          <ul
            style={{
              listStyle: "none",
              padding: "var(--am-raum-2) 0 0 var(--am-raum-4)",
              margin: 0,
              display: "grid",
              gap: "2px",
              fontSize: "0.75rem",
              color: "var(--am-text-gedaempft)",
            }}
          >
            {details
              .filter((d) => d.grund === grund)
              .slice(0, 20)
              .map((d) => (
                <li key={d.zeile}>
                  Zeile {d.zeile}: {d.text}
                </li>
              ))}
            {details.filter((d) => d.grund === grund).length > 20 && (
              <li>… und weitere</li>
            )}
          </ul>
        </details>
      ))}
    </div>
  );
}

export function Einfuhrblock({ vorwahl }: { vorwahl?: Objektart }) {
  const client = useQueryClient();
  const wer = useQuery({ queryKey: ["wer"], queryFn: () => api.get<Wer>("/api/mitglieder/wer") });
  const darfVerwalten = wer.data?.rolle === "owner" || wer.data?.rolle === "admin";
  const feld = useRef<HTMLInputElement>(null);
  const [datei, setDatei] = useState<File | null>(null);
  const [objekt, setObjekt] = useState<"" | Objektart>(vorwahl ?? "");
  const [vorschau, setVorschau] = useState<Einfuhrvorschau | null>(null);
  const [ergebnis, setErgebnis] = useState<Einfuhrergebnis | null>(null);
  const [ueber, setUeber] = useState(false);

  const bisher = useQuery({
    queryKey: ["einfuhren"],
    queryFn: () => api.get<Einfuhr[]>("/api/einfuhr"),
  });

  function formular(f: File, zuordnung?: (string | null)[]): FormData {
    const fd = new FormData();
    fd.append("datei", f);
    if (objekt) fd.append("entity", objekt);
    if (zuordnung) fd.append("zuordnung", JSON.stringify(zuordnung));
    return fd;
  }

  const lesen = useMutation({
    mutationFn: ({ f, zuordnung }: { f: File; zuordnung?: (string | null)[] }) =>
      api.postForm<Einfuhrvorschau>("/api/einfuhr/vorschau", formular(f, zuordnung)),
    onSuccess: (v) => {
      setVorschau(v);
      setErgebnis(null);
    },
  });

  const anwenden = useMutation({
    mutationFn: () =>
      api.postForm<Einfuhrergebnis>(
        "/api/einfuhr",
        formular(datei as File, vorschau?.spalten.map((s) => s.ziel) ?? []),
      ),
    onSuccess: (e) => {
      setErgebnis(e);
      setVorschau(null);
      setDatei(null);
      // Nach einem Import stimmt keine Liste und keine Zählung mehr.
      client.invalidateQueries({ queryKey: ["segment"] });
      client.invalidateQueries({ queryKey: ["segment-anzahl"] });
      client.invalidateQueries({ queryKey: ["einfuhren"] });
    },
  });

  function waehlen(dateien: FileList | null) {
    const f = dateien?.[0];
    if (!f) return;
    setDatei(f);
    setErgebnis(null);
    lesen.mutate({ f });
  }

  function umlegen(nr: number, ziel: string) {
    if (!vorschau || !datei) return;
    const zuordnung = vorschau.spalten.map((s) => (s.nr === nr ? ziel || null : s.ziel));
    lesen.mutate({ f: datei, zuordnung });
  }

  const fehler = (lesen.error ?? anwenden.error) as Error | null;

  return (
    <section className="block">
      <div className="block-kopf">
        <h2>Import aus einer CSV</h2>
      </div>
      <div className="block-inhalt">
        <Erklaerung
          kurz="Kontakte oder Firmen aus einer Tabelle anlegen. Vorhandene Datensätze werden nie überschrieben — Dubletten werden übersprungen und genannt."
          lang={
            <>
              CSV mit Semikolon, Komma oder Tabulator; Umlaute in UTF-8 oder Windows-1252. Bis
              10 MB und 20.000 Zeilen. Erkannt werden die Spaltennamen von Beacon und die
              gängigen aus anderen Systemen. Importierte Datensätze werden <strong>nicht</strong>{" "}
              automatisch angereichert — der Knopf am Datensatz bleibt.
            </>
          }
        />

        {!darfVerwalten && (
          <div className="hinweis" data-art="achtung">
            <AlertTriangle size={16} aria-hidden="true" />
            <span>Importieren darf nur der Eigentümer oder ein Verwalter.</span>
          </div>
        )}

        {/* Schritt 1: die Datei */}
        {!vorschau && !ergebnis && (
          <>
            <div style={{ display: "flex", gap: "var(--am-raum-3)", alignItems: "center", marginBottom: "var(--am-raum-3)", flexWrap: "wrap" }}>
              <span style={{ fontSize: "0.8125rem", color: "var(--am-text-gedaempft)" }}>Was steht in der Datei?</span>
              {([["", "erkennen"], ["contacts", "Kontakte"], ["companies", "Firmen"]] as const).map(
                ([wert, text]) => (
                  <label key={wert} style={{ display: "flex", alignItems: "center", gap: "var(--am-raum-1)", fontSize: "0.8125rem" }}>
                    <input
                      type="radio"
                      name="einfuhr-objekt"
                      checked={objekt === wert}
                      onChange={() => setObjekt(wert)}
                    />
                    {text}
                  </label>
                ),
              )}
            </div>

            <div
              onDragOver={(e) => { e.preventDefault(); setUeber(true); }}
              onDragLeave={() => setUeber(false)}
              onDrop={(e) => { e.preventDefault(); setUeber(false); waehlen(e.dataTransfer.files); }}
              style={{
                border: `1px dashed ${ueber ? "var(--am-handlung)" : "var(--am-rand)"}`,
                borderRadius: "var(--am-radius-2)",
                padding: "var(--am-raum-4)",
                textAlign: "center",
                background: ueber ? "var(--am-flaeche-2)" : "transparent",
              }}
            >
              <input
                ref={feld}
                type="file"
                accept=".csv,.txt,text/csv"
                hidden
                onChange={(e) => { waehlen(e.target.files); e.target.value = ""; }}
              />
              <button
                type="button"
                className="btn btn-sekundaer btn-klein"
                disabled={!darfVerwalten || lesen.isPending}
                onClick={() => feld.current?.click()}
              >
                <Upload size={14} aria-hidden="true" />
                {lesen.isPending ? "Wird gelesen …" : "CSV wählen"}
              </button>
              <p style={{ fontSize: "0.75rem", color: "var(--am-text-gedaempft)", margin: "var(--am-raum-2) 0 0" }}>
                oder hierher ziehen
              </p>
            </div>

            <p style={{ fontSize: "0.75rem", color: "var(--am-text-gedaempft)", marginTop: "var(--am-raum-3)" }}>
              Leere Vorlage mit den richtigen Spaltennamen:{" "}
              <a href="/api/einfuhr/vorlage?entity=contacts" download>Kontakte</a>
              {" · "}
              <a href="/api/einfuhr/vorlage?entity=companies" download>Firmen</a>
            </p>
          </>
        )}

        {/* Schritt 2: die Zuordnung prüfen */}
        {vorschau && (
          <>
            <p style={{ fontSize: "0.75rem", color: "var(--am-text-gedaempft)", marginBottom: "var(--am-raum-3)" }}>
              {anzahl(vorschau.zeilen, "Zeile", "Zeilen")} · gelesen als{" "}
              {KODIERUNGSNAME[vorschau.kodierung] ?? vorschau.kodierung} · Trennzeichen{" "}
              <code>{vorschau.trenner === "\t" ? "Tabulator" : vorschau.trenner}</code> ·{" "}
              {OBJEKT_TEXT[vorschau.entity]}
            </p>

            <div className="tabellenrahmen" style={{ overflowX: "auto" }}>
              <table className="tabelle">
                <thead>
                  <tr>
                    <th>Spalte in der Datei</th>
                    <th>Beispiele</th>
                    <th>Feld in Beacon</th>
                  </tr>
                </thead>
                <tbody>
                  {vorschau.spalten.map((s) => (
                    <tr key={s.nr}>
                      <td style={{ fontWeight: 600 }}>{s.kopf}</td>
                      <td style={{ fontSize: "0.75rem", color: "var(--am-text-gedaempft)" }}>
                        {s.beispiele.join(" · ") || "—"}
                      </td>
                      <td>
                        <select
                          value={s.ziel ?? ""}
                          aria-label={`Ziel für ${s.kopf}`}
                          onChange={(e) => umlegen(s.nr, e.target.value)}
                        >
                          <option value="">— nicht importieren —</option>
                          <optgroup label="Felder">
                            {vorschau.ziele.filter((z) => !z.eigen).map((z) => (
                              <option key={z.schluessel} value={z.schluessel}>{z.text}</option>
                            ))}
                          </optgroup>
                          {vorschau.ziele.some((z) => z.eigen) && (
                            <optgroup label="Eigene Eigenschaften">
                              {vorschau.ziele.filter((z) => z.eigen).map((z) => (
                                <option key={z.schluessel} value={z.schluessel}>{z.text}</option>
                              ))}
                            </optgroup>
                          )}
                        </select>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            {vorschau.hinweise.map((h) => (
              <div key={h} className="hinweis" data-art="achtung" style={{ marginTop: "var(--am-raum-3)" }}>
                <AlertTriangle size={16} aria-hidden="true" />
                <span>{h}</span>
              </div>
            ))}

            <p style={{ marginTop: "var(--am-raum-3)", fontSize: "0.875rem" }}>
              <strong>{anzahl(vorschau.bilanz.anlegen, "Datensatz", "Datensätze")} anlegen</strong>
              {vorschau.bilanz.firmen_anlegen > 0 &&
                ` · ${anzahl(vorschau.bilanz.firmen_anlegen, "Firma", "Firmen")} dazu`}
              {vorschau.bilanz.ueberspringen > 0 && ` · ${vorschau.bilanz.ueberspringen} überspringen`}
            </p>
            <Gruende gruende={vorschau.bilanz.gruende} details={vorschau.uebersprungen} />

            <div style={{ display: "flex", gap: "var(--am-raum-2)", marginTop: "var(--am-raum-4)" }}>
              <button
                type="button"
                className="btn btn-primaer btn-klein"
                disabled={!darfVerwalten || vorschau.bilanz.anlegen === 0 || anwenden.isPending}
                onClick={() => anwenden.mutate()}
              >
                {anwenden.isPending
                  ? "Wird angelegt …"
                  : `${vorschau.bilanz.anlegen} anlegen`}
              </button>
              <button
                type="button"
                className="btn btn-still btn-klein"
                onClick={() => { setVorschau(null); setDatei(null); }}
              >
                Abbrechen
              </button>
            </div>
          </>
        )}

        {/* Schritt 3: was daraus geworden ist */}
        {ergebnis && (
          <>
            <p style={{ fontSize: "0.875rem" }}>
              <strong>
                {anzahl(ergebnis.angelegt, "Datensatz", "Datensätze")} angelegt
              </strong>
              {ergebnis.firmen_angelegt > 0 &&
                ` · ${anzahl(ergebnis.firmen_angelegt, "Firma", "Firmen")} dazu`}
              {ergebnis.uebersprungen > 0 && ` · ${ergebnis.uebersprungen} übersprungen`}
            </p>
            <Gruende gruende={ergebnis.gruende} details={ergebnis.details} />
            <div style={{ display: "flex", gap: "var(--am-raum-2)", marginTop: "var(--am-raum-4)" }}>
              <Link
                className="btn btn-sekundaer btn-klein"
                href={ergebnis.entity === "companies" ? "/firmen" : "/kontakte"}
              >
                Ansehen
              </Link>
              <button type="button" className="btn btn-still btn-klein" onClick={() => setErgebnis(null)}>
                Noch eine Datei
              </button>
            </div>
          </>
        )}

        {fehler && <Fehler text={fehler.message} />}

        {bisher.data && bisher.data.length > 0 && (
          <details style={{ marginTop: "var(--am-raum-5)" }}>
            <summary style={{ cursor: "pointer", fontSize: "0.8125rem" }}>Bisherige Importe</summary>
            <div className="tabellenrahmen" style={{ overflowX: "auto", marginTop: "var(--am-raum-2)" }}>
              <table className="tabelle">
                <thead>
                  <tr>
                    <th>Wann</th>
                    <th>Datei</th>
                    <th>Was</th>
                    <th>Angelegt</th>
                    <th>Übersprungen</th>
                    <th>Von</th>
                  </tr>
                </thead>
                <tbody>
                  {bisher.data.map((e) => (
                    <tr key={e.id}>
                      <td>{datumZeit(e.created_at)}</td>
                      <td>{e.dateiname}</td>
                      <td>{OBJEKT_TEXT[e.entity]}</td>
                      <td>{e.status === "fehlgeschlagen" ? "fehlgeschlagen" : e.angelegt}</td>
                      <td>{e.uebersprungen}</td>
                      <td>{e.von ?? "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </details>
        )}

        <p style={{ fontSize: "0.75rem", color: "var(--am-text-gedaempft)", marginTop: "var(--am-raum-4)" }}>
          <Download size={12} aria-hidden="true" style={{ verticalAlign: "-1px" }} /> Hinaus geht es
          über „Exportieren" in der Liste der Kontakte oder Firmen — mit Filter, Spalten und
          Sortierung von dort.
        </p>
      </div>
    </section>
  );
}
