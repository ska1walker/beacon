"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { Seitenkopf } from "@/components/seitenkopf";
import { Segmentliste } from "@/components/segmentliste";
import { FirmaAnlegen } from "@/components/firma-anlegen";

export default function FirmenSeite() {
  const router = useRouter();
  const [offen, setOffen] = useState(false);

  return (
    <>
      <Seitenkopf titel="Firmen">
        <button type="button" className="btn btn-primaer" onClick={() => setOffen(true)}>
          Firma anlegen
        </button>
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
