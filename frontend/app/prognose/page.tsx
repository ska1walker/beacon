"use client";

import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { api, suchparameter } from "@/lib/api";
import { euro, PRODUKT_TEXT } from "@/lib/format";
import type { Prognose } from "@/lib/typen";
import { Seitenkopf } from "@/components/seitenkopf";
import { Fehler, Laedt } from "@/components/zustaende";

function monatsname(schluessel: string): string {
  const [jahr, monat] = schluessel.split("-").map(Number);
  return new Intl.DateTimeFormat("de-DE", { month: "short", year: "numeric" }).format(
    new Date(jahr, monat - 1, 1),
  );
}

/**
 * Ein Balken. Bewusst als Fläche und nicht als Diagrammbibliothek: Eine
 * Bibliothek für sechs Balken wäre 90 kB für eine Zahl, die auch als
 * Breite in Prozent stimmt.
 */
function Balken({ anteil, betont }: { anteil: number; betont?: boolean }) {
  return (
    <div className="balken">
      <div
        className="balken-fuell"
        data-betont={betont ? "true" : undefined}
        style={{ width: `${Math.max(2, Math.round(anteil * 100))}%` }}
      />
    </div>
  );
}

export default function PrognoseSeite() {
  const jahr = new Date().getFullYear();
  const [von, setVon] = useState(`${jahr}-01-01`);
  const [bis, setBis] = useState(`${jahr}-12-31`);

  const abfrage = useQuery({
    queryKey: ["prognose", von, bis],
    queryFn: () => api.get<Prognose>(`/api/prognose${suchparameter({ von, bis })}`),
  });

  if (abfrage.isPending) return <Laedt />;
  if (abfrage.isError) return <Fehler text={(abfrage.error as Error).message} />;

  const p = abfrage.data!;
  const groessterMonat = Math.max(1, ...p.monate.map((m) => m.offen_cents));
  const meisteVerluste = Math.max(1, ...p.verlustgruende.map((g) => g.anzahl));

  return (
    <>
      <Seitenkopf
        titel="Prognose"
        zahl={`${p.anzahl_offen} offene Leads · ${euro(p.gewichtet_cents)} gewichtet`}
      />

      <div className="werkzeugleiste">
        <label style={{ fontSize: "0.8125rem", display: "flex", gap: "var(--am-raum-2)", alignItems: "center" }}>
          Entschieden von
          <input className="input" type="date" value={von} onChange={(e) => setVon(e.target.value)} style={{ width: "auto" }} />
        </label>
        <label style={{ fontSize: "0.8125rem", display: "flex", gap: "var(--am-raum-2)", alignItems: "center" }}>
          bis
          <input className="input" type="date" value={bis} onChange={(e) => setBis(e.target.value)} style={{ width: "auto" }} />
        </label>
        <span style={{ fontSize: "0.75rem", color: "var(--am-text-gedaempft)" }}>
          Offene Leads zählen immer alle — ein Zeitfilter würde gerade die verstecken,
          deren Datum längst verstrichen ist.
        </span>
      </div>

      <dl className="kennzahlen">
        <div className="kennzahl">
          <dt>Offen</dt>
          <dd>{euro(p.offen_cents)}</dd>
          <div className="kennzahl-fuss">{p.anzahl_offen} Leads</div>
        </div>
        <div className="kennzahl">
          <dt>Gewichtet</dt>
          <dd>{euro(p.gewichtet_cents)}</dd>
          <div className="kennzahl-fuss">nach Stufenwahrscheinlichkeit</div>
        </div>
        <div className="kennzahl">
          <dt>Gewonnen im Zeitraum</dt>
          <dd>{euro(p.gewonnen_cents)}</dd>
          <div className="kennzahl-fuss">{p.anzahl_gewonnen} Abschlüsse</div>
        </div>
        <div className="kennzahl">
          <dt>Trefferquote</dt>
          <dd>
            {p.trefferquote === null ? "—" : `${Math.round(p.trefferquote * 100)} %`}
          </dd>
          <div className="kennzahl-fuss">
            {p.trefferquote === null
              ? "noch nichts entschieden"
              : `${p.anzahl_gewonnen} von ${p.anzahl_gewonnen + p.anzahl_verloren}`}
          </div>
        </div>
        <div className="kennzahl">
          <dt>Dauer bis Abschluss</dt>
          <dd>
            {p.durchschnittsdauer_tage === null
              ? "—"
              : `${Math.round(p.durchschnittsdauer_tage)}`}
          </dd>
          <div className="kennzahl-fuss">Tage im Mittel</div>
        </div>
        <div className="kennzahl">
          <dt>Überfällig</dt>
          <dd>{p.ueberfaellig_anzahl}</dd>
          <div className="kennzahl-fuss">{euro(p.ueberfaellig_cents)} mit verstrichenem Datum</div>
        </div>
      </dl>

      <div className="datensatz" style={{ gridTemplateColumns: "minmax(0, 1fr) minmax(0, 1fr)" }}>
        <section className="block">
          <div className="block-kopf">
            <h2>Erwarteter Abschluss je Monat</h2>
          </div>
          <div className="block-inhalt">
            {p.monate.length === 0 ? (
              <p style={{ fontSize: "0.875rem", color: "var(--am-text-gedaempft)" }}>
                Kein offener Lead trägt ein Abschlussdatum. Ohne Datum lässt sich nichts
                prognostizieren — das ist die eigentliche Aussage dieser Kachel.
              </p>
            ) : (
              <table className="tabelle">
                <thead>
                  <tr>
                    <th>Monat</th>
                    <th style={{ width: "40%" }}>Verteilung</th>
                    <th style={{ textAlign: "right" }}>Offen</th>
                    <th style={{ textAlign: "right" }}>Gewichtet</th>
                  </tr>
                </thead>
                <tbody>
                  {p.monate.map((m) => (
                    <tr key={m.monat} style={{ cursor: "default" }}>
                      <td className="haupt">{monatsname(m.monat)}</td>
                      <td>
                        <Balken anteil={m.offen_cents / groessterMonat} />
                      </td>
                      <td className="zahl">{euro(m.offen_cents)}</td>
                      <td className="zahl">{euro(m.gewichtet_cents)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        </section>

        <section className="block">
          <div className="block-kopf">
            <h2>Woran es lag</h2>
          </div>
          <div className="block-inhalt">
            {p.verlustgruende.length === 0 ? (
              <p style={{ fontSize: "0.875rem", color: "var(--am-text-gedaempft)" }}>
                Im Zeitraum ist nichts verloren gegangen — oder es wurde kein Grund vermerkt.
              </p>
            ) : (
              <table className="tabelle">
                <thead>
                  <tr>
                    <th>Grund</th>
                    <th style={{ width: "35%" }}>Anteil</th>
                    <th style={{ textAlign: "right" }}>Anzahl</th>
                    <th style={{ textAlign: "right" }}>Wert</th>
                  </tr>
                </thead>
                <tbody>
                  {p.verlustgruende.map((g) => (
                    <tr key={g.grund} style={{ cursor: "default" }}>
                      <td className="haupt">{g.grund}</td>
                      <td>
                        <Balken anteil={g.anzahl / meisteVerluste} betont />
                      </td>
                      <td className="zahl">{g.anzahl}</td>
                      <td className="zahl">{euro(g.summe_cents)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        </section>

        <section className="block" style={{ gridColumn: "1 / -1" }}>
          <div className="block-kopf">
            <h2>Nach Produkt</h2>
          </div>
          <div className="block-inhalt">
            {p.produkte.length === 0 ? (
              <p style={{ fontSize: "0.875rem", color: "var(--am-text-gedaempft)" }}>
                Im Zeitraum wurde nichts entschieden.
              </p>
            ) : (
              <table className="tabelle">
                <thead>
                  <tr>
                    <th>Produkt</th>
                    <th style={{ textAlign: "right" }}>Gewonnen</th>
                    <th style={{ textAlign: "right" }}>Verloren</th>
                    <th style={{ textAlign: "right" }}>Trefferquote</th>
                    <th style={{ textAlign: "right" }}>Umsatz</th>
                  </tr>
                </thead>
                <tbody>
                  {p.produkte.map((pr) => {
                    const gesamt = pr.gewonnen + pr.verloren;
                    return (
                      <tr key={pr.produkt} style={{ cursor: "default" }}>
                        <td className="haupt">{PRODUKT_TEXT[pr.produkt] ?? pr.produkt}</td>
                        <td className="zahl">{pr.gewonnen}</td>
                        <td className="zahl">{pr.verloren}</td>
                        <td className="zahl">
                          {gesamt === 0 ? "—" : `${Math.round((pr.gewonnen / gesamt) * 100)} %`}
                        </td>
                        <td className="zahl">{euro(pr.gewonnen_cents)}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            )}
          </div>
        </section>
      </div>
    </>
  );
}
