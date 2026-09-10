"use client";

import { useMutation, useQuery } from "@tanstack/react-query";
import { Search, Sparkles } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { api } from "@/lib/api";
import type { AnreicherungStatus, Erfassungsvorschlag, Fund, Kandidat, Kandidatenantwort } from "@/lib/typen";
import { Fehler } from "@/components/zustaende";

/**
 * Beschreiben statt tippen.
 *
 * „Baustoffhandel im Tecklenburger Land, der Geschäftsführer heißt
 * vermutlich Sebastian“ — und Beacon sucht sich den Rest zusammen. Drei
 * Schritte, an denen ein Mensch die Hand behält:
 *
 * 1. Kandidaten aus den Suchtreffern, ein Mensch wählt.
 * 2. Für die gewählte Firma Impressum, Kontaktseite, LinkedIn-Treffer.
 * 3. Die beschriebene Person auf Team-Seiten und in Treffern.
 *
 * Das Ergebnis füllt die Maske — nur leere Felder, mit Quelle je Feld.
 * Gespeichert wird nichts, bis jemand auf Anlegen drückt.
 */
export function Finden({
  art,
  firma,
  beiErgebnis,
}: {
  art: "contact" | "company";
  /** Steht die Firma schon fest (Anlegen von der Firmenseite), entfällt die Wahl. */
  firma?: { name: string; website: string | null };
  beiErgebnis: (v: Erfassungsvorschlag) => void;
}) {
  const [text, setText] = useState("");
  const [gewaehlt, setGewaehlt] = useState<Kandidat | null>(null);
  const [fund, setFund] = useState<Fund | null>(null);

  const status = useQuery({
    queryKey: ["anreicherung-status"],
    queryFn: () => api.get<AnreicherungStatus>("/api/anreicherung/status"),
    staleTime: 60_000,
  });

  const suchen = useMutation({
    mutationFn: (beschreibung: string) =>
      api.post<Kandidatenantwort>("/api/finden/kandidaten", { beschreibung }),
    onSuccess: () => {
      setGewaehlt(null);
      setFund(null);
    },
  });

  /** Schritt 2 und 3 — für einen Kontakt beides zugleich. */
  const holen = useMutation({
    mutationFn: async (k: Kandidat) => {
      const firmenwahl = { name: k.name, website: k.website };
      if (art === "company") return api.post<Fund>("/api/finden/firma", firmenwahl);
      const person = suchen.data?.person ?? {};
      const [f, p] = await Promise.all([
        api.post<Fund>("/api/finden/firma", firmenwahl),
        api.post<Fund>("/api/finden/kontakt", {
          firma: firmenwahl,
          person,
          beschreibung: Object.keys(person).length ? undefined : text.trim(),
        }),
      ]);
      // Die Firma geht mit — als firma_*-Felder, wie sie die Maske aus
      // einer Signatur kennt. Steht sie noch nicht im Bestand, legt die
      // Maske sie damit an.
      const rest: Record<string, string> = {};
      const zuordnung: Record<string, string> = { street: "firma_strasse", postal_code: "firma_plz", city: "firma_ort", phone: "firma_telefon" };
      for (const [von, nach] of Object.entries(zuordnung)) if (f.felder[von]) rest[nach] = f.felder[von];
      return {
        ...p,
        felder: { ...rest, ...p.felder },
        belege: { ...Object.fromEntries(Object.entries(f.belege).filter(([k]) => k in zuordnung).map(([k, v]) => [zuordnung[k], v])), ...p.belege },
        quellen: [...f.quellen, ...p.quellen.filter((q) => !f.quellen.some((x) => x.url === q.url))],
        hinweise: [...p.hinweise, ...f.hinweise],
      };
    },
    onSuccess: (f) => {
      setFund(f);
      beiErgebnis({ art: f.art, felder: f.felder, rest: f.rest, modell: f.modell, dublette: f.dublette });
    },
  });

  /** Firma steht fest: nur die Person suchen. */
  const personSuchen = useMutation({
    mutationFn: (beschreibung: string) =>
      api.post<Fund>("/api/finden/kontakt", {
        firma: { name: firma!.name, website: firma!.website || `https://${firma!.name}` },
        person: {},
        beschreibung,
      }),
    onSuccess: (f) => {
      setFund(f);
      beiErgebnis({ art: f.art, felder: f.felder, rest: f.rest, modell: f.modell, dublette: f.dublette });
    },
  });

  const festeFirma = art === "contact" && firma;
  const bereit = text.trim().length >= 3;
  const laeuft = suchen.isPending || holen.isPending || personSuchen.isPending;

  function los() {
    if (!bereit || laeuft) return;
    if (festeFirma) personSuchen.mutate(text.trim());
    else suchen.mutate(text.trim());
  }

  function waehlen(k: Kandidat) {
    setGewaehlt(k);
    holen.mutate(k);
  }

  const fehlt = status.data && (!status.data.llm_ready || (!festeFirma && !status.data.suche_eingerichtet));

  return (
    <div className="erfassung finden">
      <div className="erfassung-kopf">
        <Sparkles size={14} aria-hidden="true" />
        <span>
          {festeFirma
            ? `Beschreiben, wen Sie bei ${firma.name} meinen`
            : art === "contact"
              ? "Beschreiben, wen Sie meinen — Beacon sucht Firma und Person"
              : "Beschreiben, welche Firma Sie meinen — Beacon sucht den Rest"}
        </span>
      </div>

      {fehlt ? (
        <p className="erfassung-hinweis warnung">
          {!status.data!.llm_ready
            ? "Dafür braucht Beacon ein Sprachmodell."
            : "Dafür braucht Beacon einen Suchdienst — ohne ihn findet es keine Firma, die es noch nicht kennt."}{" "}
          <Link href="/einstellungen?bereich=ki">Unter KI und Programme eintragen.</Link>
        </p>
      ) : (
        <>
          <div className="erfassung-wurf">
            <textarea
              rows={2}
              value={text}
              aria-label="Beschreibung"
              placeholder={
                festeFirma
                  ? "Geschäftsführer, heißt vermutlich Sebastian"
                  : art === "contact"
                    ? "Baustoffhandel im Tecklenburger Land, der Geschäftsführer heißt vermutlich Sebastian"
                    : "Baustoffhandel im Tecklenburger Land, Familienbetrieb, eigener Fuhrpark"
              }
              onChange={(e) => setText(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  los();
                }
              }}
            />
          </div>
          <div className="erfassung-leiste">
            <span className="erfassung-tipp">
              {status.data?.suche_art === "brave" ? "Suche über Brave" : status.data?.suche_eingerichtet ? "Suche über SearXNG" : "Liest die Firmen-Website"} · Gefüllt wird nur, was leer ist
            </span>
            <span style={{ flex: 1 }} />
            <button type="button" className="btn btn-sekundaer btn-klein" disabled={!bereit || laeuft} onClick={los}>
              <Search size={14} aria-hidden="true" />
              {suchen.isPending || personSuchen.isPending ? "Sucht …" : "Suchen"}
            </button>
          </div>
        </>
      )}

      {suchen.isError && <Fehler text={(suchen.error as Error).message} />}
      {personSuchen.isError && <Fehler text={(personSuchen.error as Error).message} />}
      {holen.isError && <Fehler text={(holen.error as Error).message} />}

      {suchen.data && !fund && (
        <div className="finden-kandidaten">
          {suchen.data.kandidaten.length > 0 && (
            <p className="erfassung-hinweis">
              {suchen.data.kandidaten.length === 1 ? "Eine Firma passt" : `${suchen.data.kandidaten.length} Firmen passen`} zur Beschreibung — welche meinen Sie?
              {Object.keys(suchen.data.person).length > 0 && (
                <> Gesucht wird danach: {personText(suchen.data.person)}.</>
              )}
            </p>
          )}
          <ul>
            {suchen.data.kandidaten.map((k) => (
              <li key={k.website}>
                <button
                  type="button"
                  className={`finden-kandidat${gewaehlt?.website === k.website ? " aktiv" : ""}`}
                  disabled={holen.isPending}
                  onClick={() => waehlen(k)}
                >
                  <span className="finden-kandidat-name">{k.name}</span>
                  <span className="finden-kandidat-unter">
                    {[k.ort, host(k.website)].filter(Boolean).join(" · ")}
                    {k.grund ? ` — ${k.grund}` : ""}
                  </span>
                  <span className="finden-kandidat-aktion">
                    {holen.isPending && gewaehlt?.website === k.website ? "Liest …" : "Übernehmen"}
                  </span>
                </button>
              </li>
            ))}
          </ul>
          {suchen.data.hinweise.map((h) => (
            <p key={h} className="erfassung-hinweis warnung">{h}</p>
          ))}
          {holen.isPending && (
            <p className="erfassung-hinweis">
              Liest Impressum, Kontakt- und Team-Seite und die Suchtreffer — das dauert mit einem Modell auf der Box bis zu einer Minute.
            </p>
          )}
        </div>
      )}

      {fund && !laeuft && (
        <Fundbericht
          fund={fund}
          beiPerson={(a) => {
            beiErgebnis({
              art: "contact",
              felder: { first_name: a.first_name, last_name: a.last_name, job_title: a.job_title },
              rest: null, modell: fund.modell, dublette: null,
            });
            setFund({ ...fund, felder: { ...fund.felder, first_name: a.first_name, last_name: a.last_name, job_title: a.job_title }, alternativen: [] });
          }}
        />
      )}
    </div>
  );
}

