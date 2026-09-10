"use client";

// Die Kopfleiste — die zwei Dinge, die man von überall tut.
//
// Suchen und Anlegen gehören nicht in die Navigationsspalte. Die Suche
// geht über den ganzen Bestand und beantwortet Fragen; zwischen den
// Bereichen stehend las sie sich wie ein Filter für die Bereiche.
// Anlegen gab es nur je Seite — wer auf dem Lead-Brett stand und einen
// Kontakt brauchte, musste erst wechseln.
//
// Bewusst **nur** diese zwei. HubSpots Leiste ist voll, weil dort acht
// Produkte, Telefonie und Hinweise unterzubringen sind. Beacon ist ein
// Produkt für ein kleines Team; wer den Behälter kopiert, ohne den
// Inhalt zu haben, bekommt eine leere Leiste.
//
// Das Konto und der Datenweg-Nachweis bleiben unten in der Spalte. Der
// Nachweis ist kein Bedienelement, sondern die Aussage des Produkts —
// oben würde daraus ein Symbol neben anderen, und der Satz wäre weg.

import { ChevronDown, Plus } from "lucide-react";
import Link from "next/link";
import { useEffect, useId, useRef, useState } from "react";
import { neuPfad, NEU_ZIELE } from "@/lib/neu";
import { Marke } from "@/components/marke";
import { Klappschalter } from "@/components/navigation";
import { Suchfeld } from "@/components/suche";

function NeuMenue() {
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
        className="btn btn-primaer kopf-neu"
        aria-haspopup="menu"
        aria-expanded={offen}
        aria-controls={id}
        onClick={() => setOffen((o) => !o)}
      >
        <Plus size={16} aria-hidden="true" />
        <span className="kopf-neu-text">Neu</span>
        <ChevronDown size={14} aria-hidden="true" />
      </button>

      {offen && (
        <div className="knopfmenue-feld" id={id} role="menu">
          {NEU_ZIELE.map((z) => (
            <Link
              key={z.pfad}
              role="menuitem"
              className="knopfmenue-punkt"
              href={neuPfad(z.pfad)}
              onClick={() => setOffen(false)}
            >
              {z.text}
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}

export function Kopfleiste({
  eingeklappt,
  klappen,
}: {
  eingeklappt: boolean | null;
  klappen: () => void;
}) {
  return (
    <header className="kopfleiste">
      {/* Die Marke sitzt über der Spalte, nicht darin: So beginnt die
          Navigation mit Navigation, und die Leiste hat einen Anfang. */}
      <div className="kopfleiste-marke">
        <Link href="/" className="marke" aria-label="AImighty Beacon — zur Startseite">
          <Marke />
          <span className="marke-produkt" aria-hidden="true">Beacon</span>
        </Link>
        <Klappschalter eingeklappt={eingeklappt} umschalten={klappen} />
      </div>

      <div className="kopfleiste-suche">
        <Suchfeld />
      </div>

      <NeuMenue />
    </header>
  );
}

