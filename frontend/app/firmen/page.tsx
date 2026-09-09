"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { Seitenkopf } from "@/components/seitenkopf";
import { Knopfmenue } from "@/components/knopfmenue";
import { Segmentliste } from "@/components/segmentliste";
import { FirmaAnlegen } from "@/components/firma-anlegen";

export default function FirmenSeite() {
  const router = useRouter();
  const [offen, setOffen] = useState(false);

  return (
    <>
      <Seitenkopf titel="Firmen">
        {/* Der zweite Weg gehört neben den ersten: Wer auf eine leere
            Liste schaut, sucht den Import nicht in den Einstellungen. */}
        <Knopfmenue
          text="Firma anlegen"
          eintraege={[
            { text: "Neu anlegen", onWahl: () => setOffen(true) },
            {
              text: "Aus CSV importieren",
              hinweis: "Mehrere auf einmal, aus einer Tabelle",
              onWahl: () => router.push("/import?entity=companies"),
            },
          ]}
        />
      </Seitenkopf>

      {offen && (
        <FirmaAnlegen
          beiSchliessen={() => setOffen(false)}
          beiErfolg={(id) => {
            setOffen(false);
            router.push(`/firmen/${id}`);
          }}
        />
      )}

      <Segmentliste
        entity="companies"
        basisPfad="/firmen"
        suchePlatzhalter="Name, Domain oder Ort"
        leerTitel="Keine Firma gefunden"
        leerText="Entweder ist der Filter zu eng, oder hier ist noch nichts angelegt."
        stapelfelder={[
          { schluessel: "lifecycle_stage", text: "Stufe" },
          { schluessel: "owner_id", text: "Besitzer" },
          { schluessel: "industry", text: "Branche" },
          { schluessel: "source", text: "Herkunft" },
        ]}
      />
    </>
  );
}
