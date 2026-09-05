"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { OrgSettings } from "@/lib/typen";
import { Seitenkopf } from "@/components/seitenkopf";
import { Fehler, Laedt } from "@/components/zustaende";
import { Sicherungsblock } from "@/components/sicherung";
import { Absenderblock } from "@/components/absender";
import { Quellenblock } from "@/components/quellen";
import { Postfachblock } from "@/components/postfach";
import { Mitgliederblock } from "@/components/mitglieder";
import { Eigenschaftenblock } from "@/components/eigenschaften-verwalten";
import { Pipelinesblock } from "@/components/pipelines-verwalten";
import { Katalogblock, Verlustgruendeblock } from "@/components/katalog";
import { Postausgangblock } from "@/components/postausgang";
import { AnreicherungEinstellungen } from "@/components/anreicherung-einstellungen";

export default function EinstellungenSeite() {
  const client = useQueryClient();

  const abfrage = useQuery({
    queryKey: ["einstellungen"],
    queryFn: () => api.get<OrgSettings>("/api/settings"),
  });

  const [adresse, setAdresse] = useState("");
  const [modell, setModell] = useState("");
  const [schluessel, setSchluessel] = useState("");

  useEffect(() => {
    if (abfrage.data) {
      setAdresse(abfrage.data.llm_base_url);
      setModell(abfrage.data.llm_model);
    }
  }, [abfrage.data]);

  const speichern = useMutation({
    mutationFn: () =>
      api.put<OrgSettings>("/api/settings", {
        llm_base_url: adresse,
        llm_model: modell,
        // Leer heißt „nicht angefasst" — das Backend lässt den
        // hinterlegten Schlüssel dann stehen. Er kommt nie zurück an
        // die Oberfläche, also käme er sonst bei jedem Speichern leer
        // an und wäre nach dem ersten Feldwechsel weg.
        llm_api_key: schluessel,
      }),
    onSuccess: () => {
      setSchluessel("");
      client.invalidateQueries({ queryKey: ["einstellungen"] });
      client.invalidateQueries({ queryKey: ["ki-status"] });
    },
  });

  if (abfrage.isPending) return <Laedt />;
  if (abfrage.isError) return <Fehler text={(abfrage.error as Error).message} />;

  const e = abfrage.data!;

  return (
    <>
      <Seitenkopf titel="Einstellungen" />

      <div className="datensatz" style={{ gridTemplateColumns: "minmax(0, 640px)" }}>
        <section className="block">
          <div className="block-kopf">
            <h2>Sprachmodell</h2>
            <span className="stufe" data-art={e.llm_ready ? "won" : undefined}>
              {e.llm_ready ? "eingerichtet" : "nicht eingerichtet"}
            </span>
          </div>
          <div className="block-inhalt">
            <p style={{ fontSize: "0.875rem", color: "var(--am-text-sekundaer)", marginBottom: "var(--am-raum-6)" }}>
              aicrm bringt kein eigenes Modell mit. Es spricht einen OpenAI-kompatiblen Endpunkt
              an — üblicherweise die LiteLLM-App auf dieser Box. Es gibt bewusst keine Vorgabe:
              Jede geratene Adresse wäre auf einer anderen Box falsch. Solange hier nichts steht,
              bleiben die KI-Funktionen gesperrt und sagen das — statt in einen Verbindungsfehler
              zu laufen.
            </p>

            <form
              onSubmit={(ev) => {
                ev.preventDefault();
                speichern.mutate();
              }}
            >
              <div className="feld">
                <label htmlFor="adresse">Adresse des Endpunkts</label>
                <input
                  id="adresse"
                  value={adresse}
                  onChange={(ev) => setAdresse(ev.target.value)}
                  placeholder="https://litellm-beispiel.olares.com/v1"
                />
                <p className="feld-hinweis">
                  Mit <code>/v1</code> am Ende. aicrm hängt <code>/chat/completions</code> an.
                </p>
              </div>

              <div className="feld">
                <label htmlFor="modell">Modellname</label>
                <input
                  id="modell"
                  value={modell}
                  onChange={(ev) => setModell(ev.target.value)}
                  placeholder="aim-qwen3.6-35b"
                />
              </div>

              <div className="feld">
                <label htmlFor="schluessel">
                  Zugangsschlüssel <span className="optional">optional</span>
                </label>
                <input
                  id="schluessel"
                  type="password"
                  value={schluessel}
                  onChange={(ev) => setSchluessel(ev.target.value)}
                  placeholder={e.llm_api_key_set ? "hinterlegt — leer lassen, um ihn zu behalten" : "keiner hinterlegt"}
                  autoComplete="off"
                />
                <p className="feld-hinweis">
                  Ein Endpunkt auf der eigenen Box verlangt meist keinen.
                </p>
              </div>

              {speichern.isError && <Fehler text={(speichern.error as Error).message} />}

              <div className="btn-reihe">
                <button type="submit" className="btn btn-primaer" disabled={speichern.isPending}>
                  {speichern.isPending ? "Wird gespeichert …" : "Speichern"}
                </button>
                {speichern.isSuccess && (
                  <span style={{ fontSize: "0.8125rem", color: "var(--am-erfolg)" }}>
                    Gespeichert.
                  </span>
                )}
              </div>
            </form>
          </div>
        </section>

        <AnreicherungEinstellungen einstellungen={e} />

        <Mitgliederblock />

        <Pipelinesblock />

        <Eigenschaftenblock />

        <Katalogblock />

        <Verlustgruendeblock />

        <Postausgangblock />

        <Absenderblock />

        <Postfachblock />

        <Quellenblock />

        <Sicherungsblock />

        <section className="block">
          <div className="block-kopf">
            <h2>Wohin Daten gehen</h2>
          </div>
          <div className="block-inhalt">
            <dl>
              <div className="eigenschaft">
                <dt>Datenbank, Suche, Anhänge</dt>
                <dd>auf dieser Box</dd>
              </div>
              <div className="eigenschaft">
                <dt>Sprachmodell</dt>
                <dd>{e.llm_ready ? adresse : "nicht eingerichtet — keine Anfragen"}</dd>
              </div>
              <div className="eigenschaft">
                <dt>Anreicherung</dt>
                <dd>
                  {e.suche_endpoint_url
                    ? `Firmen- und Personennamen an ${e.suche_endpoint_url}; Websites der Firmen`
                    : "nur die Websites der Firmen — kein Suchdienst eingetragen"}
                </dd>
              </div>
              <div className="eigenschaft">
                <dt>Telemetrie</dt>
                <dd>keine</dd>
              </div>
            </dl>
            <p style={{ fontSize: "0.8125rem", color: "var(--am-text-gedaempft)", marginTop: "var(--am-raum-4)" }}>
              Steht oben eine fremde Adresse, gehen die Inhalte der Anfragen dorthin. Diese Zeile
              nennt sie deshalb beim Namen, statt pauschal „lokal" zu behaupten.
            </p>
          </div>
        </section>
      </div>
    </>
  );
}
