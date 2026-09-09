"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { Absenderkonto } from "@/lib/typen";
import { Erklaerung } from "@/components/erklaerung";
import { Schalter } from "@/components/schalter";
import { Fehler, Laedt } from "@/components/zustaende";

/**
 * Womit ich schicke.
 *
 * Bis 0.6.x hatte eine Organisation genau einen Absender. Sobald zwei
 * Menschen in einem Bestand arbeiten, ist das falsch: Marcs Angebot ging
 * als Kai hinaus, und der Empfänger sah einen Namen, mit dem er nie
 * gesprochen hatte.
 *
 * Zwei Wege, und welcher trägt, entscheidet der Mailanbieter, nicht wir.
 * Deshalb stehen beide hier — der einfache offen, der aufwendige
 * eingeklappt.
 */
export function Absenderkontoblock() {
  const client = useQueryClient();
  const [email, setEmail] = useState("");
  const [name, setName] = useState("");
  const [eigenes, setEigenes] = useState(false);
  const [host, setHost] = useState("");
  const [port, setPort] = useState("587");
  const [benutzer, setBenutzer] = useState("");
  const [passwort, setPasswort] = useState("");
  const [sicherheit, setSicherheit] = useState("starttls");
  const [meldung, setMeldung] = useState<string | null>(null);

  const konto = useQuery({
    queryKey: ["absenderkonto"],
    queryFn: () => api.get<Absenderkonto>("/api/mitglieder/wer/absender"),
  });

  useEffect(() => {
    const a = konto.data;
    if (!a) return;
    setEmail(a.absender_email ?? "");
    setName(a.absender_name ?? "");
    setHost(a.smtp_host ?? "");
    setPort(String(a.smtp_port ?? 587));
    setBenutzer(a.smtp_benutzer ?? "");
    setSicherheit(a.smtp_sicherheit ?? "starttls");
    setEigenes(Boolean(a.smtp_host));
  }, [konto.data]);

  const speichern = useMutation({
    mutationFn: () =>
      api.put<Absenderkonto>("/api/mitglieder/wer/absender", {
        absender_email: email.trim(),
        absender_name: name.trim(),
        smtp_host: eigenes ? host.trim() : "",
        smtp_port: eigenes ? Number(port) || 587 : null,
        smtp_benutzer: eigenes ? benutzer.trim() : "",
        smtp_sicherheit: eigenes ? sicherheit : null,
        // Leer heißt „nicht anfassen“ — sonst löschte jedes Speichern das
        // Passwort, das man beim Lesen nie zurückbekommt.
        ...(passwort ? { smtp_passwort: passwort } : {}),
        ...(eigenes ? {} : { smtp_passwort: "" }),
      }),
    onSuccess: () => {
      setPasswort("");
      setMeldung("Gespeichert.");
      client.invalidateQueries({ queryKey: ["absenderkonto"] });
    },
  });

  if (konto.isPending) return <Laedt />;
  if (konto.isError) return <Fehler text={(konto.error as Error).message} />;

  const haus = konto.data!.haus_absender;
  const hausdomain = haus?.split("@").pop() ?? "";
  const wirkt = email.trim() || haus || "—";

  return (
    <section className="block">
      <div className="block-kopf">
        <h2>Ihre Absenderadresse</h2>
        <span style={{ fontSize: "0.75rem", color: "var(--am-text-gedaempft)" }}>
          schickt als {wirkt}
        </span>
      </div>
      <div className="block-inhalt">
        <Erklaerung
          kurz="Unter welcher Adresse Ihre Mails hinausgehen."
          lang={
            <>
              Ohne Eintrag schickt Beacon unter dem Absender der Organisation. Wer hier
              eine eigene Adresse einträgt, erscheint beim Empfänger unter seinem Namen —
              angemeldet wird trotzdem mit dem Konto der Organisation. Ob Ihr Anbieter das
              durchlässt, entscheidet er selbst: Manche weisen eine Absenderadresse
              zurück, die nicht dem angemeldeten Postfach entspricht. Dann brauchen Sie
              eigene Zugangsdaten.
            </>
          }
        />

        <form
          onSubmit={(e) => {
            e.preventDefault();
            setMeldung(null);
            speichern.mutate();
          }}
        >
          <div className="feld">
            <label htmlFor="abs-email">E-Mail-Adresse</label>
            <input
              id="abs-email"
              className="input"
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder={haus ?? "vorname.nachname@ihre-domain.de"}
            />
            <p className="feld-hinweis">
              {eigenes
                ? "Mit eigenen Zugangsdaten ist jede Adresse möglich, die Ihr Anbieter führt."
                : hausdomain
                  ? `Auf dem gemeinsamen Konto nur eine Adresse bei ${hausdomain}. Leer lassen heißt: wie die Organisation.`
                  : "Leer lassen heißt: wie die Organisation."}
            </p>
          </div>

          <div className="feld">
            <label htmlFor="abs-name">Angezeigter Name</label>
            <input
              id="abs-name"
              className="input"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="Marc Bayer"
            />
          </div>

          {/* Nur behaupten, was auch stimmt: `Reply-To` setzt der Versand
              ausschließlich, wenn ein Postfach eingerichtet ist. Ohne eines
              landet die Antwort tatsächlich im privaten Postfach. */}
          <div className="hinweis" data-art={konto.data!.postfach_aktiv ? undefined : "achtung"} style={{ marginBottom: "var(--am-raum-4)" }}>
            <span>
              {konto.data!.postfach_aktiv ? (
                <>
                  Antworten laufen weiter in das Postfach der Organisation, das Beacon
                  einliest. Sonst läge die Antwort in Ihrem privaten Postfach und im
                  Bestand stünde nichts.
                </>
              ) : (
                <>
                  Beacon liest noch kein Postfach ein. Antworten auf Ihre Mails kommen
                  deshalb in <strong>Ihrem eigenen</strong> Postfach an und tauchen im
                  Bestand nicht auf. Das Postfach richtet der Eigentümer weiter oben
                  unter „Posteingang“ ein.
                </>
              )}
            </span>
          </div>

          <Schalter
            an={eigenes}
            umschalten={setEigenes}
            text="Eigenes Postfach benutzen"
            hinweis="Nötig, wenn Ihr Anbieter eine fremde Absenderadresse ablehnt, oder wenn Ihre Adresse zu einer anderen Domain gehört. Sie melden sich dann selbst an."
          />

          {eigenes && (
            <div style={{ marginTop: "var(--am-raum-4)" }}>
              <div className="feld">
                <label htmlFor="abs-host">Server</label>
                <input id="abs-host" className="input" value={host} onChange={(e) => setHost(e.target.value)} placeholder="send.one.com" />
              </div>
              <div className="feld">
                <label htmlFor="abs-port">Port</label>
                <input id="abs-port" className="input" inputMode="numeric" value={port} onChange={(e) => setPort(e.target.value)} />
              </div>
              <div className="feld">
                <label htmlFor="abs-benutzer">Benutzer</label>
                <input id="abs-benutzer" className="input" value={benutzer} onChange={(e) => setBenutzer(e.target.value)} autoComplete="off" />
              </div>
              <div className="feld">
                <label htmlFor="abs-passwort">Passwort</label>
                <input
                  id="abs-passwort"
                  className="input"
                  type="password"
                  value={passwort}
                  onChange={(e) => setPasswort(e.target.value)}
                  placeholder={konto.data!.smtp_passwort_set ? "gespeichert — leer lassen, um es zu behalten" : ""}
                  autoComplete="new-password"
                />
              </div>
              <div className="feld">
                <label htmlFor="abs-sicherheit">Verschlüsselung</label>
                <select id="abs-sicherheit" className="input" value={sicherheit} onChange={(e) => setSicherheit(e.target.value)}>
                  <option value="starttls">STARTTLS (Port 587)</option>
                  <option value="ssl">SSL (Port 465)</option>
                  <option value="keine">keine</option>
                </select>
              </div>
            </div>
          )}

          <button type="submit" className="btn btn-primaer" disabled={speichern.isPending}>
            {speichern.isPending ? "Speichert …" : "Speichern"}
          </button>
        </form>

        {speichern.isError && <Fehler text={(speichern.error as Error).message} />}
        {meldung && <p className="feld-hinweis">{meldung}</p>}
      </div>
    </section>
  );
}
