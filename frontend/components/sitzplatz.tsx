"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, UserRound } from "lucide-react";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { liesSitzplatz, setzeSitzplatz } from "@/lib/sitzplatz";
import type { Mitglied, Wer } from "@/lib/typen";

/**
 * Die Sitzplatz-Wahl unten in der Navigation.
 *
 * Sie erscheint erst, wenn es mehr als eine Person gibt — allein wäre
 * sie ein Schalter ohne Wahl.
 */
export function Sitzplatzwahl() {
  const client = useQueryClient();
  const [offen, setOffen] = useState(false);
  const [gewaehlt, setGewaehlt] = useState<string | null>(null);

  useEffect(() => setGewaehlt(liesSitzplatz()), []);

  const mitglieder = useQuery({
    queryKey: ["mitglieder"],
    queryFn: () => api.get<Mitglied[]>("/api/mitglieder"),
  });

  const wer = useQuery({
    queryKey: ["wer", gewaehlt],
    queryFn: () => api.get<Wer>("/api/mitglieder/wer"),
  });

  if (!mitglieder.data || mitglieder.data.length < 2) return null;

  const aktuell = wer.data;

  function waehle(id: string) {
    setzeSitzplatz(id);
    setGewaehlt(id);
    setOffen(false);
    // Alles neu holen: Besitz, Zuordnung und „meine" hängen an der Person.
    client.invalidateQueries();
  }

  return (
    <div className="sitzplatz">
      <button
        type="button"
        className="sitzplatz-knopf"
        aria-expanded={offen}
        onClick={() => setOffen((o) => !o)}
      >
        <UserRound size={14} aria-hidden="true" />
        <span className="sitzplatz-name">{aktuell?.display_name ?? "Sitzplatz"}</span>
      </button>

      {offen && (
        <div className="sitzplatz-liste" role="menu">
          <p className="sitzplatz-erklaerung">
            Wer arbeitet gerade an diesem Rechner? Besitz, Zuordnung und Protokoll hängen
            daran. Es ist <strong>keine Anmeldung</strong> — der Olares-Zugang bleibt
            derselbe.
          </p>
          {mitglieder.data.map((m) => (
            <button
              key={m.id}
              type="button"
              role="menuitem"
              className={`sitzplatz-eintrag${aktuell?.user_id === m.id ? " aktiv" : ""}`}
              onClick={() => waehle(m.id)}
            >
              <span>{m.display_name ?? m.olares_username}</span>
              {m.zugang === "olares" && <span className="sitzplatz-art">eigener Zugang</span>}
              {aktuell?.user_id === m.id && <Check size={13} aria-hidden="true" />}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
