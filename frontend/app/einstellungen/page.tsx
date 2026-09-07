"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { OrgSettings } from "@/lib/typen";
import { Seitenkopf } from "@/components/seitenkopf";
import { Fehler, Laedt } from "@/components/zustaende";
import { Erklaerung } from "@/components/erklaerung";
import { Sicherungsblock } from "@/components/sicherung";
import { Absenderblock } from "@/components/absender";
import { Quellenblock } from "@/components/quellen";
import { Postfachblock } from "@/components/postfach";
import { Mitgliederblock } from "@/components/mitglieder";
import { Eigenschaftenblock } from "@/components/eigenschaften-verwalten";
import { Pipelinesblock } from "@/components/pipelines-verwalten";
import { Katalogblock, Verlustgruendeblock } from "@/components/katalog";
import { Postausgangblock } from "@/components/postausgang";
import { Marketingversandblock, Versandblock } from "@/components/versand";
import { AnreicherungEinstellungen } from "@/components/anreicherung-einstellungen";
import { Sprachausgabeblock } from "@/components/podcast";

/**
 * Die Einstellungen in fünf Unterpunkten.
 *
 * Eine Seite mit vierzehn Blöcken untereinander liest niemand. Jeder
 * Unterpunkt trägt, was zusammengehört; jeder Block sagt in einem Satz,
 * wozu er da ist, und hält das Kleingedruckte hinter dem Symbol.
 */
const BEREICHE = [
  { schluessel: "firma", text: "Firma und Team" },
  { schluessel: "vertrieb", text: "Vertrieb" },
  { schluessel: "email", text: "E-Mail" },
  { schluessel: "ki", text: "KI und Programme" },
  { schluessel: "daten", text: "Daten" },
] as const;

type Bereich = (typeof BEREICHE)[number]["schluessel"];

/** Der KI-Assistent: Adresse, Modell, Schlüssel. */
function KIBlock({ e }: { e: OrgSettings }) {
  const client = useQueryClient();
  const [adresse, setAdresse] = useState(e.llm_base_url);
  const [modell, setModell] = useState(e.llm_model);
  const [schluessel, setSchluessel] = useState("");
  useEffect(() => {
    setAdresse(e.llm_base_url);
    setModell(e.llm_model);
  }, [e.llm_base_url, e.llm_model]);

  const speichern = useMutation({
    mutationFn: () =>
      api.put<OrgSettings>("/api/settings", {
        llm_base_url: adresse,
        llm_model: modell,
        // Leer heißt „nicht angefasst“ — der hinterlegte Schlüssel bleibt.
        llm_api_key: schluessel,
      }),
    onSuccess: () => {
      setSchluessel("");
      client.invalidateQueries({ queryKey: ["einstellungen"] });
      client.invalidateQueries({ queryKey: ["ki-status"] });
      // Der Anlegen-Dialog fragt denselben Stand ab — sonst sagt er noch
      // eine Minute lang „kein Sprachmodell“, obwohl gerade eins gespeichert wurde.
      client.invalidateQueries({ queryKey: ["anreicherung-status"] });
    },
  });

  return (
    <section className="block">
      <div className="block-kopf">
        <h2>KI-Assistent</h2>
        <span className="stufe" data-art={e.llm_ready ? "won" : undefined}>
          {e.llm_ready ? "eingerichtet" : "nicht eingerichtet"}
        </span>
      </div>
      <div className="block-inhalt">
        <Erklaerung
          kurz="Der KI-Assistent braucht ein Sprachmodell — meist die LiteLLM-App auf dieser Box."
          lang={<>Beacon bringt kein eigenes Modell mit. Es spricht einen OpenAI-kompatiblen Endpunkt an. Es gibt bewusst keine Vorgabe: Jede geratene Adresse wäre auf einer anderen Box falsch. Solange hier nichts steht, bleiben die KI-Funktionen gesperrt und sagen das — statt in einen Verbindungsfehler zu laufen.</>}
        />
        <form onSubmit={(ev) => { ev.preventDefault(); speichern.mutate(); }}>
          <div className="feld">
            <label htmlFor="adresse">Adresse</label>
            <input id="adresse" value={adresse} onChange={(ev) => setAdresse(ev.target.value)} placeholder="https://litellm-beispiel.olares.com/v1" />
            <p className="feld-hinweis">Mit <code>/v1</code> am Ende.</p>
          </div>
          <div className="feld">
            <label htmlFor="modell">Modell</label>
            <input id="modell" value={modell} onChange={(ev) => setModell(ev.target.value)} placeholder="aim-qwen3.6-35b" />
          </div>
          <div className="feld">
            <label htmlFor="schluessel">Zugangsschlüssel <span className="optional">optional</span></label>
            <input
              id="schluessel"
              type="password"
              value={schluessel}
              onChange={(ev) => setSchluessel(ev.target.value)}
              placeholder={e.llm_api_key_set ? "hinterlegt — leer lassen, um ihn zu behalten" : "keiner hinterlegt"}
              autoComplete="off"
            />
          </div>
          {speichern.isError && <Fehler text={(speichern.error as Error).message} />}
          <div className="btn-reihe">
            <button type="submit" className="btn btn-primaer" disabled={speichern.isPending}>
              {speichern.isPending ? "Wird gespeichert …" : "Speichern"}
            </button>
            {speichern.isSuccess && <span style={{ fontSize: "0.8125rem", color: "var(--am-erfolg)" }}>Gespeichert.</span>}
          </div>
        </form>
      </div>
    </section>
  );
}

