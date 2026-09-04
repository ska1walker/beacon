"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { Seitenkopf } from "@/components/seitenkopf";
import { Segmentliste } from "@/components/segmentliste";
import { KontaktAnlegen } from "@/components/kontakt-anlegen";

export default function KontakteSeite() {
  const router = useRouter();
  const [offen, setOffen] = useState(false);

  return (
    <>
      <Seitenkopf titel="Kontakte">
        <button type="button" className="btn btn-primaer" onClick={() => setOffen(true)}>
          Kontakt anlegen
        </button>
      </Seitenkopf>

      {offen && (
        <KontaktAnlegen
          beiSchliessen={() => setOffen(false)}
          beiErfolg={(id) => {
            setOffen(false);
            router.push(`/kontakte/${id}`);
          }}
        />
      )}

      <Segmentliste
        entity="contacts"
        basisPfad="/kontakte"
        suchePlatzhalter="Name, E-Mail oder Firma"
        leerTitel="Kein Kontakt gefunden"
        leerText="Entweder ist der Filter zu eng, oder hier ist noch niemand angelegt."
        stapelfelder={[
          { schluessel: "lifecycle_stage", text: "Stufe" },
          { schluessel: "owner_id", text: "Besitzer" },
          { schluessel: "source", text: "Herkunft" },
        ]}
      />
    </>
  );
}
