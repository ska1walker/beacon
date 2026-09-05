"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { datumZeit, EINWILLIGUNG_TEXT } from "@/lib/format";
import type { Contact, OrgSettings } from "@/lib/typen";
import { Fehler } from "@/components/zustaende";

/**
 * Die Marketing-Einwilligung am Kontakt — mit Beleg.
 *
 * Drei Handgriffe, mehr nicht: Bestätigung anfordern (Double-Opt-In),
 * als Bestandskunde kennzeichnen (§7 Abs. 3 UWG — bewusst, mit Namen),
 * zurücksetzen. `bestaetigt` entsteht nur über den Link in der Mail;
 * hier gibt es keinen Knopf dafür, und das ist die ganze Idee.
 */
export function Einwilligungsblock({ kontakt }: { kontakt: Contact }) {
  const client = useQueryClient();
  const einstellungen = useQuery({
    queryKey: ["einstellungen"],
    queryFn: () => api.get<OrgSettings>("/api/settings"),
    staleTime: 60_000,
  });

  const setzen = useMutation({
    mutationFn: (aktion: "anfragen" | "bestandskunde" | "keine") =>
      api.post<Contact>(`/api/contacts/${kontakt.id}/einwilligung`, { aktion }),
    onSuccess: () => {
      client.invalidateQueries({ queryKey: ["kontakt", kontakt.id] });
      client.invalidateQueries({ queryKey: ["aktivitaeten"] });
    },
  });

  const stand = kontakt.marketing_einwilligung;
  const art =
    stand === "bestaetigt" || stand === "bestandskunde" ? "won"
    : stand === "abgemeldet" ? "lost"
    : undefined;
  const beleg = kontakt.einwilligung_nachweis;
  const versandBereit = einstellungen.data?.smtp_ready && !!einstellungen.data?.links_basis_wirksam;
  const versandHinweis = !einstellungen.data?.smtp_ready
    ? "Kein SMTP-Konto — unter Einstellungen → Versand einrichten."
    : !einstellungen.data?.links_basis_wirksam
      ? "Die Adresse der öffentlichen Links fehlt — unter Einstellungen → Marketing-Versand."
      : undefined;

  return (
    <section className="block">
      <div className="block-kopf">
        <h2>Marketing-Einwilligung</h2>
        <span className="stufe" data-art={art}>{EINWILLIGUNG_TEXT[stand] ?? stand}</span>
      </div>
      <div className="block-inhalt">
        <dl>
          {kontakt.einwilligung_am && (
            <div className="eigenschaft">
              <dt>Seit</dt>
              <dd>{datumZeit(kontakt.einwilligung_am)}{kontakt.einwilligung_quelle ? ` · ${kontakt.einwilligung_quelle}` : ""}</dd>
            </div>
          )}
          {stand === "angefragt" && beleg?.angefragt_am && (
            <div className="eigenschaft">
              <dt>Angefragt</dt>
              <dd>{datumZeit(beleg.angefragt_am)} — wartet auf den Klick in der Mail</dd>
            </div>
          )}
          {kontakt.abgemeldet_am && (
            <div className="eigenschaft">
              <dt>Abgemeldet</dt>
              <dd>{datumZeit(kontakt.abgemeldet_am)}</dd>
            </div>
          )}
          {stand === "bestaetigt" && beleg && (
            <div className="eigenschaft">
              <dt>Beleg</dt>
              <dd style={{ fontSize: "0.8125rem" }}>
                {[beleg.adresse && `von ${beleg.adresse}`, beleg.programm && `mit ${beleg.programm.slice(0, 60)}`]
                  .filter(Boolean).join(", ") || "vorhanden"}
              </dd>
            </div>
          )}
        </dl>

        <p style={{ fontSize: "0.8125rem", color: "var(--am-text-sekundaer)", margin: "var(--am-raum-3) 0" }}>
          {stand === "keine" && "Ohne Einwilligung geht keine Marketing-Post hinaus. Bestätigen kann nur der Kontakt selbst — über den Link in der Mail."}
          {stand === "angefragt" && "Die Bestätigungsmail ist draußen. Der Link darin gilt sieben Tage."}
          {stand === "bestaetigt" && "Belegt durch Double-Opt-In. Der Abmeldelink in jeder Mail nimmt sie zurück."}
          {stand === "bestandskunde" && "Ausnahme aus §7 Abs. 3 UWG: bewusst gesetzt, nicht abgeleitet. Gilt nur für Werbung zu ähnlichen Leistungen."}
          {stand === "abgemeldet" && "Der Kontakt hat sich abgemeldet. Das gilt, bis er selbst neu bestätigt."}
        </p>

        {setzen.isError && <Fehler text={(setzen.error as Error).message} />}

        <div className="btn-reihe">
          {stand !== "bestaetigt" && (
            <button
              type="button"
              className="btn btn-sekundaer btn-klein"
              disabled={setzen.isPending || !kontakt.email || !versandBereit}
              title={!kontakt.email ? "Der Kontakt hat keine E-Mail-Adresse." : versandHinweis}
              onClick={() => setzen.mutate("anfragen")}
            >
              {stand === "angefragt" ? "Bestätigung erneut anfordern" : "Bestätigung anfordern"}
            </button>
          )}
          {stand !== "bestandskunde" && stand !== "bestaetigt" && (
            <button
              type="button"
              className="btn btn-still btn-klein"
              disabled={setzen.isPending}
              onClick={() => setzen.mutate("bestandskunde")}
            >
              Als Bestandskunde kennzeichnen
            </button>
          )}
          {stand !== "keine" && (
            <button
              type="button"
              className="btn btn-still btn-klein"
              disabled={setzen.isPending}
              onClick={() => setzen.mutate("keine")}
            >
              Zurücksetzen
            </button>
          )}
        </div>
        {versandHinweis && stand !== "bestaetigt" && (
          <p style={{ fontSize: "0.75rem", color: "var(--am-text-gedaempft)", marginTop: "var(--am-raum-2)" }}>{versandHinweis}</p>
        )}
      </div>
    </section>
  );
}