/** Wohin Daten gehen — gemessen an dem, was eingetragen ist. */
function Datenwege({ e }: { e: OrgSettings }) {
  return (
    <section className="block">
      <div className="block-kopf"><h2>Wohin Daten gehen</h2></div>
      <div className="block-inhalt">
        <Erklaerung
          kurz="Alles bleibt auf dieser Box — außer dem, was Sie hier ausdrücklich an eine fremde Adresse schicken."
          lang={<>Steht bei KI-Assistent oder Suchdienst eine fremde Adresse, gehen die Inhalte der Anfragen dorthin. Diese Übersicht nennt sie beim Namen, statt pauschal „lokal“ zu behaupten.</>}
        />
        <dl>
          <div className="eigenschaft"><dt>Datenbank, Suche, Anhänge</dt><dd>auf dieser Box</dd></div>
          <div className="eigenschaft"><dt>KI-Assistent</dt><dd>{e.llm_ready ? e.llm_base_url : "nicht eingerichtet — keine Anfragen"}</dd></div>
          <div className="eigenschaft"><dt>Sprachausgabe</dt><dd>{e.tts_ready ? `Skripte der Podcasts an ${e.tts_endpoint_url}` : "nicht eingerichtet — keine Anfragen"}</dd></div>
          <div className="eigenschaft"><dt>Automatisch ergänzen</dt><dd>{e.suche_endpoint_url ? `Firmen- und Personennamen an ${e.suche_endpoint_url}; Websites der Firmen` : "nur die Websites der Firmen — kein Suchdienst eingetragen"}</dd></div>
          <div className="eigenschaft"><dt>E-Mail</dt><dd>{e.smtp_ready ? `über ${e.smtp_host}` : "kein Konto eingetragen"}{e.marketing_versand === "brevo" && e.brevo_api_key_set ? " · Marketing über Brevo" : ""}</dd></div>
          <div className="eigenschaft"><dt>Telemetrie</dt><dd>keine</dd></div>
        </dl>
      </div>
    </section>
  );
}

function Inhalt() {
  const suche = useSearchParams();
  const gewaehlt = (suche.get("bereich") as Bereich | null) ?? "firma";
  const bereich: Bereich = BEREICHE.some((b) => b.schluessel === gewaehlt) ? gewaehlt : "firma";

  const abfrage = useQuery({
    queryKey: ["einstellungen"],
    queryFn: () => api.get<OrgSettings>("/api/settings"),
  });

  if (abfrage.isPending) return <Laedt />;
  if (abfrage.isError) return <Fehler text={(abfrage.error as Error).message} />;
  const e = abfrage.data!;

  return (
    <>
      <Seitenkopf titel="Einstellungen" />

      <nav className="unterpunkte" aria-label="Bereiche der Einstellungen">
        {BEREICHE.map((b) => (
          <Link
            key={b.schluessel}
            href={`/einstellungen?bereich=${b.schluessel}`}
            className={`unterpunkt${b.schluessel === bereich ? " aktiv" : ""}`}
            aria-current={b.schluessel === bereich ? "page" : undefined}
          >
            {b.text}
          </Link>
        ))}
      </nav>

      <div className="datensatz" style={{ gridTemplateColumns: "minmax(0, 640px)" }}>
        {bereich === "firma" && (
          <>
            <Absenderblock />
            <Mitgliederblock />
          </>
        )}
        {bereich === "vertrieb" && (
          <>
            <Pipelinesblock />
            <Katalogblock />
            <Verlustgruendeblock />
            <Eigenschaftenblock />
          </>
        )}
        {bereich === "email" && (
          <>
            <Versandblock />
            <Marketingversandblock />
            <Postfachblock />
            <Postausgangblock />
          </>
        )}
        {bereich === "ki" && (
          <>
            <KIBlock e={e} />
            <Sprachausgabeblock e={e} />
            <AnreicherungEinstellungen einstellungen={e} />
            <Quellenblock />
          </>
        )}
        {bereich === "daten" && (
          <>
            <Sicherungsblock />
            <Datenwege e={e} />
          </>
        )}
      </div>
    </>
  );
}

export default function EinstellungenSeite() {
  return (
    <Suspense fallback={<Laedt />}>
      <Inhalt />
    </Suspense>
  );
}
