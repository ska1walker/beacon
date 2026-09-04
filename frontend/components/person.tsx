"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, ChevronsUpDown } from "lucide-react";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { initialenAusName } from "@/lib/format";
import { liesSitzplatz, setzeSitzplatz } from "@/lib/sitzplatz";
import type { Mitglied, Wer } from "@/lib/typen";

/**
 * Wer gerade arbeitet — unten in der Navigation, immer sichtbar.
 *
 * Vorher stand hier ein Schalter, der erst ab zwei Personen erschien.
 * Das war falsch herum gedacht: Die Frage „unter welchem Namen schreibe
 * ich das gerade" stellt sich auch allein, und sie stellt sich ständig,
 * weil Besitz, Zuordnung und Protokoll daran hängen. Der Kreis mit den
 * Initialen beantwortet sie, ohne dass man klicken muss.
 *
 * Gibt es mehr als eine Person, öffnet ein Klick die Wahl. Gibt es nur
 * eine, ist der Kreis ruhig und zeigt nur an.
 */
export function Personenanzeige() {
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

  const aktuell = wer.data;
  const mehrere = (mitglieder.data?.length ?? 0) > 1;
  const name = aktuell?.display_name ?? aktuell?.login_username ?? "…";

  function waehle(id: string) {
    setzeSitzplatz(id);
    setGewaehlt(id);
    setOffen(false);
    // Alles neu holen: Besitz, Zuordnung und „nur meine" hängen an der Person.
    client.invalidateQueries();
  }

  const inhalt = (
    <>
      <span className="person-kreis" aria-hidden="true">
        {initialenAusName(aktuell?.display_name ?? aktuell?.login_username)}
      </span>
      <span className="person-text">
        <span className="person-name">{name}</span>
        <span className="person-rolle">
          {aktuell?.sitzplatz_gewaehlt ? `Sitzplatz · ${aktuell.login_username}` : "angemeldet"}
        </span>
      </span>
      {mehrere && <ChevronsUpDown size={14} aria-hidden="true" className="person-pfeil" />}
    </>
  );

  return (
    <div className="person">
      {mehrere ? (
        <button
          type="button"
          className="person-knopf"
          aria-expanded={offen}
          aria-label={`Sie arbeiten als ${name}. Person wechseln`}
          onClick={() => setOffen((o) => !o)}
        >
          {inhalt}
        </button>
      ) : (
        <div className="person-knopf" data-still="true" title={`Sie arbeiten als ${name}`}>
          {inhalt}
        </div>
      )}

      {offen && mehrere && (
        <div className="person-liste" role="menu">
          <p className="person-erklaerung">
            Wer arbeitet gerade an diesem Rechner? Besitz, Zuordnung und Protokoll hängen
            daran. Es ist <strong>keine Anmeldung</strong> — der Olares-Zugang bleibt
            derselbe.
          </p>
          {mitglieder.data!.map((m) => (
            <button
              key={m.id}
              type="button"
              role="menuitem"
              className={`person-eintrag${aktuell?.user_id === m.id ? " aktiv" : ""}`}
              onClick={() => waehle(m.id)}
            >
              <span className="person-kreis klein" aria-hidden="true">
                {initialenAusName(m.display_name ?? m.olares_username)}
              </span>
              <span className="person-eintrag-text">
                <span>{m.display_name ?? m.olares_username}</span>
                {m.zugang === "olares" && <span className="person-art">eigener Zugang</span>}
              </span>
              {aktuell?.user_id === m.id && <Check size={13} aria-hidden="true" />}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
