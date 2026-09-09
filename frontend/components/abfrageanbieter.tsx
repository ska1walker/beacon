"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState } from "react";
import { ApiFehler } from "@/lib/api";

/**
 * Wann sich ein zweiter Versuch lohnt.
 *
 * Nach einem Neustart der Box ist das Frontend eher da als das Backend.
 * Der Next-Proxy findet dann noch niemanden und antwortet **selbst** mit
 * 500 — im Backend-Log steht nichts. Auf dem Bildschirm stand „Anfrage
 * fehlgeschlagen (500)", und erst ein Neuladen half. Genau dafür sind
 * Wiederholungen da: Das Backend braucht ein paar Sekunden, nicht einen
 * Menschen mit F5.
 *
 * **Nicht** wiederholt wird alles Vierhundertere: Ein 401 gehört zur
 * Anmeldung, ein 403 zur Rolle, ein 404 zum Datensatz. Sie fielen beim
 * dritten Versuch nicht anders aus und verzögerten nur die Meldung.
 */
function nochmal(versuch: number, fehler: unknown): boolean {
  if (fehler instanceof ApiFehler && fehler.status >= 400 && fehler.status < 500) return false;
  return versuch < 4;
}

export function Abfrageanbieter({ children }: { children: React.ReactNode }) {
  // Im State, nicht im Modul: Ein Client je Baum. Auf Modulebene teilten
  // sich beim Server-Rendern sonst mehrere Anfragen denselben Zwischen-
  // speicher, und Daten der einen Sitzung landeten in der anderen.
  const [client] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            staleTime: 30_000,
            refetchOnWindowFocus: false,
            retry: nochmal,
            // 0,4 s, 0,8 s, 1,6 s, 3,2 s — nach gut sechs Sekunden steht
            // das Backend, und niemand hat etwas gemerkt.
            retryDelay: (versuch) => Math.min(400 * 2 ** versuch, 4000),
          },
        },
      }),
  );
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}
