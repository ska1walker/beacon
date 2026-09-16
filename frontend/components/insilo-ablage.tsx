"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "@/lib/api";
import { anzahl, datumZeit } from "@/lib/format";
import type { InsiloAblage } from "@/lib/typen";
import { Erklaerung } from "@/components/erklaerung";
import { Schalter } from "@/components/schalter";
import { Fehler, Laedt } from "@/components/zustaende";

/**
 * Insilo auf derselben Box — über den gemeinsamen Ordner, wie Relay.
 *
 * Kein Webhook, kein Geheimnis: Insilo legt jedes fertige Protokoll in den
 * geteilten Ordner der Box, Beacon liest alle zwei Minuten mit. Dieser
 * Block sagt, ob das gerade geschieht, und beweist es mit „Jetzt lesen".
 */
export function InsiloAblageblock() {
  const client = useQueryClient();
  const stand = useQuery({
    queryKey: ["insilo-ablage"],
    queryFn: () => api.get<InsiloAblage>("/api/besprechungen/ablage"),
  });
  const [adresse, setAdresse] = useState<string | null>(null);

  const nachher = (neu?: InsiloAblage) => {
    if (neu) client.setQueryData(["insilo-ablage"], neu);
    else client.invalidateQueries({ queryKey: ["insilo-ablage"] });
  };

  const einstellen = useMutation({
    mutationFn: (felder: { aktiv?: boolean | null; adresse?: string | null }) =>
      api.put<InsiloAblage>("/api/besprechungen/ablage", felder),
    onSuccess: (neu) => {
      nachher(neu);
      setAdresse(null);
    },
  });
  const lesen = useMutation({
    mutationFn: () =>
      api.post<{
        dateien: number;
        neu: number;
        geaendert: number;
        entfernt: number;
        unlesbar: number;
        nicht_crm?: number;
        zurueckgezogen?: number;
      }>(
        "/api/besprechungen/ablage/lesen",
      ),
    onSuccess: () => {
      nachher();
      client.invalidateQueries({ queryKey: ["besprechungen"] });
      client.invalidateQueries({ queryKey: ["briefing"] });
    },
  });

  if (stand.isPending) return <Laedt />;
  if (stand.isError) return <Fehler text={(stand.error as Error).message} />;
  const s = stand.data;
  const feld = adresse ?? s.adresse ?? "";
  const geaendert = feld.trim() !== (s.adresse ?? "");

  const zustand = !s.eingehaengt
    ? { text: "nicht eingehängt", art: undefined }
    : s.fehler
      ? { text: "Ordner fehlt", art: "lost" }
      : s.aktiv
        ? { text: "liest mit", art: "won" }
        : { text: "aus", art: undefined };

  return (
    <section className="block">
      <div className="block-kopf">
        <h2>Insilo auf dieser Box</h2>
        <span className="stufe" data-art={zustand.art}>{zustand.text}</span>
      </div>
      <div className="block-inhalt">
        <Erklaerung
          kurz="Besprechungen aus Insilo, ohne Webhook: Beacon liest den Ordner, in den Insilo seine Protokolle legt."
          lang={
            <>
              Insilo legt jedes fertige Protokoll — ohne Wortlaut — in den gemeinsamen Ordner der Box.
              Beacon sieht dort alle zwei Minuten nach; Relay liest denselben Ordner. Nichts wird
              ungefragt einem Kunden zugeordnet. Den Ordner sehen alle Programme auf der Box, die
              ihn anfordern — wer Protokolle nur an Beacon geben will, nimmt stattdessen einen Webhook.
            </>
          }
        />

        {!s.eingehaengt ? (
          <p className="erfassung-hinweis">
            Diese Installation hat den gemeinsamen Ordner nicht bekommen. Er kommt mit dem Upgrade über
            den Markt; fehlt er danach, bringt ihn eine Neuinstallation. Bis dahin geht es über einen
            Webhook weiter unten.
          </p>
        ) : (
          <>
            <dl>
              <div className="eigenschaft">
                <dt>Im Ordner</dt>
                <dd>{s.ordner_da ? anzahl(s.dateien, "Protokoll", "Protokolle") : "noch kein Ordner — Insilo legt ihn beim ersten Protokoll an"}</dd>
              </div>
              <div className="eigenschaft">
                <dt>Übernommen</dt>
                <dd>{anzahl(s.uebernommen, "Besprechung", "Besprechungen")}</dd>
              </div>
              <div className="eigenschaft">
                <dt>Zuletzt gelesen</dt>
                <dd>{s.zuletzt ? datumZeit(s.zuletzt) : "seit dem Start noch nicht"}</dd>
              </div>
            </dl>
            {s.fehler && <Fehler text={s.fehler} />}

            <p className="feld-hinweis">
              Übernommen werden nur Kundengespräche: welche Vorlagen dazu zählen, legt man in Insilo
              unter Einstellungen › Vorlagen für Zusammenfassungen fest. Interne Runden und Notizen bleiben draußen. Was schon
              einem Kunden zugeordnet ist, bleibt auch dann, wenn die Vorlage später umgestellt wird.
            </p>

            <Schalter
              an={s.aktiv}
              umschalten={(an) => einstellen.mutate({ aktiv: an })}
              text="Besprechungen aus dem Ordner übernehmen"
              hinweis={
                s.einstellung === null
                  ? s.organisationen === 1
                    ? "Von selbst an: Beacon hat auf dieser Box nur eine Organisation."
                    : "Von selbst aus: Auf dieser Box gibt es mehrere Organisationen — nur die, die hier einschaltet, bekommt die Gespräche."
                  : undefined
              }
            />

            <div className="btn-reihe" style={{ marginBlock: "var(--am-raum-3)" }}>
              <button type="button" className="btn btn-sekundaer btn-klein" onClick={() => lesen.mutate()} disabled={lesen.isPending}>
                {lesen.isPending ? "Liest …" : "Jetzt lesen"}
              </button>
              {lesen.isSuccess && (
                <span className="feld-hinweis" style={{ margin: 0 }}>
                  {lesen.data.neu || lesen.data.geaendert || lesen.data.entfernt
                    ? `${lesen.data.neu} neu, ${lesen.data.geaendert} geändert, ${lesen.data.entfernt} entfernt`
                    : "Nichts Neues."}
                  {lesen.data.unlesbar > 0 && ` ${anzahl(lesen.data.unlesbar, "Datei", "Dateien")} in einem unbekannten Format übersprungen.`}
                  {(lesen.data.nicht_crm ?? 0) > 0 &&
                    ` ${anzahl(lesen.data.nicht_crm ?? 0, "Besprechung", "Besprechungen")} in Insilo nicht als Kundengespräch markiert.`}
                  {(lesen.data.zurueckgezogen ?? 0) > 0 &&
                    ` Davon ${lesen.data.zurueckgezogen} zurückgezogen.`}
                </span>
              )}
            </div>
            {lesen.isError && <Fehler text={(lesen.error as Error).message} />}
          </>
        )}

        <form
          className="feld"
          onSubmit={(e) => {
            e.preventDefault();
            einstellen.mutate({ adresse: feld.trim() || null });
          }}
        >
          <label htmlFor="insilo-ablage-adresse">
            Adresse von Insilo <span className="optional">optional</span>
          </label>
          <div style={{ display: "flex", gap: "var(--am-raum-2)" }}>
            <input
              id="insilo-ablage-adresse"
              value={feld}
              onChange={(e) => setAdresse(e.target.value)}
              placeholder="https://e5d605f30.ihr-name.olares.de"
              style={{ flex: 1 }}
            />
            <button type="submit" className="btn btn-sekundaer" disabled={!geaendert || einstellen.isPending}>
              Speichern
            </button>
          </div>
          <p className="feld-hinweis">Dann führt jede Besprechung mit „In Insilo öffnen" zum Wortlaut.</p>
        </form>
        {einstellen.isError && <Fehler text={(einstellen.error as Error).message} />}
      </div>
    </section>
  );
}
