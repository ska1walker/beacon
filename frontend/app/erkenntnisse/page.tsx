"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ChevronDown, ChevronRight, Lightbulb, Sparkles } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { api } from "@/lib/api";
import { anzahl, datum } from "@/lib/format";
import type { Aussage, Erkenntnisse, Thema } from "@/lib/typen";
import { Seitenkopf } from "@/components/seitenkopf";
import { Fehler, Laedt, Leer } from "@/components/zustaende";

const ART_TEXT: Record<string, string> = { lob: "Lob", kritik: "Kritik", wunsch: "Wunsch", einwand: "Einwand", frage: "Frage" };
const ZEITRAEUME = [
  { tage: 30, text: "30 Tage" },
  { tage: 90, text: "90 Tage" },
  { tage: 180, text: "6 Monate" },
  { tage: 365, text: "12 Monate" },
];

/**
 * Erkenntnisse — was Kunden in Gesprächen über die Produkte sagen, gebündelt.
 *
 * Jede Notiz wird einmal gelesen und in Aussagen zerlegt; die Aussagen
 * eines Zeitraums werden zu Themen. Ein Thema, das fünf Firmen nennen,
 * ist eine Aufgabe fürs Produkt — und jedes Thema zeigt auf die
 * Gespräche dahinter, damit niemand dem Modell glauben muss.
 */
export default function ErkenntnisseSeite() {
  const client = useQueryClient();
  const [tage, setTage] = useState(90);

  const daten = useQuery({
    queryKey: ["erkenntnisse", tage],
    queryFn: () => api.get<Erkenntnisse>(`/api/erkenntnisse?tage=${tage}`),
    refetchInterval: (q) => (q.state.data?.lauf?.status === "laeuft" ? 3000 : false),
  });

  const auswerten = useMutation({
    mutationFn: () => api.post("/api/erkenntnisse/auswerten", { tage }),
    onSuccess: () => client.invalidateQueries({ queryKey: ["erkenntnisse", tage] }),
  });

  const d = daten.data;
  const lauf = d?.lauf ?? null;
  const laeuft = lauf?.status === "laeuft";
  const aussagen = new Map((d?.aussagen ?? []).map((a) => [a.id, a]));

  return (
    <>
      <Seitenkopf titel="Erkenntnisse" zahl="Was Kunden über die Produkte sagen">
        <select value={tage} onChange={(e) => setTage(Number(e.target.value))} aria-label="Zeitraum">
          {ZEITRAEUME.map((z) => <option key={z.tage} value={z.tage}>{z.text}</option>)}
        </select>
        <button type="button" className="btn btn-primaer" disabled={!d?.llm_ready || laeuft || auswerten.isPending} onClick={() => auswerten.mutate()}>
          <Sparkles size={14} aria-hidden="true" />
          {laeuft ? "Wertet aus …" : d?.offene_notizen ? `Auswerten (${anzahl(d.offene_notizen, "neue Notiz", "neue Notizen")})` : "Neu bündeln"}
        </button>
      </Seitenkopf>

      <div className="liste">
        {daten.isPending && <Laedt />}
        {daten.isError && <Fehler text={(daten.error as Error).message} />}
        {auswerten.isError && <Fehler text={(auswerten.error as Error).message} />}

        {d && !d.llm_ready && (
          <p className="erfassung-hinweis warnung" style={{ marginBottom: "var(--am-raum-4)" }}>
            Dafür braucht Beacon ein Sprachmodell. <Link href="/einstellungen?bereich=ki">Unter KI und Programme eintragen.</Link>
          </p>
        )}

        {laeuft && (
          <p className="erfassung-hinweis" style={{ marginBottom: "var(--am-raum-4)" }}>
            {lauf.fortschritt.schritt === "themen"
              ? "Bündelt die Aussagen zu Themen …"
              : `Liest Notizen — ${lauf.fortschritt.gelesen ?? 0} von ${lauf.fortschritt.gesamt ?? 0} …`}
          </p>
        )}
        {lauf?.status === "fehler" && <Fehler text={`Die letzte Auswertung ist gescheitert: ${lauf.fehler ?? "unbekannt"}`} />}

        {d && (
          <dl className="kennzahlen" style={{ marginBottom: "var(--am-raum-6)" }}>
            {Object.entries(d.nach_art).map(([art, n]) => (
              <div className="kennzahl" key={art}>
                <dt><span className="erkenntnis-art" data-art={art}>{ART_TEXT[art]}</span></dt>
                <dd>{n}</dd>
              </div>
            ))}
            <div className="kennzahl">
              <dt>Noch nicht gelesen</dt>
              <dd>{d.offene_notizen}</dd>
            </div>
          </dl>
        )}

        {d && lauf?.status === "fertig" && lauf.themen.length === 0 && (
          <Leer titel="Keine Themen" text="In den Notizen des Zeitraums steht nichts über die Produkte — oder es sind noch keine Notizen da." />
        )}
        {d && !lauf && (
          <Leer
            titel="Noch nicht ausgewertet"
            text={d.offene_notizen === 0 ? "Im Zeitraum gibt es keine Gesprächsnotizen mit Inhalt." : `${anzahl(d.offene_notizen, "Notiz wartet", "Notizen warten")} darauf, gelesen zu werden — oben auf Auswerten drücken.`}
          />
        )}

        {lauf && lauf.themen.length > 0 && (
          <div className="themen">
            {lauf.themen.map((t, i) => <Themenkarte key={`${i}-${t.titel}`} thema={t} aussagen={aussagen} />)}
            <p className="erfassung-hinweis">
              Stand {datum(lauf.updated_at)} · {anzahl(lauf.aussagen_anzahl, "Aussage", "Aussagen")} aus {ZEITRAEUME.find((z) => z.tage === lauf.zeitraum_tage)?.text ?? `${lauf.zeitraum_tage} Tagen`} · gebündelt von <span className="mono">{lauf.modell}</span>
            </p>
          </div>
        )}
      </div>
    </>
  );
}