function personText(p: Record<string, string>): string {
  return [p.rolle, [p.vorname, p.nachname].filter(Boolean).join(" ")].filter(Boolean).join(", ");
}

function host(url: string): string {
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return url;
  }
}

const FELDTEXT: Record<string, string> = {
  name: "Name", domain: "Domain", website: "Website", industry: "Branche", employee_count: "Beschäftigte",
  street: "Straße", postal_code: "PLZ", city: "Ort", country: "Land", phone: "Telefon", linkedin_url: "LinkedIn",
  description: "Beschreibung", first_name: "Vorname", last_name: "Nachname", job_title: "Position", email: "E-Mail",
  mobile: "Mobil", firma_name: "Firma", firma_domain: "Firmendomain", firma_strasse: "Firmenanschrift",
  firma_plz: "PLZ der Firma", firma_ort: "Ort der Firma", firma_telefon: "Telefon der Firma",
};

/** Was gefüllt wurde, und woher — je Quelle eine Zeile, damit man nachsehen kann. */
function Fundbericht({ fund, beiPerson }: { fund: Fund; beiPerson: (a: NonNullable<Fund["alternativen"]>[number]) => void }) {
  const jeQuelle = new Map<string, string[]>();
  for (const [feld, b] of Object.entries(fund.belege)) {
    const liste = jeQuelle.get(b.quelle) ?? [];
    liste.push(FELDTEXT[feld] ?? feld);
    jeQuelle.set(b.quelle, liste);
  }
  const anfragen = fund.quellen.filter((q) => q.art === "suche" && q.anfrage).map((q) => q.anfrage!);
  const felder = Object.keys(fund.felder).length;

  return (
    <div className="erfassung-ergebnis">
      <p className="erfassung-hinweis">
        {felder === 0 ? "Nichts gefunden" : felder === 1 ? "Ein Feld gefüllt" : `${felder} Felder gefüllt`} · gelesen von{" "}
        <span className="mono">{fund.modell}</span>. Bitte nachsehen, bevor Sie anlegen.
      </p>
      {jeQuelle.size > 0 && (
        <ul className="finden-belege">
          {[...jeQuelle.entries()].map(([quelle, felder]) => (
            <li key={quelle}>
              <a href={quelle} target="_blank" rel="noreferrer noopener">{host(quelle)}{pfad(quelle)}</a>: {felder.join(", ")}
            </li>
          ))}
        </ul>
      )}
      {anfragen.length > 0 && (
        <p className="erfassung-hinweis">
          An den Suchdienst ging: {[...new Set(anfragen)].map((a) => `„${a}“`).join(", ")}
        </p>
      )}
      {fund.hinweise.map((h) => (
        <p key={h} className="erfassung-hinweis warnung">{h}</p>
      ))}
      {fund.alternativen && fund.alternativen.length > 0 && (
        <ul className="finden-personen">
          {fund.alternativen.map((a) => (
            <li key={`${a.first_name}-${a.last_name}`}>
              <button type="button" className="finden-person" onClick={() => beiPerson(a)}>
                <span className="finden-kandidat-name">{[a.first_name, a.last_name].filter(Boolean).join(" ")}</span>
                {a.job_title && <span className="finden-kandidat-unter">{a.job_title} · {host(a.quelle)}{pfad(a.quelle)}</span>}
                <span className="finden-kandidat-aktion">Übernehmen</span>
              </button>
            </li>
          ))}
        </ul>
      )}
      {fund.dublette && (
        <p className="erfassung-hinweis warnung">
          Gibt es womöglich schon:{" "}
          <Link href={`${fund.art === "contact" ? "/kontakte" : "/firmen"}/${fund.dublette.id}`}>
            {fund.art === "contact"
              ? [fund.dublette.first_name, fund.dublette.last_name].filter(Boolean).join(" ") || fund.dublette.email
              : fund.dublette.name || fund.dublette.domain}
          </Link>{" "}
          ({fund.dublette.grund}). Anlegen geht trotzdem — nur wissen Sie es jetzt.
        </p>
      )}
    </div>
  );
}

function pfad(url: string): string {
  try {
    const p = new URL(url).pathname.replace(/\/$/, "");
    return p.length > 1 ? p : "";
  } catch {
    return "";
  }
}

/** Zwei Wege in die Maske: beschreiben oder hineinwerfen. */
export function Wegwahl({ weg, setWeg }: { weg: "finden" | "werfen"; setWeg: (w: "finden" | "werfen") => void }) {
  return (
    <div className="wegwahl" role="tablist" aria-label="Wie die Maske gefüllt wird">
      <button type="button" role="tab" aria-selected={weg === "finden"} className={weg === "finden" ? "aktiv" : ""} onClick={() => setWeg("finden")}>
        Beschreiben
      </button>
      <button type="button" role="tab" aria-selected={weg === "werfen"} className={weg === "werfen" ? "aktiv" : ""} onClick={() => setWeg("werfen")}>
        Hineinwerfen
      </button>
    </div>
  );
}
