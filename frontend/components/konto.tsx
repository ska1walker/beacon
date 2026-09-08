"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, ChevronsUpDown, Globe, Server } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";
import { nachweis } from "@/lib/datenwege";
import { initialenAusName } from "@/lib/format";
import { setzeSitzplatz } from "@/lib/sitzplatz";
import type { Mitglied, OrgSettings } from "@/lib/typen";
import { useWer } from "@/lib/wer";
import { Darstellungsschalter } from "@/components/darstellung";

/**
 * Der Fuß der Navigation: eine Zeile für das Konto, eine für den Nachweis.
 *
 * Vorher standen hier drei Dinge nebeneinander, die nichts miteinander zu
 * tun haben — eine Personenkarte mit Rahmen, ein Dreifach-Schalter für die
 * Darstellung und der Satz „läuft auf dieser Box". Die Karte wog mehr als
 * jeder Navigationseintrag und sagte „angemeldet", was man ohnehin sieht;
 * der Schalter stand dauerhaft da für eine Entscheidung, die man einmal
 * trifft; und der Satz war eine Zusage ohne Beleg, die seit dem ersten
 * fremden Endpunkt schlicht nicht mehr stimmte.
 *
 * Jetzt: eine ruhige Zeile, die ein Menü öffnet (Sitzplatz, Darstellung),
 * und darunter der gemessene Stand — oder nichts.
 */

function useMitglieder() {
  return useQuery({
    queryKey: ["mitglieder"],
    queryFn: () => api.get<Mitglied[]>("/api/mitglieder"),
  });
}

export function Kontozeile() {
  const client = useQueryClient();
  const aktuell = usePathname();
  const [offen, setOffen] = useState(false);
  const knopf = useRef<HTMLButtonElement>(null);
  const { wer, setGewaehlt } = useWer();
  const mitglieder = useMitglieder();

  useEffect(() => {
    setOffen(false);
  }, [aktuell]);

  const person = wer.data;
  const name = person?.display_name ?? person?.login_username ?? "…";

  function waehle(id: string) {
    setzeSitzplatz(id);
    setGewaehlt(id);
    setOffen(false);
    // Alles neu holen: Besitz, Zuordnung und „nur meine" hängen an der Person.
    client.invalidateQueries();
  }

  function schliessen(fokus = true) {
    setOffen(false);
    if (fokus) knopf.current?.focus();
  }

  return (
    <div className="person">
      <button
        ref={knopf}
        type="button"
        className="person-knopf"
        aria-expanded={offen}
        aria-haspopup="dialog"
        aria-controls="konto-menue"
        aria-label={`Sie arbeiten als ${name}. Konto und Darstellung`}
        onClick={() => setOffen((o) => !o)}
      >
        <span className="person-kreis" aria-hidden="true">
          {initialenAusName(person?.display_name ?? person?.login_username)}
        </span>
        <span className="person-text">
          <span className="person-name">{name}</span>
          {/* Nur wenn ein Sitzplatz gewählt ist, sagt die zweite Zeile etwas. */}
          {person?.sitzplatz_gewaehlt && (
            <span className="person-rolle">Sitzplatz · {person.login_username}</span>
          )}
        </span>
        <ChevronsUpDown size={14} aria-hidden="true" className="person-pfeil" />
      </button>

      {offen && (
        <Kontomenue
          mitglieder={mitglieder.data ?? []}
          aktuellId={person?.user_id}
          waehle={waehle}
          schliessen={schliessen}
          knopf={knopf}
        />
      )}
    </div>
  );
}

/**
 * Das Menü klappt nach oben. Es schließt bei Escape, bei einem Klick
 * außerhalb und beim Seitenwechsel, und der Fokus kehrt zum Knopf zurück —
 * dasselbe Verhalten wie das Feld „Mehr" in der Hülle. Die alte
 * Personenliste schloss nur durch Auswahl; wer sie versehentlich öffnete,
 * wurde sie nicht mehr los.
 */
function Kontomenue({
  mitglieder,
  aktuellId,
  waehle,
  schliessen,
  knopf,
}: {
  mitglieder: Mitglied[];
  aktuellId: string | undefined;
  waehle: (id: string) => void;
  schliessen: (fokus?: boolean) => void;
  knopf: React.RefObject<HTMLButtonElement | null>;
}) {
  const wurzel = useRef<HTMLDivElement>(null);
  const mehrere = mitglieder.length > 1;

  useEffect(() => {
    wurzel.current?.querySelector<HTMLElement>("button")?.focus();
    function taste(e: KeyboardEvent) {
      if (e.key === "Escape") schliessen(true);
    }
    function klick(e: MouseEvent) {
      const ziel = e.target as Node;
      if (wurzel.current?.contains(ziel) || knopf.current?.contains(ziel)) return;
      schliessen(false);
    }
    document.addEventListener("keydown", taste);
    document.addEventListener("mousedown", klick);
    return () => {
      document.removeEventListener("keydown", taste);
      document.removeEventListener("mousedown", klick);
    };
  }, [schliessen, knopf]);

  return (
    <div className="person-liste" id="konto-menue" role="dialog" aria-label="Konto" ref={wurzel}>
      {mehrere && (
        <>
          <p className="konto-abschnitt">Sitzplatz</p>
          <p className="person-erklaerung">
            Wer arbeitet gerade an diesem Rechner? Besitz, Zuordnung und Protokoll hängen
            daran. Es ist <strong>keine Anmeldung</strong> — der Olares-Zugang bleibt
            derselbe.
          </p>
          {mitglieder.map((m) => (
            <button
              key={m.id}
              type="button"
              className={`person-eintrag${aktuellId === m.id ? " aktiv" : ""}`}
              onClick={() => waehle(m.id)}
            >
              <span className="person-kreis klein" aria-hidden="true">
                {initialenAusName(m.display_name ?? m.olares_username)}
              </span>
              <span className="person-eintrag-text">
                <span>{m.display_name ?? m.olares_username}</span>
                {m.zugang === "olares" && <span className="person-art">eigener Zugang</span>}
              </span>
              {aktuellId === m.id && <Check size={13} aria-hidden="true" />}
            </button>
          ))}
        </>
      )}

      <div className={mehrere ? "konto-teil" : undefined}>
        <p className="konto-abschnitt">Darstellung</p>
        <Darstellungsschalter />
      </div>
    </div>
  );
}

/**
 * Der Nachweis — gemessen an dem, was eingetragen ist.
 *
 * docs/DESIGN.md §5: „mit gemessenen Werten — oder gar nicht". Solange die
 * Einstellungen nicht da sind, steht hier deshalb nichts. Farbe trägt die
 * Aussage nie allein: Das Zeichen wechselt mit.
 */
export function Nachweiszeile() {
  const einstellungen = useQuery({
    queryKey: ["einstellungen"],
    queryFn: () => api.get<OrgSettings>("/api/settings"),
    staleTime: 5 * 60_000,
  });

  const stand = nachweis(einstellungen.data);
  if (!stand) return null;

  const Zeichen = stand.extern ? Globe : Server;
  const titel = stand.extern
    ? stand.ziele.map((z) => `${z.was}: ${z.host}`).join(" · ")
    : "Kein eingetragenes Ziel außerhalb dieser Box";

  return (
    <Link href="/einstellungen?bereich=daten" className="nachweis" data-extern={stand.extern ? "true" : undefined} title={titel}>
      <Zeichen size={13} strokeWidth={1.75} aria-hidden="true" />
      <span>{stand.text}</span>
    </Link>
  );
}
