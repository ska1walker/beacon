"use client";

// Ein Knopf, der mehr als eine Sache kann.
//
// Gedacht für den Fall, dass eine Seite **einen** offensichtlichen
// Hauptweg hat und einen zweiten, den man selten braucht und trotzdem
// finden muss: Kontakt anlegen — oder eben hundert auf einmal aus einer
// Datei. Der Import lag zuerst nur in den Einstellungen; dort sucht ihn
// niemand, der gerade auf die leere Kontaktliste schaut.
//
// Der erste Eintrag ist die Vorgabe: Ein Klick auf den Knopf selbst führt
// ihn aus, ohne das Menü zu öffnen. Wer nur anlegen will, merkt vom Menü
// nichts.

import { ChevronDown } from "lucide-react";
import { useEffect, useId, useRef, useState } from "react";

export type Menuepunkt = {
  text: string;
  hinweis?: string;
  onWahl: () => void;
};

export function Knopfmenue({
  text,
  eintraege,
}: {
  text: string;
  eintraege: Menuepunkt[];
}) {
  const [offen, setOffen] = useState(false);
  const wurzel = useRef<HTMLDivElement>(null);
  const id = useId();

  useEffect(() => {
    if (!offen) return;
    function zu(e: MouseEvent | KeyboardEvent) {
      if (
        e instanceof KeyboardEvent
          ? e.key === "Escape"
          : !wurzel.current?.contains(e.target as Node)
      ) {
        setOffen(false);
      }
    }
    document.addEventListener("mousedown", zu);
    document.addEventListener("keydown", zu);
    return () => {
      document.removeEventListener("mousedown", zu);
      document.removeEventListener("keydown", zu);
    };
  }, [offen]);

  return (
    <div className="knopfmenue" ref={wurzel}>
      <button
        type="button"
        className="btn btn-primaer knopfmenue-haupt"
        onClick={() => eintraege[0]?.onWahl()}
      >
        {text}
      </button>
      <button
        type="button"
        className="btn btn-primaer knopfmenue-pfeil"
        aria-haspopup="menu"
        aria-expanded={offen}
        aria-controls={id}
        aria-label={`${text} — weitere Wege`}
        onClick={() => setOffen((o) => !o)}
      >
        <ChevronDown size={16} aria-hidden="true" />
      </button>

      {offen && (
        <div className="knopfmenue-feld" id={id} role="menu">
          {eintraege.map((e) => (
            <button
              key={e.text}
              type="button"
              role="menuitem"
              className="knopfmenue-punkt"
              onClick={() => {
                setOffen(false);
                e.onWahl();
              }}
            >
              <span>{e.text}</span>
              {e.hinweis && <span className="knopfmenue-hinweis">{e.hinweis}</span>}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
