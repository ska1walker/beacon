"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "@/lib/api";
import type { OrgSettings, Ticket } from "@/lib/typen";
import { Fehler } from "@/components/zustaende";

/**
 * Die Antwort an den, der geschrieben hat — per Mail, am Faden.
 *
 * Der Empfänger steht fest: der Kontakt, sonst die Absenderadresse aus
 * dem Eingang. Kam das Ticket per Mail, hängt die Antwort mit
 * `In-Reply-To` an der Anfrage; die Kennung im Betreff hält den Faden
 * auch dann, wenn ein Mailprogramm die Kopfzeile verliert. Danach steht
 * die erste Antwort fest, und das Ticket wartet auf den Kontakt.
 */
export function Ticketantwort({ ticket }: { ticket: Ticket }) {
  const client = useQueryClient();
  const [text, setText] = useState("");
  const [betreff, setBetreff] = useState("");
  const einstellungen = useQuery({
    queryKey: ["einstellungen"],
    queryFn: () => api.get<OrgSettings>("/api/settings"),
    staleTime: 60_000,
  });

  const senden = useMutation({
    mutationFn: () =>
      api.post<Ticket>(`/api/tickets/${ticket.id}/antworten`, { text, betreff: betreff || null }),
    onSuccess: () => {
      setText("");
      setBetreff("");
      client.invalidateQueries({ queryKey: ["ticket", ticket.id] });
      client.invalidateQueries({ queryKey: ["ticket-brett"] });
      client.invalidateQueries({ queryKey: ["aktivitaeten"] });
    },
  });

  const an = ticket.kontakt_email || ticket.absender_email;
  const bereit = einstellungen.data?.smtp_ready ?? false;

  return (
    <section className="block">
      <div className="block-kopf">
        <h2>Antworten</h2>
        {an && <span style={{ fontSize: "0.8125rem", color: "var(--am-text-sekundaer)" }}>an {an}</span>}
      </div>
      <div className="block-inhalt">
        {!an && (
          <p style={{ fontSize: "0.875rem", color: "var(--am-text-sekundaer)" }}>
            Dieses Ticket hat keine Adresse, an die eine Antwort gehen könnte. Kontakt zuordnen,
            dann geht es hier weiter.
          </p>
        )}
        {an && !bereit && (
          <div className="hinweis" data-art="achtung">
            <span>Kein SMTP-Konto eingerichtet — unter Einstellungen → E-Mail nachholen.</span>
          </div>
        )}
        {an && (
          <>
            <div className="feld" style={{ marginTop: bereit ? 0 : "var(--am-raum-3)" }}>
              <label htmlFor="antwort-betreff">Betreff <span className="optional">optional</span></label>
              <input
                id="antwort-betreff"
                value={betreff}
                onChange={(e) => setBetreff(e.target.value)}
                placeholder={`AW: ${ticket.betreff} [${ticket.kennung}]`}
                disabled={!bereit}
              />
            </div>
            <div className="notiz-feld">
              <textarea
                rows={7}
                value={text}
                onChange={(e) => setText(e.target.value)}
                aria-label="Antwort"
                placeholder="Guten Tag, …"
                disabled={!bereit}
              />
            </div>
            {senden.isError && <Fehler text={(senden.error as Error).message} />}
            {senden.isSuccess && (
              <p style={{ fontSize: "0.8125rem", color: "var(--am-erfolg)" }}>
                Gesendet — steht im Verlauf, das Ticket wartet jetzt auf den Kontakt.
              </p>
            )}
            <div className="btn-reihe" style={{ marginTop: "var(--am-raum-3)" }}>
              <button
                type="button"
                className="btn btn-primaer btn-klein"
                disabled={!bereit || !text.trim() || senden.isPending}
                onClick={() => senden.mutate()}
              >
                {senden.isPending ? "Schickt …" : "Per E-Mail antworten"}
              </button>
            </div>
          </>
        )}
      </div>
    </section>
  );
}
