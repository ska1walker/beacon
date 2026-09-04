"use client";

import { Check, ChevronDown, X } from "lucide-react";
import { useCallback, useEffect, useId, useLayoutEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";

/**
 * Mehrere Werte aus einer festen Liste wählen.
 *
 * Die naheliegende Lösung — eine Reihe Kontrollkästchen — hält bis etwa
 * sieben Werten und wird danach zur Tapete: Wer aus vierzig Branchen drei
 * sucht, liest vierzig. HubSpot löst das mit einem Feld, das aussieht wie
 * ein Eingabefeld, sich aber wie eine Liste verhält, und genau das steht
 * hier:
 *
 * - **Das Gewählte steht im Feld**, als abnehmbare Plättchen. Man sieht
 *   die Antwort, ohne die Liste zu öffnen.
 * - **Getippt wird gesucht, nicht geschrieben.** Bei vierzig Optionen ist
 *   Tippen der schnellste Weg zur richtigen; bei vier stört es nicht.
 * - **Die Liste bleibt offen.** Wer drei Werte setzen will, soll nicht
 *   dreimal aufklappen — das ist der eine Unterschied zur Einfachauswahl,
 *   und er entscheidet, ob sich das Feld gut anfühlt.
 *
 * Tastatur: ↓ öffnet, ↑/↓ wandert, Eingabe schaltet um, Esc schließt,
 * Rücktaste bei leerer Suche nimmt das letzte Plättchen weg.
 */
export function Mehrfachauswahl({
  optionen,
  gewaehlt,
  beiAendern,
  id,
  platzhalter = "Auswählen …",
  ariaLabel,
  kompakt = false,
  deaktiviert = false,
}: {
  optionen: { wert: string; text: string }[];
  gewaehlt: string[];
  beiAendern: (neu: string[]) => void;
  id?: string;
  platzhalter?: string;
  ariaLabel?: string;
  kompakt?: boolean;
  deaktiviert?: boolean;
}) {
  const eigeneId = useId();
  const feldId = id ?? `mehrfach-${eigeneId}`;
  const listenId = `${feldId}-liste`;

  const [offen, setOffen] = useState(false);
  const [suche, setSuche] = useState("");
  const [aktiv, setAktiv] = useState(0);

  const huelle = useRef<HTMLDivElement>(null);
  const tafel = useRef<HTMLDivElement>(null);
  const eingabe = useRef<HTMLInputElement>(null);
  const liste = useRef<HTMLUListElement>(null);

  // Die Tafel hängt am Körper, nicht am Feld. Sonst schneidet sie die
  // Karte ab, in der das Feld sitzt: Ein Block mit runden Ecken hat
  // `overflow: hidden`, und damit endet jedes Aufklappfeld am Kartenrand.
  const [lage, setLage] = useState<{ top: number; left: number; breite: number } | null>(null);

  const messen = useCallback(() => {
    const r = huelle.current?.getBoundingClientRect();
    if (!r) return;
    const hoehe = tafel.current?.offsetHeight ?? 260;
    const darunter = window.innerHeight - r.bottom;
    // Nach oben klappen, wenn unten kein Platz ist — aber nur, wenn oben
    // mehr ist. Sonst bliebe sie oben genauso abgeschnitten.
    const nachOben = darunter < hoehe + 8 && r.top > darunter;
    setLage({
      top: nachOben ? Math.max(8, r.top - hoehe - 4) : r.bottom + 4,
      left: r.left,
      breite: Math.max(r.width, 240),
    });
  }, []);

  useLayoutEffect(() => {
    if (!offen) return setLage(null);
    messen();
    window.addEventListener("scroll", messen, true);
    window.addEventListener("resize", messen);
    return () => {
      window.removeEventListener("scroll", messen, true);
      window.removeEventListener("resize", messen);
    };
  }, [offen, messen]);

  // Die Höhe steht erst, wenn die gefilterte Liste gezeichnet ist.
  useLayoutEffect(() => {
    if (offen) messen();
  }, [offen, messen, suche]);

  // Die Suche wird beim Öffnen und Schließen geleert: Ein stehengebliebener
  // Suchbegriff versteckt beim nächsten Öffnen die halbe Liste, und niemand
  // sucht den Grund im Feld darüber.
  useEffect(() => {
    if (!offen) setSuche("");
    else eingabe.current?.focus();
  }, [offen]);

  useEffect(() => {
    if (!offen) return;
    function daneben(e: MouseEvent) {
      const ziel = e.target as Node;
      if (huelle.current?.contains(ziel) || tafel.current?.contains(ziel)) return;
      setOffen(false);
    }
    document.addEventListener("mousedown", daneben);
    return () => document.removeEventListener("mousedown", daneben);
  }, [offen]);

  const gefiltert = useMemo(() => {
    const s = suche.trim().toLowerCase();
    return s ? optionen.filter((o) => o.text.toLowerCase().includes(s)) : optionen;
  }, [optionen, suche]);

  useEffect(() => {
    setAktiv((a) => Math.min(a, Math.max(0, gefiltert.length - 1)));
  }, [gefiltert.length]);

  // Der aktive Eintrag muss sichtbar bleiben, sonst wandert die Auswahl
  // beim Blättern mit der Tastatur aus dem Bild.
  useEffect(() => {
    if (!offen) return;
    liste.current
      ?.querySelector<HTMLElement>(`[data-i="${aktiv}"]`)
      ?.scrollIntoView({ block: "nearest" });
  }, [aktiv, offen]);

  const gesetzt = new Set(gewaehlt);
  const textVon = (w: string) => optionen.find((o) => o.wert === w)?.text ?? w;

  function umschalten(wert: string) {
    beiAendern(
      gesetzt.has(wert)
        ? gewaehlt.filter((g) => g !== wert)
        : // Die Reihenfolge der Definition, nicht die des Anklickens:
          // Zwei Datensätze mit derselben Auswahl sollen gleich aussehen.
          optionen.map((o) => o.wert).filter((w) => w === wert || gesetzt.has(w)),
    );
  }

  function taste(e: React.KeyboardEvent) {
    if (deaktiviert) return;
    if (e.key === "ArrowDown" || (e.key === "ArrowUp" && !offen)) {
      e.preventDefault();
      if (!offen) return setOffen(true);
      setAktiv((a) => (a + 1) % Math.max(1, gefiltert.length));
      return;
    }
    if (e.key === "ArrowUp") {
      e.preventDefault();
      setAktiv((a) => (a - 1 + gefiltert.length) % Math.max(1, gefiltert.length));
      return;
    }
    if (e.key === "Enter") {
      e.preventDefault();
      if (!offen) return setOffen(true);
      const o = gefiltert[aktiv];
      if (o) umschalten(o.wert);
      return;
    }
    if (e.key === "Escape" && offen) {
      e.preventDefault();
      setOffen(false);
      return;
    }
    if (e.key === "Backspace" && suche === "" && gewaehlt.length > 0) {
      beiAendern(gewaehlt.slice(0, -1));
    }
  }

  return (
    <div className="mehrfach" ref={huelle} data-kompakt={kompakt ? "true" : undefined}>
      {/* eslint-disable-next-line jsx-a11y/click-events-have-key-events, jsx-a11y/no-static-element-interactions */}
      <div
        className="mehrfach-feld"
        data-offen={offen ? "true" : undefined}
        data-leer={gewaehlt.length === 0 ? "true" : undefined}
        onMouseDown={(e) => {
          // Ein Klick auf ein Plättchen soll das Feld nicht öffnen.
          if ((e.target as HTMLElement).closest("[data-plaettchen]")) return;
          if (!deaktiviert) {
            setOffen(true);
            eingabe.current?.focus();
          }
        }}
      >
        {gewaehlt.map((w) => (
          <span className="mehrfach-plaettchen" key={w} data-plaettchen="">
            {textVon(w)}
            {!deaktiviert && (
              <button
                type="button"
                aria-label={`${textVon(w)} entfernen`}
                onClick={() => beiAendern(gewaehlt.filter((g) => g !== w))}
              >
                <X size={12} aria-hidden="true" />
              </button>
            )}
          </span>
        ))}

        <input
          ref={eingabe}
          id={feldId}
          className="mehrfach-suche"
          role="combobox"
          aria-expanded={offen}
          aria-controls={listenId}
          aria-autocomplete="list"
          aria-label={ariaLabel}
          aria-activedescendant={offen && gefiltert[aktiv] ? `${listenId}-${aktiv}` : undefined}
          autoComplete="off"
          disabled={deaktiviert}
          placeholder={gewaehlt.length === 0 ? platzhalter : ""}
          value={suche}
          onChange={(e) => {
            setSuche(e.target.value);
            setOffen(true);
            setAktiv(0);
          }}
          onKeyDown={taste}
        />

        <ChevronDown size={16} className="mehrfach-pfeil" aria-hidden="true" />
      </div>

      {offen &&
        typeof document !== "undefined" &&
        createPortal(
          <div
            className="mehrfach-tafel"
            ref={tafel}
            style={
              lage
                ? { top: lage.top, left: lage.left, width: lage.breite }
                : { opacity: 0, pointerEvents: "none" }
            }
          >
          <ul className="mehrfach-liste" id={listenId} role="listbox" aria-multiselectable ref={liste}>
            {gefiltert.length === 0 && (
              <li className="mehrfach-leer" role="presentation">
                {optionen.length === 0
                  ? "Für diese Eigenschaft ist noch kein Wert hinterlegt."
                  : `Nichts passt zu „${suche.trim()}“.`}
              </li>
            )}
            {gefiltert.map((o, i) => {
              const an = gesetzt.has(o.wert);
              return (
                <li
                  key={o.wert}
                  id={`${listenId}-${i}`}
                  data-i={i}
                  role="option"
                  aria-selected={an}
                  data-aktiv={i === aktiv ? "true" : undefined}
                  className="mehrfach-eintrag"
                  onMouseEnter={() => setAktiv(i)}
                  onMouseDown={(e) => {
                    // Verhindert, dass das Eingabefeld den Fokus verliert —
                    // sonst schließt die Tafel vor dem Klick.
                    e.preventDefault();
                    umschalten(o.wert);
                  }}
                >
                  <span className="mehrfach-kasten" aria-hidden="true">
                    {an && <Check size={12} />}
                  </span>
                  {o.text}
                </li>
              );
            })}
          </ul>

            {(gewaehlt.length > 0 || optionen.length > 0) && (
              <div className="mehrfach-fuss">
                <span>
                  {gewaehlt.length} von {optionen.length} gewählt
                </span>
                {gewaehlt.length > 0 && (
                  <button
                    type="button"
                    onMouseDown={(e) => {
                      e.preventDefault();
                      beiAendern([]);
                    }}
                  >
                    Auswahl leeren
                  </button>
                )}
              </div>
            )}
          </div>,
          document.body,
        )}
    </div>
  );
}

/** Gewählte Werte als Plättchen, nur zum Lesen — für Tabellen und Karten. */
export function Mehrfachplaettchen({ werte, grenze = 3 }: { werte: string[]; grenze?: number }) {
  if (werte.length === 0) return <span className="leerwert">—</span>;
  const sichtbar = werte.slice(0, grenze);
  const rest = werte.length - sichtbar.length;
  return (
    <span className="mehrfach-anzeige">
      {sichtbar.map((w) => (
        <span className="mehrfach-plaettchen still" key={w}>
          {w}
        </span>
      ))}
      {rest > 0 && (
        <span className="mehrfach-mehr" title={werte.slice(grenze).join(", ")}>
          +{rest}
        </span>
      )}
    </span>
  );
}
