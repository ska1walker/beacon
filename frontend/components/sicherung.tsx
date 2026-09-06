"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, Download, Save } from "lucide-react";
import { useState } from "react";
import { api } from "@/lib/api";
import { datumZeit } from "@/lib/format";
import type { Sicherungsbilanz, Sicherungsstand, Wiederherstellung } from "@/lib/typen";
import { Fehler } from "@/components/zustaende";
import { Erklaerung } from "@/components/erklaerung";

function zeilenSumme(zeilen: Record<string, number>): number {
  return Object.values(zeilen).reduce((s, n) => s + n, 0);
}

export function Sicherungsblock() {
  const client = useQueryClient();
  const [bestaetigt, setBestaetigt] = useState<string | null>(null);

  const staende = useQuery({
    queryKey: ["sicherungsstaende"],
    queryFn: () => api.get<Sicherungsstand[]>("/api/sicherung/staende"),
  });

  const sichern = useMutation({
    mutationFn: () => api.post<Sicherungsbilanz>("/api/sicherung"),
    onSuccess: () => client.invalidateQueries({ queryKey: ["sicherungsstaende"] }),
  });

  const zurueck = useMutation({
    mutationFn: (name: string) =>
      api.post<Wiederherstellung>(`/api/sicherung/wiederherstellen?name=${encodeURIComponent(name)}`),
    onSuccess: () => {
      setBestaetigt(null);
      // Nach einer Wiederherstellung stimmt nichts mehr, was im
      // Zwischenspeicher liegt.
      client.invalidateQueries();
    },
  });

  const letzte = staende.data?.[0];

  return (
    <section className="block">
      <div className="block-kopf">
        <h2>Sicherung</h2>
        {letzte && (
          <span style={{ fontSize: "0.75rem", color: "var(--am-text-gedaempft)" }}>
            zuletzt {datumZeit(letzte.erstellt_am)}
          </span>
        )}
      </div>
      <div className="block-inhalt">
        <Erklaerung
          kurz="Beacon sichert Ihren Bestand regelmäßig auf dieser Box — und stellt ihn nach einer Neuinstallation von selbst wieder her."
          lang={<>Sobald sich etwas ändert, entsteht ein Abzug unter <code>/app/data</code> — auch die Einstellungen; die letzten vierzehn bleiben. Die Ausfuhr unten ist derselbe Stand als Datei — ohne den Zugangsschlüssel zum Sprachmodell.</>}
        />
        <div className="hinweis" data-art="achtung">
          <AlertTriangle size={16} aria-hidden="true" />
          <span>
            Eine Deinstallation über den Olares-Markt legt die Datenbank neu an. Der Abzug
            liegt daneben in <code>/app/data</code> und überlebt das — die Anwendung liest ihn
            beim ersten Start danach von allein zurück. Ohne Abzug wären Firmen, Kontakte,
            Geschäfte und der gesamte Verlauf weg.
          </span>
        </div>

        <p style={{ fontSize: "0.875rem", color: "var(--am-text-sekundaer)", margin: "var(--am-raum-4) 0" }}>
          Selbsttätig nach jeder Änderung, die letzten vierzehn Stände bleiben liegen.
        </p>

        <div className="btn-reihe">
          <button
            type="button"
            className="btn btn-primaer btn-klein"
            onClick={() => sichern.mutate()}
            disabled={sichern.isPending}
          >
            <Save size={14} aria-hidden="true" />
            {sichern.isPending ? "Sichert …" : "Jetzt sichern"}
          </button>
          <a className="btn btn-sekundaer btn-klein" href="/api/sicherung/ausfuhr" download>
            <Download size={14} aria-hidden="true" />
            Ausfuhr herunterladen
          </a>
        </div>

        {sichern.isError && <Fehler text={(sichern.error as Error).message} />}
        {sichern.data && (
          <p style={{ fontSize: "0.8125rem", color: "var(--am-erfolg)", marginTop: "var(--am-raum-3)" }}>
            {zeilenSumme(sichern.data.zeilen)} Zeilen gesichert in {sichern.data.datei}.
          </p>
        )}

        {zurueck.isError && <Fehler text={(zurueck.error as Error).message} />}
        {zurueck.data && (
          <div className="hinweis" style={{ marginTop: "var(--am-raum-3)" }}>
            <span>
              {zeilenSumme(zurueck.data.geschrieben)} Zeilen zurückgespielt,{" "}
              {zeilenSumme(zurueck.data.uebersprungen)} waren schon da.
            </span>
          </div>
        )}

        {staende.data && staende.data.length > 0 && (
          <div className="rollbar" style={{ marginTop: "var(--am-raum-6)" }}>
            <table className="tabelle">
              <thead>
                <tr>
                  <th>Stand</th>
                  <th style={{ textAlign: "right" }}>Größe</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {staende.data.map((s) => (
                  <tr key={s.name} style={{ cursor: "default" }}>
                    <td className="haupt">{datumZeit(s.erstellt_am)}</td>
                    <td className="zahl">{Math.round(s.groesse_bytes / 1024)} kB</td>
                    <td style={{ textAlign: "right" }}>
                      {bestaetigt === s.name ? (
                        <span className="btn-reihe" style={{ justifyContent: "flex-end" }}>
                          <button
                            type="button"
                            className="btn btn-primaer btn-klein"
                            onClick={() => zurueck.mutate(s.name)}
                            disabled={zurueck.isPending}
                          >
                            Wirklich zurückspielen
                          </button>
                          <button
                            type="button"
                            className="btn btn-still btn-klein"
                            onClick={() => setBestaetigt(null)}
                          >
                            Abbrechen
                          </button>
                        </span>
                      ) : (
                        <button
                          type="button"
                          className="btn btn-sekundaer btn-klein"
                          onClick={() => setBestaetigt(s.name)}
                        >
                          Zurückspielen
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            <p style={{ fontSize: "0.75rem", color: "var(--am-text-gedaempft)", marginTop: "var(--am-raum-2)" }}>
              Zurückspielen überschreibt nichts. Was heute da ist, bleibt — es wird nur
              ergänzt, was fehlt.
            </p>
          </div>
        )}
      </div>
    </section>
  );
}
