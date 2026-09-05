"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { datumZeit } from "@/lib/format";
import type { OrgSettings } from "@/lib/typen";
import { Fehler } from "@/components/zustaende";
import { Erklaerung } from "@/components/erklaerung";

/**
 * Das SMTP-Konto, aus dem transaktionale Post kommt: Ticket-Antworten,
 * Bestätigungsmails, die Ansprache aus dem Kontakt.
 *
 * Getrennt vom Marketing-Versand — HubSpot tut dasselbe: Ein gesperrtes
 * Marketing-Konto darf keine Antwort an einen Kunden aufhalten. Der Knopf
 * „Testmail“ ist keine Zugabe: Zugangsdaten, die erst bei der ersten
 * Antwort scheitern, sind keine Einrichtung.
 */
export function Versandblock() {
  const client = useQueryClient();
  const einstellungen = useQuery({
    queryKey: ["einstellungen"],
    queryFn: () => api.get<OrgSettings>("/api/settings"),
  });

  const [host, setHost] = useState("");
  const [port, setPort] = useState("587");
  const [sicherheit, setSicherheit] = useState<"starttls" | "ssl" | "keine">("starttls");
  const [benutzer, setBenutzer] = useState("");
  const [passwort, setPasswort] = useState("");
  const [absender, setAbsender] = useState("");
  const [absenderName, setAbsenderName] = useState("");
  const [test, setTest] = useState<string | null>(null);

  const e = einstellungen.data;
  useEffect(() => {
    if (!e) return;
    setHost(e.smtp_host ?? "");
    setPort(String(e.smtp_port ?? 587));
    setSicherheit((e.smtp_sicherheit as "starttls" | "ssl" | "keine") ?? "starttls");
    setBenutzer(e.smtp_benutzer ?? "");
    setAbsender(e.smtp_absender ?? "");
    setAbsenderName(e.smtp_absender_name ?? "");
  }, [e]);

  const speichern = useMutation({
    mutationFn: () =>
      api.put<OrgSettings>("/api/settings", {
        smtp_host: host || null,
        smtp_port: Number(port) || 587,
        smtp_sicherheit: sicherheit,
        smtp_benutzer: benutzer || null,
        // Leer heißt „nicht anfassen“ — sonst wäre das Passwort nach dem
        // ersten Speichern weg.
        ...(passwort ? { smtp_passwort: passwort } : {}),
        smtp_absender: absender || null,
        smtp_absender_name: absenderName || null,
      }),
    onSuccess: () => {
      setPasswort("");
      client.invalidateQueries({ queryKey: ["einstellungen"] });
      client.invalidateQueries({ queryKey: ["post-status"] });
    },
  });

  const testen = useMutation({
    mutationFn: () => api.post<{ an: string }>("/api/settings/versand/testen"),
    onSuccess: (a) => {
      setTest(a.an);
      client.invalidateQueries({ queryKey: ["einstellungen"] });
    },
  });

  return (
    <section className="block">
      <div className="block-kopf">
        <h2>E-Mail-Konto</h2>
        <span className="stufe" data-art={e?.smtp_ready ? "won" : undefined}>
          {e?.smtp_ready ? "eingerichtet" : "nicht eingerichtet"}
        </span>
      </div>
      <div className="block-inhalt">
        <Erklaerung kurz="Das E-Mail-Konto, aus dem Beacon Antworten und Bestätigungen schickt." lang={<>Das Konto, aus dem Antworten auf Tickets, Bestätigungsmails und die Ansprache aus dem
          Kontakt kommen. Ein gewöhnliches SMTP-Konto — dasselbe, das Relay oder Ihr Mailprogramm
          benutzt. Jede Mail steht danach im Verlauf des Kontakts, mit dem Faden zur Anfrage.</>} />

        <div style={{ display: "grid", gridTemplateColumns: "minmax(0, 2fr) minmax(0, 1fr) minmax(0, 1.4fr)", gap: "0 var(--am-raum-4)" }}>
          <div className="feld">
            <label htmlFor="smtp-host">SMTP-Server</label>
            <input id="smtp-host" value={host} onChange={(x) => setHost(x.target.value)} placeholder="smtp.beispiel.de" />
          </div>
          <div className="feld">
            <label htmlFor="smtp-port">Port</label>
            <input id="smtp-port" type="number" value={port} onChange={(x) => setPort(x.target.value)} />
          </div>
          <div className="feld">
            <label htmlFor="smtp-sicherheit">Verschlüsselung</label>
            <select id="smtp-sicherheit" value={sicherheit} onChange={(x) => setSicherheit(x.target.value as "starttls" | "ssl" | "keine")}>
              <option value="starttls">STARTTLS (587)</option>
              <option value="ssl">SSL/TLS (465)</option>
              <option value="keine">keine</option>
            </select>
          </div>
        </div>

        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "0 var(--am-raum-4)" }}>
          <div className="feld">
            <label htmlFor="smtp-benutzer">Benutzer</label>
            <input id="smtp-benutzer" value={benutzer} onChange={(x) => setBenutzer(x.target.value)} placeholder="kai@aimighty.de" />
          </div>
          <div className="feld">
            <label htmlFor="smtp-passwort">
              Passwort {e?.smtp_passwort_set && <span className="optional">hinterlegt</span>}
            </label>
            <input
              id="smtp-passwort"
              type="password"
              value={passwort}
              autoComplete="new-password"
              onChange={(x) => setPasswort(x.target.value)}
              placeholder={e?.smtp_passwort_set ? "leer lassen, um es zu behalten" : ""}
            />
          </div>
        </div>

        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "0 var(--am-raum-4)" }}>
          <div className="feld">
            <label htmlFor="smtp-absender">Absenderadresse</label>
            <input id="smtp-absender" type="email" value={absender} onChange={(x) => setAbsender(x.target.value)} placeholder="support@aimighty.de" />
            <p className="feld-hinweis">Muss zum Konto passen — sonst lehnt der Server ab.</p>
          </div>
          <div className="feld">
            <label htmlFor="smtp-absender-name">Absendername</label>
            <input id="smtp-absender-name" value={absenderName} onChange={(x) => setAbsenderName(x.target.value)} placeholder="AImighty Support" />
          </div>
        </div>

        {e?.smtp_letzter_fehler && (
          <div style={{ marginTop: "var(--am-raum-3)" }}>
            <Fehler text={`Letzter Versuch: ${e.smtp_letzter_fehler}`} />
          </div>
        )}
        {speichern.isError && <Fehler text={(speichern.error as Error).message} />}
        {testen.isError && <Fehler text={(testen.error as Error).message} />}
        {test && !testen.isError && (
          <p className="erfassung-hinweis">Testmail ist unterwegs an {test}.</p>
        )}

        <div className="btn-reihe" style={{ marginTop: "var(--am-raum-4)" }}>
          <button type="button" className="btn btn-primaer" disabled={speichern.isPending} onClick={() => speichern.mutate()}>
            {speichern.isPending ? "Speichert …" : "Speichern"}
          </button>
          <button
            type="button"
            className="btn btn-sekundaer"
            disabled={testen.isPending || !e?.smtp_ready}
            title={e?.smtp_ready ? undefined : "Erst speichern — Server und Absenderadresse fehlen."}
            onClick={() => testen.mutate()}
          >
            {testen.isPending ? "Schickt …" : "Testmail an mich"}
          </button>
          {e?.smtp_zuletzt && (
            <span style={{ fontSize: "0.75rem", color: "var(--am-text-gedaempft)", alignSelf: "center" }}>
              zuletzt {datumZeit(e.smtp_zuletzt)}
            </span>
          )}
        </div>
      </div>
    </section>
  );
}