function Themenkarte({ thema, aussagen }: { thema: Thema; aussagen: Map<string, Aussage> }) {
  const [offen, setOffen] = useState(false);
  const belege = thema.aussagen.map((id) => aussagen.get(id)).filter((a): a is Aussage => Boolean(a));
  return (
    <article className="karte thema">
      <header className="thema-kopf">
        <div>
          <h2>{thema.titel}</h2>
          <div className="thema-marken">
            <span className="erkenntnis-art" data-art={thema.art}>{ART_TEXT[thema.art] ?? thema.art}</span>
            {thema.produkt && <span className="stufe">{thema.produkt}</span>}
            <span className="thema-zahl">{anzahl(thema.aussagen.length, "Aussage", "Aussagen")} · {anzahl(thema.firmen.length, "Firma", "Firmen")}</span>
          </div>
        </div>
      </header>
      {thema.bedeutung && <p className="thema-bedeutung">{thema.bedeutung}</p>}
      {thema.vorschlag && (
        <p className="thema-vorschlag"><Lightbulb size={14} aria-hidden="true" /><span><strong>Was zu tun wäre:</strong> {thema.vorschlag}</span></p>
      )}
      <button type="button" className="alsLink thema-auf" aria-expanded={offen} onClick={() => setOffen((o) => !o)}>
        {offen ? <ChevronDown size={14} aria-hidden="true" /> : <ChevronRight size={14} aria-hidden="true" />}
        {offen ? "Gespräche verbergen" : `Gespräche zeigen (${thema.firmen.slice(0, 3).join(", ")}${thema.firmen.length > 3 ? " …" : ""})`}
      </button>
      {offen && (
        <ul className="thema-belege">
          {belege.map((a) => (
            <li key={a.id}>
              <span className="erkenntnis-art" data-art={a.art}>{ART_TEXT[a.art]}</span>
              <span className="thema-beleg-text">
                {a.text}
                {a.zitat && <q>{a.zitat}</q>}
              </span>
              <span className="thema-beleg-quelle">
                {a.company_id ? <Link href={`/firmen/${a.company_id}`}>{a.firma ?? "Firma"}</Link> : a.firma ?? "—"}
                {" · "}{datum(a.occurred_at)}
                {a.deal_id && <> · <Link href={`/deals/${a.deal_id}`}>Lead</Link></>}
              </span>
            </li>
          ))}
        </ul>
      )}
    </article>
  );
}
