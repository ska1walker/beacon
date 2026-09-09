"use client";

// Der Import hat eine eigene Seite, keinen Dialog.
//
// Er hat drei Schritte, eine Zuordnungstabelle mit einer Zeile je Spalte
// der Datei und eine Bilanz mit aufklappbaren Gründen. Das ist mehr, als
// in ein Fenster über der Liste passt, und man will dabei scrollen
// können, ohne dass darunter etwas wegrutscht.

import { useSearchParams } from "next/navigation";
import { Suspense } from "react";
import { Seitenkopf } from "@/components/seitenkopf";
import { Einfuhrblock } from "@/components/einfuhr";
import type { Objektart } from "@/lib/typen";

function Inhalt() {
  const gewaehlt = useSearchParams().get("entity");
  const objekt: Objektart | undefined =
    gewaehlt === "companies" ? "companies" : gewaehlt === "contacts" ? "contacts" : undefined;

  return (
    <>
      <Seitenkopf
        titel="Import"
        pfad={
          objekt === "companies"
            ? { text: "← Firmen", href: "/firmen" }
            : { text: "← Kontakte", href: "/kontakte" }
        }
      />
      <div style={{ padding: "0 var(--am-raum-8) var(--am-raum-16)", maxWidth: 900 }}>
        <Einfuhrblock vorwahl={objekt} />
      </div>
    </>
  );
}

export default function ImportSeite() {
  // `useSearchParams` verlangt eine Grenze, sonst rendert Next die ganze
  // Seite zur Anfragezeit statt beim Bauen.
  return (
    <Suspense fallback={null}>
      <Inhalt />
    </Suspense>
  );
}
