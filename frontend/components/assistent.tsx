"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ArrowUp, Check, ExternalLink, X } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";
import type { AssistentAntwort, AssistentKarte } from "@/lib/typen";
import { Schild } from "@/components/schild";

/**
 * Der Assistent — unten rechts, wie in Relay, mit dem Schild als Zeichen.
 *
 * Ein Auftrag in Worten: „Leg für Brinkmann eine Aufgabe an: Angebot
 * nachfassen, Freitag.“ Das Modell plant mit Beacons Werkzeugen, Beacon
 * führt aus. Lesen sofort, Schreiben mit Karte: Jede Änderung kommt als
 * fertige Anfrage zurück und wird erst auf „Ausführen“ geschrieben — mit
 * den Rechten der Person, wie ein Klick.
 */
type Eintrag =
  | { art: "nutzer"; text: string }
  | { art: "assistent"; text: string; karten: AssistentKarte[]; navigation: string | null; schritte: string[] };

const BEISPIELE = [
  "Leg für Brinkmann eine Aufgabe an: Angebot nachfassen, Freitag",
  "Welche Aufgaben sind überfällig?",
  "Öffne Nordlicht Steuerberatung",
  "Setz den Lead Insilo für Brinkmann auf Angebot",
];

export function Assistent() {
  const [offen, setOffen] = useState(false);
  const [text, setText] = useState("");
  const [verlauf, setVerlauf] = useState<Eintrag[]>([]);
  const router = useRouter();
  const client = useQueryClient();
  const feld = useRef<HTMLTextAreaElement>(null);
  const ende = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (offen) feld.current?.focus();
  }, [offen]);
  useEffect(() => ende.current?.scrollIntoView({ block: "end" }), [verlauf]);

  const senden = useMutation({
    mutationFn: (nachricht: string) =>
      api.post<AssistentAntwort>("/api/assistent", {
        nachricht,
        verlauf: verlauf.slice(-10).map((e) => ({ rolle: e.art, inhalt: e.text })),
      }),
    onSuccess: (a) => {
      setVerlauf((v) => [...v, { art: "assistent", text: a.antwort, karten: a.karten, navigation: a.navigation, schritte: a.schritte }]);
      if (a.navigation) router.push(a.navigation);
    },
  });

  function los() {
    const nachricht = text.trim();
    if (!nachricht || senden.isPending) return;
    setVerlauf((v) => [...v, { art: "nutzer", text: nachricht }]);
    setText("");
    senden.mutate(nachricht);
  }

  return (
    <>
      <button
        type="button"
        className={`assistent-knopf${offen ? " offen" : ""}`}
        onClick={() => setOffen((o) => !o)}
        aria-label={offen ? "Assistent schließen" : "Assistent öffnen"}
        aria-expanded={offen}
        aria-controls="assistent-panel"
      >
        <Schild size={22} zwinkert={!offen && !senden.isPending} />
      </button>

      {offen && (
        <section className="assistent-panel" id="assistent-panel" aria-label="Assistent">
          <header className="assistent-kopf">
            <Schild size={16} />
            <span>Assistent</span>
            <button type="button" className="assistent-zu" onClick={() => setOffen(false)} aria-label="Schließen">
              <X size={16} aria-hidden="true" />
            </button>
          </header>

          <div className="assistent-verlauf">
            {verlauf.length === 0 && (
              <div className="assistent-leer">
                <p>Sagen Sie, was zu tun ist. Änderungen kommen als Karte zurück und laufen erst, wenn Sie sie ausführen.</p>
                <ul>
                  {BEISPIELE.map((b) => (
                    <li key={b}>
                      <button type="button" className="alsLink" onClick={() => setText(b)}>{b}</button>
                    </li>
                  ))}
                </ul>
              </div>
            )}
            {verlauf.map((e, i) =>
              e.art === "nutzer" ? (
                <p key={i} className="assistent-nachricht nutzer">{e.text}</p>
              ) : (
                <div key={i} className="assistent-antwort">
                  {e.text && <p className="assistent-nachricht">{e.text}</p>}
                  {e.karten.map((k) => (
                    <Karte key={k.id} karte={k} client={client} />
                  ))}
                  {e.navigation && (
                    <p className="assistent-hinweis">
                      <ExternalLink size={12} aria-hidden="true" /> Geöffnet: <Link href={e.navigation}>{e.navigation}</Link>
                    </p>
                  )}
                </div>
              ),
            )}
            {senden.isPending && <p className="assistent-nachricht arbeitet">Denkt nach und schaut im Bestand nach — bis zu einer halben Minute.</p>}
            {senden.isError && <p className="assistent-nachricht fehler">{(senden.error as Error).message}</p>}
            <div ref={ende} />
          </div>

          <form
            className="assistent-eingabe"
            onSubmit={(e) => {
              e.preventDefault();
              los();
            }}
          >
            <textarea
              ref={feld}
              rows={2}
              value={text}
              onChange={(e) => setText(e.target.value)}
              placeholder="Was soll ich tun?"
              aria-label="Auftrag"
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  los();
                }
              }}
            />
            <button type="submit" className="assistent-senden" disabled={!text.trim() || senden.isPending} aria-label="Senden">
              <ArrowUp size={16} aria-hidden="true" />
            </button>
          </form>
        </section>
      )}
    </>
  );
}