/**
 * Was Marketing-Post braucht und transaktionale nicht: einen Weg, der
 * Zustellbarkeit trägt (Dienst oder dasselbe Konto), die Adresse, unter
 * der Bestätigen und Abmelden erreichbar sind, und die Bestätigungsmail.
 */
export function Marketingversandblock() {
  const client = useQueryClient();
  const einstellungen = useQuery({
    queryKey: ["einstellungen"],
    queryFn: () => api.get<OrgSettings>("/api/settings"),
  });

  const [weg, setWeg] = useState<"smtp" | "brevo">("smtp");
  const [brevo, setBrevo] = useState("");
  const [absender, setAbsender] = useState("");
  const [absenderName, setAbsenderName] = useState("");
  const [basis, setBasis] = useState("");
  const [doiBetreff, setDoiBetreff] = useState("");
  const [doiText, setDoiText] = useState("");

  const e = einstellungen.data;
  useEffect(() => {
    if (!e) return;
    setWeg((e.marketing_versand as "smtp" | "brevo") ?? "smtp");
    setAbsender(e.marketing_absender ?? "");
    setAbsenderName(e.marketing_absender_name ?? "");
    setBasis(e.links_basis_url ?? "");
    setDoiBetreff(e.doi_betreff ?? "");
    setDoiText(e.doi_text ?? "");
  }, [e]);

  const speichern = useMutation({
    mutationFn: () =>
      api.put<OrgSettings>("/api/settings", {
        marketing_versand: weg,
        ...(brevo ? { brevo_api_key: brevo } : {}),
        marketing_absender: absender || null,
        marketing_absender_name: absenderName || null,
        links_basis_url: basis || null,
        doi_betreff: doiBetreff || null,
        doi_text: doiText || null,
      }),
    onSuccess: () => {
      setBrevo("");
      client.invalidateQueries({ queryKey: ["einstellungen"] });
    },
  });

  return (
    <section className="block">
      <div className="block-kopf">
        <h2>Marketing-Mails</h2>
        {e?.links_basis_wirksam ? (
          <span className="stufe" data-art="won">Links erreichbar</span>
        ) : (
          <span className="stufe">Adresse der Links fehlt</span>
        )}
      </div>
      <div className="block-inhalt">
        <Erklaerung kurz="Marketing-Mails gehen nur an Kontakte mit Einwilligung und tragen immer einen Abmeldelink." lang={<>Marketing-Post geht nur an Kontakte mit belegter Einwilligung — Double-Opt-In oder
          Bestandskunde — und trägt immer einen Abmeldelink. Bestätigen und Abmelden laufen
          über den öffentlichen Entrance von Beacon; alles andere bleibt hinter der Anmeldung.</>} />

        <div className="feld">
          <label htmlFor="mk-weg">Versandweg</label>
          <select id="mk-weg" value={weg} onChange={(x) => setWeg(x.target.value as "smtp" | "brevo")}>
            <option value="smtp">Über das SMTP-Konto oben</option>
            <option value="brevo">Über Brevo (API)</option>
          </select>
          <p className="feld-hinweis">
            Ein Dienst wie Brevo trägt die Zustellbarkeit bei größeren Mengen. Für ein paar
            hundert Empfänger im Monat reicht das eigene Konto.
          </p>
        </div>

        {weg === "brevo" && (
          <div className="feld">
            <label htmlFor="mk-brevo">
              Brevo-API-Schlüssel {e?.brevo_api_key_set && <span className="optional">hinterlegt</span>}
            </label>
            <input
              id="mk-brevo"
              type="password"
              autoComplete="off"
              value={brevo}
              onChange={(x) => setBrevo(x.target.value)}
              placeholder={e?.brevo_api_key_set ? "leer lassen, um ihn zu behalten" : "xkeysib-…"}
            />
          </div>
        )}

        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "0 var(--am-raum-4)" }}>
          <div className="feld">
            <label htmlFor="mk-absender">Absenderadresse <span className="optional">optional</span></label>
            <input id="mk-absender" type="email" value={absender} onChange={(x) => setAbsender(x.target.value)} placeholder="wie beim Versand oben" />
          </div>
          <div className="feld">
            <label htmlFor="mk-absender-name">Absendername</label>
            <input id="mk-absender-name" value={absenderName} onChange={(x) => setAbsenderName(x.target.value)} />
          </div>
        </div>

        <div className="feld">
          <label htmlFor="mk-basis">Adresse der öffentlichen Links <span className="optional">optional</span></label>
          <input id="mk-basis" value={basis} onChange={(x) => setBasis(x.target.value)} placeholder={e?.links_basis_wirksam ?? "https://…"} />
          <p className="feld-hinweis">
            {e?.links_basis_wirksam
              ? <>Zurzeit gilt <code>{e.links_basis_wirksam}</code>{basis ? " (eigener Wert)" : " — von der Box abgeleitet"}.</>
              : "Die Box hat ihre Domain nicht mitgeteilt. Hier die Adresse des öffentlichen Entrance eintragen."}
          </p>
        </div>

        <div className="feld">
          <label htmlFor="mk-doi-betreff">Bestätigungsmail: Betreff <span className="optional">optional</span></label>
          <input id="mk-doi-betreff" value={doiBetreff} onChange={(x) => setDoiBetreff(x.target.value)} placeholder="Bitte bestätigen Sie Ihre Einwilligung" />
        </div>
        <div className="feld">
          <label htmlFor="mk-doi-text">Bestätigungsmail: Text <span className="optional">optional</span></label>
          <textarea id="mk-doi-text" rows={5} value={doiText} onChange={(x) => setDoiText(x.target.value)} placeholder={"{{anrede}},\n\n… bestätigen Sie bitte mit einem Klick:\n\n{{bestaetigungslink}}"} />
          <p className="feld-hinweis">
            Platzhalter: <code>{"{{anrede}}"}</code>, <code>{"{{vorname}}"}</code>, <code>{"{{nachname}}"}</code>,{" "}
            <code>{"{{firma}}"}</code>, <code>{"{{bestaetigungslink}}"}</code>. Leer heißt: die Vorgabe.
          </p>
        </div>

        {speichern.isError && <Fehler text={(speichern.error as Error).message} />}
        <div className="btn-reihe" style={{ marginTop: "var(--am-raum-2)" }}>
          <button type="button" className="btn btn-primaer" disabled={speichern.isPending} onClick={() => speichern.mutate()}>
            {speichern.isPending ? "Speichert …" : "Speichern"}
          </button>
          {speichern.isSuccess && <span style={{ fontSize: "0.8125rem", color: "var(--am-erfolg)" }}>Gespeichert.</span>}
        </div>
      </div>
    </section>
  );
}
