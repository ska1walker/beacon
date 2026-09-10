"use client";

import { useMutation, useQuery } from "@tanstack/react-query";
import { Search, Sparkles } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useId, useRef, useState } from "react";
import { api } from "@/lib/api";
import type { Frageantwort, Suchergebnis, Suchtreffer } from "@/lib/typen";
import { Fehler } from "@/components/zustaende";

const ART_TEXT: Record<string, string> = {
  firma: "Firma",
  kontakt: "Kontakt",
  geschaeft: "Geschäft",
  ticket: "Ticket",
  liste: "Liste",
  kampagne: "Kampagne",
};

/** Sieht der Text wie eine Frage aus? Dann ist die Frage die letzte Zeile. */
function istFrage(text: string): boolean {
  const t = text.trim();
  return t.endsWith("?") || t.split(/\s+/).length >= 4;
}

/**
 * Suchen oder fragen — ein Feld für beides, wie HubSpot es macht.
 *
 * Beim Tippen kommen sofort Treffer über alle Objekte; das kostet nichts.
 * Sieht der Text wie eine Frage aus, steht darunter „Frage stellen ↵“ —
 * erst dann läuft das Modell. ⌘K / Strg+K von überall.
 *
 * **Es öffnet sich unter dem Feld, nicht in der Mitte des Bildes.** Bis
 * 0.9.2 war die Suche ein Fenster über allem: Ein Klick auf das Feld ließ
 * es verschwinden, und ein zweites, gleich aussehendes Feld erschien in
 * der Bildmitte. Man tippte dann in etwas anderes als in das, was man
 * angeklickt hatte. Jetzt ist das Feld in der Leiste das echte Feld, und
 * die Treffer hängen daran.
 */
