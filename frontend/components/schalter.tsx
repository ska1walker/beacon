"use client";

import { useId } from "react";

/**
 * Ein Schalter für Einstellungen, die an oder aus sind.
 *
 * Ein Häkchen fragt „trifft zu?“, ein Schalter sagt „läuft“. Für
 * „regelmäßig abholen“ oder „automatisch vorbereiten“ ist das zweite
 * gemeint — und ein nacktes Browser-Häkchen in Feldgröße war ohnehin
 * kein Anblick. Links der Schalter, rechts der Satz, darunter das
 * Kleingedruckte; die ganze Zeile ist klickbar.
 */
export function Schalter({
  an,
  umschalten,
  text,
  hinweis,
  id,
}: {
  an: boolean;
  umschalten: (an: boolean) => void;
  text: React.ReactNode;
  hinweis?: React.ReactNode;
  id?: string;
}) {
  const eigene = useId();
  const kennung = id ?? eigene;
  return (
    <div className="schalter-zeile">
      <button
        type="button"
        role="switch"
        id={kennung}
        aria-checked={an}
        className={`schalter${an ? " an" : ""}`}
        onClick={() => umschalten(!an)}
      >
        <span className="schalter-knauf" aria-hidden="true" />
      </button>
      <label htmlFor={kennung} className="schalter-text">
        <span>{text}</span>
        {hinweis && <span className="schalter-hinweis">{hinweis}</span>}
      </label>
    </div>
  );
}
