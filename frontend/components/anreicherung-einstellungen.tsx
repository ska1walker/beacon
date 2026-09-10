"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { OrgSettings } from "@/lib/typen";
import { Fehler } from "@/components/zustaende";
import { Erklaerung } from "@/components/erklaerung";
import { Schalter } from "@/components/schalter";

/**
 * Woher die Anreicherung liest und was sie von selbst schreiben darf.
 *
 * Die Website der Firma liest sie immer. Für alles darüber hinaus —
 * Website finden, LinkedIn-Seiten über Suchtreffer — braucht sie einen
 * Suchdienst, und der steht hier oder gar nicht.
 */
export function AnreicherungEinstellungen({ einstellungen }: { einstellungen: OrgSettings }) {
  const client = useQueryClient();
  const [adresse, setAdresse] = useState(einstellungen.suche_endpoint_url ?? "");
  const [schluessel, setSchluessel] = useState("");
  const [region, setRegion] = useState(einstellungen.suche_region ?? "DE");
  const [automatisch, setAutomatisch] = useState(einstellungen.anreicherung_automatisch);
  const [uebernahme, setUebernahme] = useState<OrgSettings["anreicherung_uebernahme"]>(einstellungen.anreicherung_uebernahme);

  useEffect(() => {
    setAdresse(einstellungen.suche_endpoint_url ?? "");
    setRegion(einstellungen.suche_region ?? "DE");
    setAutomatisch(einstellungen.anreicherung_automatisch);
    setUebernahme(einstellungen.anreicherung_uebernahme);
  }, [einstellungen]);

  const speichern = useMutation({
    mutationFn: () =>
      api.put<OrgSettings>("/api/settings", {
        suche_endpoint_url: adresse.trim() || null,
        // Leer heißt „nicht angefasst" — wie beim Modellschlüssel.
        suche_api_key: schluessel,
        suche_region: region,
        anreicherung_automatisch: automatisch,
        anreicherung_uebernahme: uebernahme,
      }),
    onSuccess: () => {
      setSchluessel("");
      client.invalidateQueries({ queryKey: ["einstellungen"] });
      client.invalidateQueries({ queryKey: ["anreicherung-status"] });
    },
  });

  const eingerichtet = Boolean(einstellungen.suche_endpoint_url);

  return (
    <section className="block">
      <div className="block-kopf">
        <h2>Automatisch ergänzen</h2>
        <span className="stufe" data-art={eingerichtet ? "won" : undefined}>
          {eingerichtet ? "mit Suchdienst" : "nur Firmen-Website"}
        </span>
      </div>
      <div className="block-inhalt">
        <Erklaerung kurz="Beacon ergänzt Firmen und Kontakte aus öffentlichen Quellen und findet beim Anlegen, wen Sie beschreiben — nie wird etwas überschrieben." lang={<>Neue Firmen und Kontakte werden aus öffentlichen Quellen ergänzt: Impressum, Kontakt- und
          Team-Seiten der Firmen-Website, dazu die Treffer eines Suchdienstes — darüber auch
          LinkedIn-Seiten und -Profile, ohne LinkedIn selbst abzurufen. Jeder Wert nennt seine
          Quelle; Kontaktdaten müssen wörtlich dort stehen. Was schon eingetragen ist, wird nie
          überschrieben.</>} />

        <form
          onSubmit={(ev) => {
            ev.preventDefault();
            speichern.mutate();
          }}
        >
          <div className="feld">
            <label htmlFor="suche-adresse">
              Suchdienst <span className="optional">optional</span>
            </label>
            <input
              id="suche-adresse"
              value={adresse}
              onChange={(ev) => setAdresse(ev.target.value)}
              placeholder="https://searxng-beispiel.olares.com"
            />
            <p className="feld-hinweis">
              Drei Adressen, die Beacon am Namen erkennt: eine SearXNG-Instanz auf dieser Box,{" "}
              <code>https://api.tavily.com/search</code> oder{" "}
              <code>https://api.search.brave.com/res/v1/web/search</code>. Ohne Suchdienst wird nur
              die Website der Firma gelesen — Firmennamen verlassen die Box dann nicht.
            </p>
          </div>

          <div className="feld">
            <label htmlFor="suche-schluessel">
              Zugangsschlüssel <span className="optional">optional</span>
            </label>
            <input
              id="suche-schluessel"
              type="password"
              value={schluessel}
              onChange={(ev) => setSchluessel(ev.target.value)}
              placeholder={einstellungen.suche_api_key_kennung ? `${einstellungen.suche_api_key_kennung} — leer lassen, um ihn zu behalten` : "keiner hinterlegt"}
              autoComplete="off"
            />
            <p className="feld-hinweis">
              Tavily und Brave verlangen einen; eine eigene SearXNG-Instanz meist nicht.
              Wechselt die Adresse den Dienst, wird der hinterlegte Schlüssel verworfen — er gilt
              nur für den, bei dem er ausgestellt wurde.
            </p>
          </div>

          <div className="feld">
            <label htmlFor="suche-region">Region der Suche</label>
            <select id="suche-region" value={region} onChange={(ev) => setRegion(ev.target.value)}>
              <option value="DE">Deutschland</option>
              <option value="AT">Österreich</option>
              <option value="CH">Schweiz</option>
              <option value="NL">Niederlande</option>
              <option value="FR">Frankreich</option>
              <option value="GB">Großbritannien</option>
              <option value="US">USA</option>
              <option value="">Keine Vorgabe</option>
            </select>
            <p className="feld-hinweis">„Baustoffhandel“ ohne Land liefert Fürth, wenn Sie Tecklenburg meinen.</p>
          </div>

          <Schalter
            an={automatisch}
            umschalten={setAutomatisch}
            text="Beim Anlegen von selbst anreichern"
            hinweis="Abgeschaltet läuft die Anreicherung nur auf Knopfdruck am Datensatz."
          />

          <div className="feld">
            <label htmlFor="uebernahme">Was ohne Rückfrage geschrieben wird</label>
            <select id="uebernahme" value={uebernahme} onChange={(ev) => setUebernahme(ev.target.value as OrgSettings["anreicherung_uebernahme"])}>
              <option value="leere_felder">Leere Felder füllen — Abweichungen und Beschreibung bleiben Vorschlag</option>
              <option value="vorschlag">Nichts — alles bleibt Vorschlag, bis jemand übernimmt</option>
            </select>
          </div>

          {speichern.isError && <Fehler text={(speichern.error as Error).message} />}

          <div className="btn-reihe">
            <button type="submit" className="btn btn-primaer" disabled={speichern.isPending}>
              {speichern.isPending ? "Wird gespeichert …" : "Speichern"}
            </button>
            {speichern.isSuccess && (
              <span style={{ fontSize: "0.8125rem", color: "var(--am-erfolg)" }}>Gespeichert.</span>
            )}
          </div>
        </form>
      </div>
    </section>
  );
}
