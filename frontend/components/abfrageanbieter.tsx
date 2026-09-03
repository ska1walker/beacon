"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState } from "react";

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
            retry: 1,
          },
        },
      }),
  );
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}