export function Suchfeld() {
  const router = useRouter();
  const [offen, setOffen] = useState(false);
  const [text, setText] = useState("");
  const [wahl, setWahl] = useState(0);
  const wurzel = useRef<HTMLDivElement>(null);
  const feld = useRef<HTMLInputElement>(null);
  const id = useId();

  const suche = useQuery({
    queryKey: ["suche", text.trim()],
    queryFn: () => api.get<Suchergebnis>(`/api/suche?q=${encodeURIComponent(text.trim())}`),
    enabled: offen && text.trim().length >= 2,
    staleTime: 10_000,
  });
  const frage = useMutation({
    mutationFn: (f: string) => api.post<Frageantwort>("/api/fragen", { frage: f }),
  });

  const treffer: Suchtreffer[] = suche.data?.treffer ?? [];
  const fragbar = text.trim().length >= 3 && istFrage(text);
  // Zeilen: erst die Treffer, dann — wenn es eine Frage ist — die Frage.
  const zeilen = treffer.length + (fragbar ? 1 : 0);

  useEffect(() => {
    setWahl(0);
  }, [text]);

  // ⌘K führt zum Feld, statt ein zweites zu öffnen.
  useEffect(() => {
    function taste(e: KeyboardEvent) {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        feld.current?.focus();
        feld.current?.select();
        setOffen(true);
      }
    }
    window.addEventListener("keydown", taste);
    return () => window.removeEventListener("keydown", taste);
  }, []);

  // Ein Klick daneben schließt die Treffer. Der Text bleibt stehen — wer
  // zurückkommt, tippt weiter, statt von vorn anzufangen.
  useEffect(() => {
    if (!offen) return;
    function daneben(e: MouseEvent) {
      if (!wurzel.current?.contains(e.target as Node)) setOffen(false);
    }
    document.addEventListener("mousedown", daneben);
    return () => document.removeEventListener("mousedown", daneben);
  }, [offen]);

  function schliessen() {
    setOffen(false);
    frage.reset();
  }

  function oeffnen(t: Suchtreffer) {
    router.push(t.pfad);
    setText("");
    schliessen();
  }

  function bestaetigen() {
    if (wahl < treffer.length) return oeffnen(treffer[wahl]);
    if (fragbar) frage.mutate(text.trim());
  }

  // Das Feld allein ist noch kein Grund für ein Feld darunter: Solange
  // niemand getippt hat und keine Antwort dasteht, gäbe es nichts zu
  // zeigen außer einem Satz, den man nach dem zweiten Mal nicht mehr liest.
  const zeigt = offen && (text.trim().length >= 2 || frage.data !== undefined || frage.isPending);

  return (
    <div className="kopfsuche" ref={wurzel}>
      <Search size={16} aria-hidden="true" className="kopfsuche-zeichen" />
      <input
        ref={feld}
        className="kopfsuche-feld"
        value={text}
        role="combobox"
        aria-expanded={zeigt}
        aria-controls={id}
        aria-label="Suchen oder fragen"
        placeholder="Suchen oder fragen"
        onFocus={() => setOffen(true)}
        onChange={(e) => {
          setText(e.target.value);
          setOffen(true);
        }}
        onKeyDown={(e) => {
          if (e.key === "Escape") { schliessen(); feld.current?.blur(); }
          if (e.key === "ArrowDown") { e.preventDefault(); setOffen(true); setWahl((w) => Math.min(w + 1, Math.max(zeilen - 1, 0))); }
          if (e.key === "ArrowUp") { e.preventDefault(); setWahl((w) => Math.max(w - 1, 0)); }
          if (e.key === "Enter") { e.preventDefault(); bestaetigen(); }
        }}
      />
      {!text && <kbd className="kopfsuche-taste">⌘K</kbd>}

      {zeigt && (
        <div className="kopfsuche-feld-auf" id={id}>
          {treffer.length > 0 && (
            <ul className="suchpalette-liste" role="listbox" aria-label="Treffer">
              {treffer.map((t, i) => (
                <li key={`${t.art}-${t.id}`} role="option" aria-selected={i === wahl}>
                  <Link
                    href={t.pfad}
                    className={`suchpalette-zeile${i === wahl ? " aktiv" : ""}`}
                    onClick={() => { setText(""); schliessen(); }}
                    onMouseEnter={() => setWahl(i)}
                  >
                    <span className="suchpalette-art">{ART_TEXT[t.art] ?? t.art}</span>
                    <span className="suchpalette-titel">{t.titel}</span>
                    {t.untertitel && <span className="suchpalette-unter">{t.untertitel}</span>}
                  </Link>
                </li>
              ))}
            </ul>
          )}
          {suche.data && treffer.length === 0 && !fragbar && (
            <p className="suchpalette-hinweis">Nichts gefunden. Eine Frage formulieren? „Welche Firmen …?“</p>
          )}

          {fragbar && (
            <button
              type="button"
              className={`suchpalette-zeile suchpalette-frage${wahl === treffer.length ? " aktiv" : ""}`}
              onMouseEnter={() => setWahl(treffer.length)}
              onClick={() => frage.mutate(text.trim())}
              disabled={frage.isPending}
            >
              <Sparkles size={15} aria-hidden="true" />
              <span className="suchpalette-titel">{frage.isPending ? "Sieht nach …" : `Frage stellen: „${text.trim()}“`}</span>
              <kbd>↵</kbd>
            </button>
          )}

          {frage.isError && <div style={{ padding: "0 var(--am-raum-4) var(--am-raum-3)" }}><Fehler text={(frage.error as Error).message} /></div>}
          {frage.data && (
            <div className="suchpalette-antwort">
              {frage.data.hinweis && <p className="suchpalette-hinweis" style={{ padding: 0 }}>{frage.data.hinweis}</p>}
              {frage.data.antwort && <p style={{ whiteSpace: "pre-wrap", margin: 0 }}>{frage.data.antwort}</p>}
              {frage.data.fundstellen.length > 0 && (
                <ul className="suchpalette-fundstellen">
                  {frage.data.fundstellen.slice(0, 8).map((f, i) => (
                    <li key={i}>
                      {f.id ? (
                        <Link
                          href={f.art === "firma" ? `/firmen/${f.id}` : f.art === "kontakt" ? `/kontakte/${f.id}` : f.art === "geschaeft" ? `/deals/${f.id}` : f.art === "ticket" ? `/tickets/${f.id}` : "#"}
                          onClick={schliessen}
                        >
                          {f.titel}
                        </Link>
                      ) : f.titel}
                    </li>
                  ))}
                </ul>
              )}
              <p className="suchpalette-hinweis" style={{ padding: "var(--am-raum-2) 0 0" }}>
                Antwort von {frage.data.modell} — <Link href="/fragen" onClick={schliessen}>alle Fragen</Link>
              </p>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