/** Eine Karte: die fertige Anfrage, ein Mensch drückt „Ausführen“. */
function Karte({ karte, client }: { karte: AssistentKarte; client: ReturnType<typeof useQueryClient> }) {
  const [stand, setStand] = useState<"offen" | "verworfen" | "ausgefuehrt">("offen");
  const [ziel, setZiel] = useState<string | null>(null);

  const ausfuehren = useMutation({
    mutationFn: async () => {
      const { methode, pfad, koerper } = karte.anfrage;
      if (methode === "PATCH") return api.patch<{ id?: string }>(pfad, koerper);
      if (methode === "PUT") return api.put<{ id?: string }>(pfad, koerper);
      return api.post<{ id?: string }>(pfad, koerper);
    },
    onSuccess: (erg) => {
      setStand("ausgefuehrt");
      setZiel(karte.danach ? karte.danach.replace("{id}", erg?.id ?? "") : null);
      // Alles neu holen: Was der Assistent angelegt hat, soll überall stehen.
      client.invalidateQueries();
    },
  });

  return (
    <div className={`assistent-karte ${stand}`}>
      <div className="assistent-karte-kopf">
        <strong>{karte.titel}</strong>
        {stand === "ausgefuehrt" && <span className="stufe" data-art="won"><Check size={12} aria-hidden="true" /> erledigt</span>}
        {stand === "verworfen" && <span className="stufe">verworfen</span>}
      </div>
      <dl className="assistent-karte-zeilen">
        {karte.zeilen.map(([label, wert]) => (
          <div key={label}>
            <dt>{label}</dt>
            <dd>{wert}</dd>
          </div>
        ))}
      </dl>
      {ausfuehren.isError && <p className="assistent-nachricht fehler">{(ausfuehren.error as Error).message}</p>}
      {stand === "offen" && (
        <div className="btn-reihe" style={{ marginTop: "var(--am-raum-2)", gap: "var(--am-raum-2)" }}>
          <button type="button" className="btn btn-primaer btn-klein" disabled={ausfuehren.isPending} onClick={() => ausfuehren.mutate()}>
            {ausfuehren.isPending ? "Läuft …" : "Ausführen"}
          </button>
          <button type="button" className="btn btn-still btn-klein" onClick={() => setStand("verworfen")}>Verwerfen</button>
        </div>
      )}
      {stand === "ausgefuehrt" && ziel && (
        <p className="assistent-hinweis"><Link href={ziel}>Öffnen</Link></p>
      )}
    </div>
  );
}
