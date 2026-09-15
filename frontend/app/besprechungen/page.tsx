"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Search } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { api, suchparameter } from "@/lib/api";
import { anzahl, datum } from "@/lib/format";
import type { Besprechung, Besprechungsanzahl, Besprechungsseite, BesprechungVoll } from "@/lib/typen";
import { BesprechungZuordnen } from "@/components/besprechung-zuordnen";
import { Seitenkopf } from "@/components/seitenkopf";
import { Fehler, Laedt, Leer } from "@/components/zustaende";

type Reiter = "alle" | "offen" | "zugeordnet";

function dauer(sek: number | null): string | null {
  if (!sek) return null;
  return `${Math.max(1, Math.round(sek / 60))} min`;
}

/**
 * Alle Gespräche aus Insilo, nach Datum.
 *
 * Kein Eingang: Eine Besprechung verschwindet hier nicht, wenn sie einem
 * Kunden zugeordnet ist — man sucht sie später wieder, nach Datum oder nach
 * einem Wort aus dem Protokoll. „Ohne Kunde" ist die Aufräumansicht, von
 * der Marc sprach: dort liegt, was noch einen Klick braucht.
 */
export default function BesprechungenSeite() {
  const router = useRouter();
  const client = useQueryClient();
  const [reiter, setReiter] = useState<Reiter>("alle");
  const [eingabe, setEingabe] = useState("");
  const [suche, setSuche] = useState("");
  const [von, setVon] = useState("");
  const [bis, setBis] = useState("");
  const [waehlt, setWaehlt] = useState<Besprechung | null>(null);

  // Nicht bei jedem Tastendruck fragen.
  useEffect(() => {
    const t = setTimeout(() => setSuche(eingabe.trim()), 250);
    return () => clearTimeout(t);
  }, [eingabe]);

  const zahlen = useQuery({
    queryKey: ["besprechungen", "anzahl"],
    queryFn: () => api.get<Besprechungsanzahl>("/api/besprechungen/anzahl"),
    refetchInterval: 60_000,
  });

  const seite = useQuery({
    queryKey: ["besprechungen", "liste", reiter, suche, von, bis],
    queryFn: () =>
      api.get<Besprechungsseite>(
        `/api/besprechungen${suchparameter({ status: reiter, q: suche, von, bis, limit: "100" })}`,
      ),
    // Gespräche kommen von außen, ohne dass die Oberfläche es merkt.
    refetchInterval: 60_000,
  });

  const uebernehmen = useMutation({
    mutationFn: (b: Besprechung) =>
      api.post<BesprechungVoll>(`/api/besprechungen/${b.id}/zuordnen`, {
        company_id: b.vorschlag?.company?.id ?? null,
        contact_ids: (b.vorschlag?.kontakte ?? []).map((k) => k.id),
        deal_id: b.vorschlag?.deal?.id ?? null,
      }),
    onSuccess: () => {
      client.invalidateQueries({ queryKey: ["besprechungen"] });
      client.invalidateQueries({ queryKey: ["briefing"] });
    },
  });

  const REITER: { wert: Reiter; text: string; zahl?: number }[] = [
    { wert: "alle", text: "Alle", zahl: zahlen.data?.alle },
    { wert: "offen", text: "Ohne Kunde", zahl: zahlen.data?.offen },
    { wert: "zugeordnet", text: "Zugeordnet", zahl: zahlen.data?.zugeordnet },
  ];

  const gefiltert = Boolean(suche || von || bis);

  return (
    <>
      <Seitenkopf
        titel="Besprechungen"
        zahl={zahlen.data ? `${anzahl(zahlen.data.offen, "ohne Kunde", "ohne Kunde")}` : undefined}
      />

      <div className="ansichtsleiste" role="tablist" aria-label="Ansichten">
        {REITER.map((r) => (
          <button
            key={r.wert}
            type="button"
            role="tab"
            aria-selected={reiter === r.wert}
            className={`ansicht-reiter${reiter === r.wert ? " aktiv" : ""}`}
            onClick={() => setReiter(r.wert)}
          >
            {r.text}
            {r.zahl !== undefined && <span className="ansicht-zahl">{r.zahl}</span>}
          </button>
        ))}
      </div>

      <div className="werkzeugleiste">
        <div className="suchfeld">
          <Search size={16} aria-hidden="true" />
          <input
            value={eingabe}
            onChange={(e) => setEingabe(e.target.value)}
            placeholder="Titel oder ein Wort aus dem Protokoll"
            aria-label="Besprechungen durchsuchen"
          />
        </div>
        <label className="besprechung-zeitraum">
          <span>von</span>
          <input type="date" value={von} onChange={(e) => setVon(e.target.value)} />
        </label>
        <label className="besprechung-zeitraum">
          <span>bis</span>
          <input type="date" value={bis} onChange={(e) => setBis(e.target.value)} />
        </label>
        {gefiltert && (
          <button type="button" className="btn btn-still btn-klein" onClick={() => { setEingabe(""); setVon(""); setBis(""); }}>
            Filter leeren
          </button>
        )}
        <span className="besprechung-treffer">{seite.data ? anzahl(seite.data.gesamt, "Besprechung", "Besprechungen") : ""}</span>
      </div>

      <div className="liste">
        {seite.isPending && <Laedt />}
        {seite.isError && <Fehler text={(seite.error as Error).message} />}
        {uebernehmen.isError && <Fehler text={(uebernehmen.error as Error).message} />}

        {seite.data?.gesamt === 0 && (
          gefiltert ? (
            <Leer titel="Nichts gefunden" text="Kein Titel und kein Protokoll passt zu Suche und Zeitraum." />
          ) : reiter === "offen" ? (
            <Leer titel="Alles zugeordnet" text="Jede Besprechung hängt an einem Kunden." />
          ) : (
            <Leer
              titel="Noch keine Besprechung"
              text="Gespräche kommen aus Insilo, sobald dort ein Webhook auf Beacon zeigt — Einstellungen › KI und Programme › Verbundene Programme."
            />
          )
        )}

        {seite.data && seite.data.gesamt > 0 && (
          <div className="rollbar">
            <table className="tabelle besprechungstabelle" style={{ minInlineSize: "46rem" }}>
              <thead>
                <tr>
                  <th>Datum</th>
                  <th>Besprechung</th>
                  <th>Kunde</th>
                </tr>
              </thead>
              <tbody>
                {seite.data.eintraege.map((b) => (
                  <tr key={b.id} onClick={() => router.push(`/besprechungen/${b.id}`)}>
                    <td className="besprechung-datum">
                      {datum(b.recorded_at ?? b.created_at)}
                      {dauer(b.dauer_sek) && <span>{dauer(b.dauer_sek)}</span>}
                    </td>
                    <td>
                      <span className="haupt">{b.titel || "Besprechung"}</span>
                      {b.beteiligte.length > 0 && (
                        <span className="besprechung-beteiligte">{b.beteiligte.join(", ")}</span>
                      )}
                    </td>
                    <td onClick={(e) => e.stopPropagation()}>
                      <Kundenzelle
                        b={b}
                        uebernimmt={uebernehmen.isPending && uebernehmen.variables?.id === b.id}
                        beiUebernehmen={() => uebernehmen.mutate(b)}
                        beiWaehlen={() => setWaehlt(b)}
                      />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {waehlt && <BesprechungZuordnen besprechung={waehlt} beiSchliessen={() => setWaehlt(null)} />}
    </>
  );
}

/**
 * Was in der Kundenspalte steht — die Zuordnung, der Vorschlag, oder die
 * Bitte zu wählen.
 *
 * Der Vorschlag steht als Vorschlag da, nicht als Tatsache: gedämpft, mit
 * dem Grund darunter und einem Knopf. Bestätigen ist ein Klick; ungefragt
 * zugeordnet wird nichts.
 */
function Kundenzelle({
  b,
  uebernimmt,
  beiUebernehmen,
  beiWaehlen,
}: {
  b: Besprechung;
  uebernimmt: boolean;
  beiUebernehmen: () => void;
  beiWaehlen: () => void;
}) {
  if (b.status === "zugeordnet") {
    return (
      <div className="kundenzelle">
        {b.company ? (
          <Link href={`/firmen/${b.company.id}`} className="haupt">{b.company.name}</Link>
        ) : (
          <span className="haupt">{b.kontakte[0]?.name ?? "zugeordnet"}</span>
        )}
        {b.kontakte.length > 0 && <span className="kundenzelle-unter">{b.kontakte.map((k) => k.name).join(", ")}</span>}
      </div>
    );
  }
  if (b.status === "verworfen") {
    return <span className="kundenzelle-unter">verworfen</span>;
  }

  const v = b.vorschlag;
  if (v?.company) {
    const wer = [v.company.name, ...v.kontakte.map((k) => k.name)].join(" · ");
    return (
      <div className="kundenzelle vorschlag">
        <span className="kundenzelle-vorschlag">
          <span className="kundenzelle-marke">{v.quelle === "modell" ? "Vorschlag des Modells" : "Vorschlag"}</span>
          {wer}
        </span>
        <span className="kundenzelle-unter">{v.grund}</span>
        <span className="kundenzelle-knoepfe">
          <button type="button" className="btn btn-sekundaer btn-klein" onClick={beiUebernehmen} disabled={uebernimmt}>
            {uebernimmt ? "Ordnet zu …" : "Übernehmen"}
          </button>
          <button type="button" className="btn btn-still btn-klein" onClick={beiWaehlen}>Anders …</button>
        </span>
      </div>
    );
  }

  return (
    <div className="kundenzelle">
      <span className="kundenzelle-unter">{v?.grund || "Noch kein Vorschlag"}</span>
      <span className="kundenzelle-knoepfe">
        <button type="button" className="btn btn-sekundaer btn-klein" onClick={beiWaehlen}>
          {v?.mehrdeutig ? "Wählen …" : "Zuordnen …"}
        </button>
      </span>
    </div>
  );
}
