"use client";

// Das Tor — die einzige Seite, die jemand ohne Zugang zu sehen bekommt.
//
// Deshalb sagt sie so wenig wie möglich: keine Liste von Konten, kein
// „diesen Namen gibt es nicht", keine Registrierung. Wer hier steht und
// nicht hineingehört, soll nicht einmal erfahren, wer hineingehört.

import { AlertCircle } from "lucide-react";
import { Marke } from "@/components/marke";

export function Tor({
  titel,
  unter,
  fehler,
  laeuft,
  knopf,
  onSenden,
  children,
  fuss,
}: {
  titel: string;
  unter?: React.ReactNode;
  fehler?: string | null;
  laeuft?: boolean;
  knopf: string;
  onSenden: () => void;
  children: React.ReactNode;
  fuss?: React.ReactNode;
}) {
  return (
    <main className="tor">
      <form
        className="tor-karte"
        onSubmit={(e) => {
          e.preventDefault();
          onSenden();
        }}
      >
        <div className="tor-marke">
          <Marke />
          <span className="marke-produkt">Beacon</span>
        </div>

        <h1 className="tor-titel">{titel}</h1>
        {unter && <p className="tor-unter">{unter}</p>}

        {children}

        {/* Farbe trägt die Aussage nie allein: Zeichen und Satz dazu. */}
        {fehler && (
          <p className="feld-fehlertext" role="alert">
            <AlertCircle size={14} aria-hidden="true" />
            {fehler}
          </p>
        )}

        <button type="submit" className="btn btn-primaer tor-knopf" disabled={laeuft}>
          {laeuft ? "Einen Moment …" : knopf}
        </button>

        {fuss && <p className="tor-fuss">{fuss}</p>}
      </form>
    </main>
  );
}
