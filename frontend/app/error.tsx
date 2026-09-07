"use client";

import { AlertTriangle } from "lucide-react";
import { useEffect } from "react";
import { fehlerMelden } from "@/components/fehlermelder";

/**
 * Die Seite, die Next zeigt, wenn ein Bauteil beim Rendern zerbricht.
 *
 * Statt „Application error: a client-side exception has occurred“ steht
 * hier ein Satz, den man lesen kann — und der Fehler geht mit Stack an die
 * Box, wo ihn jemand finden kann.
 */
export default function Fehlerseite({ error, reset }: { error: Error & { digest?: string }; reset: () => void }) {
  useEffect(() => {
    fehlerMelden(error);
  }, [error]);

  return (
    <div className="leerzustand" role="alert">
      <AlertTriangle size={24} aria-hidden="true" />
      <h4>Etwas ist schiefgelaufen.</h4>
      <p>Der Fehler wurde auf der Box protokolliert. Laden Sie die Seite neu — bleibt es dabei, hilft das Protokoll des Backends weiter.</p>
      <p style={{ fontSize: "0.8125rem", color: "var(--am-text-gedaempft)", marginTop: "var(--am-raum-2)" }}>
        {error.name}: {error.message}
      </p>
      <div className="btn-reihe" style={{ justifyContent: "center", marginTop: "var(--am-raum-4)" }}>
        <button type="button" className="btn btn-primaer" onClick={() => reset()}>
          Neu laden
        </button>
      </div>
    </div>
  );
}
