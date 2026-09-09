"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { favoritUmschalten } from "@/lib/navigation";
import { liesSitzplatz } from "@/lib/sitzplatz";
import type { Wer } from "@/lib/typen";

/**
 * Wer gerade handelt — mit dem gewählten Sitzplatz als Teil des Schlüssels,
 * damit ein Wechsel der Person auch die Antwort wechselt.
 */
export function useWer() {
  const [gewaehlt, setGewaehlt] = useState<string | null>(null);
  useEffect(() => setGewaehlt(liesSitzplatz()), []);
  const wer = useQuery({
    queryKey: ["wer", gewaehlt],
    queryFn: () => api.get<Wer>("/api/mitglieder/wer"),
  });
  return { wer, gewaehlt, setGewaehlt };
}

/**
 * Die Favoriten der handelnden Person — sofort sichtbar, dann gespeichert.
 *
 * Das Lesezeichen wirkt, bevor der Server geantwortet hat; scheitert das
 * Speichern, springt er zurück. Gespeichert wird am Menschen auf der Box,
 * nicht im Browser: Auf jedem Gerät dieselben Favoriten.
 */
export function useFavoriten() {
  const client = useQueryClient();
  const { wer, gewaehlt } = useWer();
  const schluessel = ["wer", gewaehlt];
  const favoriten = wer.data?.einstellungen?.favoriten ?? [];

  const speichern = useMutation({
    mutationFn: (neu: string[]) => api.patch<Wer>("/api/mitglieder/wer/einstellungen", { favoriten: neu }),
    onMutate: async (neu) => {
      await client.cancelQueries({ queryKey: schluessel });
      const vorher = client.getQueryData<Wer>(schluessel);
      if (vorher) client.setQueryData<Wer>(schluessel, { ...vorher, einstellungen: { ...vorher.einstellungen, favoriten: neu } });
      return { vorher };
    },
    onError: (_fehler, _neu, kontext) => {
      if (kontext?.vorher) client.setQueryData(schluessel, kontext.vorher);
    },
    onSettled: () => client.invalidateQueries({ queryKey: ["wer"] }),
  });

  return {
    favoriten,
    geladen: wer.isSuccess,
    // Vom Stand im Zwischenspeicher aus, nicht vom Stand beim Zeichnen: Zwei
    // schnelle Klicks sollen zwei Favoriten ergeben, nicht den zweiten allein.
    umschalten: (pfad: string) => {
      const aktuell = client.getQueryData<Wer>(schluessel)?.einstellungen?.favoriten ?? favoriten;
      speichern.mutate(favoritUmschalten(aktuell, pfad));
    },
  };
}
