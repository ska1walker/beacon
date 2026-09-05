"use client";

import { Info } from "lucide-react";
import { useEffect, useId, useRef, useState } from "react";

/**
 * Ein Satz für alle, der Rest hinter einem Symbol.
 *
 * Einstellungen erklären sich in ein, zwei Sätzen — wer wissen will, was
 * dahintersteckt, klappt es auf. Die lange Fassung bleibt so erhalten,
 * ohne dass jeder Block zum Aufsatz wird.
 */
export function Erklaerung({ kurz, lang }: { kurz: React.ReactNode; lang?: React.ReactNode }) {
  const [offen, setOffen] = useState(false);
  const id = useId();
  const wurzel = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!offen) return;
    function zu(e: MouseEvent | KeyboardEvent) {
      if (e instanceof KeyboardEvent ? e.key === "Escape" : !wurzel.current?.contains(e.target as Node)) setOffen(false);
    }
    document.addEventListener("mousedown", zu);
    document.addEventListener("keydown", zu);
    return () => {
      document.removeEventListener("mousedown", zu);
      document.removeEventListener("keydown", zu);
    };
  }, [offen]);

  return (
    <div className="erklaerung" ref={wurzel}>
      <p className="erklaerung-kurz">
        {kurz}
        {lang && (
          <button
            type="button"
            className="erklaerung-knopf"
            aria-label="Mehr dazu"
            aria-expanded={offen}
            aria-controls={id}
            onClick={() => setOffen((o) => !o)}
          >
            <Info size={15} aria-hidden="true" />
          </button>
        )}
      </p>
      {lang && offen && (
        <div className="erklaerung-lang" id={id} role="note">
          {lang}
        </div>
      )}
    </div>
  );
}
