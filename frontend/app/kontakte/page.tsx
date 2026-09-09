"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { Seitenkopf } from "@/components/seitenkopf";
import { Knopfmenue } from "@/components/knopfmenue";
import { Segmentliste } from "@/components/segmentliste";
import { KontaktAnlegen } from "@/components/kontakt-anlegen";

export default function KontakteSeite() {
  const router = useRouter();
  const [offen, setOffen] = useState(false);

  return (
    <>
      <Seitenkopf titel="Kontakte">
        {/* Der zweite Weg gehört neben den ersten: Wer auf eine leere
            Liste schaut, sucht den Import nicht in den Einstellungen. */}
        <Knopfmenue
          text="Kontakt anlegen"
          eintraege={[
            { text: "Neu anlegen", onWahl: () => setOffen(true) },
            {
              text: "Aus CSV importieren",
              hinweis: "Mehrere auf einmal, aus einer Tabelle",
              onWahl: () => router.push("/import?entity=contacts"),
            },
          ]}
        />
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
