"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Copy, KeyRound, Pencil, UserMinus } from "lucide-react";
import { useRef, useState } from "react";
import { api } from "@/lib/api";
import { lage, passwortAendern } from "@/lib/anmeldung";
import { datumZeit } from "@/lib/format";
import type { Mitglied, Wer } from "@/lib/typen";
import { Fehler, Laedt } from "@/components/zustaende";
import { Erklaerung } from "@/components/erklaerung";

export function Mitgliederblock() {
  const client = useQueryClient();
  const [name, setName] = useState("");
  // Welche Zeile gerade umbenannt wird, und der Entwurf des Namens.
  const [bearbeitet, setBearbeitet] = useState<string | null>(null);
  const [entwurf, setEntwurf] = useState("");

  const mitglieder = useQuery({
    queryKey: ["mitglieder"],
    queryFn: () => api.get<Mitglied[]>("/api/mitglieder"),
  });

  const wer = useQuery({
    queryKey: ["wer"],
    queryFn: () => api.get<Wer>("/api/mitglieder/wer"),
  });

  const anlegen = useMutation({
    mutationFn: () => api.post<Mitglied>("/api/mitglieder", { display_name: name }),
    onSuccess: () => {
      setName("");
      client.invalidateQueries({ queryKey: ["mitglieder"] });
    },
  });

  const umbenennen = useMutation({
    mutationFn: ({ id, display_name }: { id: string; display_name: string }) =>
      api.patch<Mitglied>(`/api/mitglieder/${id}`, { display_name }),
    onSuccess: () => {
      setBearbeitet(null);
      client.invalidateQueries({ queryKey: ["mitglieder"] });
      client.invalidateQueries({ queryKey: ["wer"] });
    },
  });

  // Rollen vergibt nur die Eigentümerin. Ohne diesen Weg hieß Hilfe auf
  // einer fremden Box: „gib mir dein Passwort" — jede angelegte Person
  // war fest `member` und sah die Einstellungen nicht.
  const rolleSetzen = useMutation({
    mutationFn: ({ id, role }: { id: string; role: "admin" | "member" }) =>
      api.patch<Mitglied>(`/api/mitglieder/${id}/rolle`, { role }),
    onSuccess: () => client.invalidateQueries({ queryKey: ["mitglieder"] }),
  });

  const entfernen = useMutation({
    mutationFn: (id: string) => api.del(`/api/mitglieder/${id}`),
    onSuccess: () => client.invalidateQueries({ queryKey: ["mitglieder"] }),
  });

  // Der Link kommt zurück und wird **einmal** angezeigt. Er landet
  // absichtlich in keiner Liste und in keiner Mail: Wer ihn hat, setzt das
  // Passwort, und ein Zugang, der am Mailversand hängt, wäre genau dann
  // nicht da, wenn eine frische Box noch kein SMTP kennt.
  const [kopiert, setKopiert] = useState(false);
  const feld = useRef<HTMLInputElement>(null);
  const [link, setLink] = useState<
    { fuer: string; kennung: string; adresse: string; tage: number; uebernahme: boolean } | null
  >(null);
  const einladen = useMutation({
    mutationFn: async (id: string) => {
      const a = await api.post<{ pfad: string; name: string; gilt_tage: number }>(
        `/api/mitglieder/${id}/einladung`,
      );
      const person = mitglieder.data?.find((m) => m.id === id);
      return { ...a, kennung: person?.olares_username ?? "", uebernahme: person?.passwort_gesetzt ?? false };
    },
    onSuccess: (a) => {
      setKopiert(false);
      setLink({
        fuer: a.name,
        kennung: a.kennung,
        adresse: `${window.location.origin}${a.pfad}`,
        tage: a.gilt_tage,
        uebernahme: a.uebernahme,
      });
    },
  });

  // Nur die Eigentümerin. Ein Verwalter darf schon alles, was die
  // Einstellungen schützen; dürfte er auch Rollen setzen, könnte er die
  // Eigentümerin herabstufen und sich die Organisation aneignen.
  const darfRollen = wer.data?.rolle === "owner";

  if (mitglieder.isPending) return <Laedt />;

  return (
    <section className="block">
      <div className="block-kopf">
        <h2>Wer hier arbeitet</h2>
        {wer.data && (
          <span style={{ fontSize: "0.75rem", color: "var(--am-text-gedaempft)" }}>
            Zugang: {wer.data.login_username}
          </span>
        )}
      </div>
      <div className="block-inhalt">
        <Erklaerung kurz="Wer mit Ihnen in Beacon arbeitet. Alle sehen und ändern alles." lang={<>Olares installiert Apps pro Nutzer und lässt an einem Zugang keinen zweiten
          Menschen zusätzlich herein. Wer zu zweit dasselbe CRM benutzt, teilt deshalb einen
          Olares-Zugang — und Beacon unterscheidet die Personen selbst.</>} />
        <div className="hinweis" data-art="achtung" style={{ marginBottom: "var(--am-raum-4)" }}>
          <span>
            Der Sitzplatz ist <strong>Zuschreibung, keine Anmeldung.</strong> Wer den
            geteilten Zugang hat, kann jeden Platz wählen. Er entscheidet, wem Besitz,
            Zuordnung und Protokolleinträge zugeschrieben werden — nicht, wer hereinkommt.
            Das Protokoll hält beides fest: die Person und den Zugang.
          </span>
        </div>

        <table className="tabelle mitgliedertabelle" style={{ marginBottom: "var(--am-raum-4)" }}>
          <thead>
            <tr>
              <th>Person</th>
              <th>Art</th>
              <th>Zuletzt</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {mitglieder.data!.map((m) => (
              <tr key={m.id} style={{ cursor: "default" }}>
                <td className="haupt">
                  {bearbeitet === m.id ? (
                    <form
                      style={{ display: "flex", gap: "var(--am-raum-2)", alignItems: "center" }}
                      onSubmit={(e) => {
                        e.preventDefault();
                        if (entwurf.trim().length >= 2) umbenennen.mutate({ id: m.id, display_name: entwurf });
                      }}
                    >
                      <input
                        aria-label="Name der Person"
                        value={entwurf}
                        onChange={(e) => setEntwurf(e.target.value)}
                        autoFocus
                        style={{ minWidth: 0 }}
                      />
                      <button type="submit" className="btn btn-primaer btn-klein" disabled={entwurf.trim().length < 2 || umbenennen.isPending}>
                        Speichern
                      </button>
                      <button type="button" className="btn btn-still btn-klein" onClick={() => setBearbeitet(null)}>
                        Abbrechen
                      </button>
                    </form>
                  ) : (
                    <span className="mitglied-name">
                      <span className="mitglied-name-zeile">
                        {m.display_name ?? m.olares_username}
                      <button
                        type="button"
                        className="btn btn-still btn-klein"
                        aria-label={`${m.display_name ?? m.olares_username} umbenennen`}
                        title="Namen ändern"
                        onClick={() => {
                          setBearbeitet(m.id);
                          setEntwurf(m.display_name ?? "");
                        }}
                      >
                        <Pencil size={14} aria-hidden="true" />
                      </button>
                      </span>
                      {/* Die Kennung ist der Name, mit dem sich diese Person
                          anmeldet — sie gehört unter den Anzeigenamen, nicht
                          in eine eigene Spalte. */}
                      <span className="mitglied-kennung">{m.olares_username}</span>
                    </span>
                  )}
                </td>
                <td>
                  {/* Zwei Aussagen übereinander statt in zwei Spalten: Die
                      Tabelle hat 638 px Rahmen, und eine fünfte Spalte
                      schöbe die Knöpfe der ersten Zeile aus dem Bild
                      (gemessen, siehe 0.5.0). */}
                  <span className="mitglied-art">
                    <span className="stufe" data-art={m.zugang === "olares" ? "won" : undefined}>
                      {m.zugang === "olares" ? "eigener Zugang" : "Sitzplatz"}
                    </span>
                    {darfRollen && m.role !== "owner" ? (
                      <select
                        className="mitglied-rolle"
                        aria-label={`Rolle von ${m.display_name ?? m.olares_username}`}
                        value={m.role === "admin" ? "admin" : "member"}
                        disabled={rolleSetzen.isPending}
                        onChange={(e) =>
                          rolleSetzen.mutate({
                            id: m.id,
                            role: e.target.value as "admin" | "member",
                          })
                        }
                      >
                        <option value="member">Mitglied</option>
                        <option value="admin">Verwalter</option>
                      </select>
                    ) : (
                      <span className="mitglied-rolle-fest">{ROLLENTEXT[m.role] ?? m.role}</span>
                    )}
                  </span>
                </td>
                <td>{m.last_seen_at ? datumZeit(m.last_seen_at) : "—"}</td>
                <td style={{ textAlign: "right", whiteSpace: "nowrap" }}>
                  {/* Beide Handlungen als Zeichen.
                      Gemessen auf der Box: Mit dem Wort „Entfernen" war die
                      Tabelle 744 px breit, ihr Rahmen 638 — der Schlüssel der
                      ersten Zeile stand bei 697 und war damit unsichtbar,
                      ausgerechnet für die Person, die ihn zuerst braucht. */}
                  <button
                    type="button"
                    className="btn btn-still btn-klein"
                    title="Einladungslink erzeugen — damit setzt diese Person ihr Passwort"
                    aria-label={`Einladungslink für ${m.display_name ?? m.olares_username} erzeugen`}
                    onClick={() => einladen.mutate(m.id)}
                    disabled={einladen.isPending}
                  >
                    <KeyRound size={14} aria-hidden="true" />
                  </button>
                  {m.zugang === "sitzplatz" && m.id !== wer.data?.user_id && (
                    <button
                      type="button"
                      className="btn btn-still btn-klein"
                      title="Aus der Organisation entfernen"
                      aria-label={`${m.display_name ?? m.olares_username} aus der Organisation entfernen`}
                      onClick={() => entfernen.mutate(m.id)}
                    >
                      <UserMinus size={14} aria-hidden="true" />
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>

        {link && (
          <div className="einladung-ausgabe">
            <p className="einladung-fuer">
              Einladung für <span className="mono">{link.kennung}</span>
              {link.fuer && link.fuer !== link.kennung ? <> ({link.fuer})</> : null}
            </p>
            {/* Wer schon ein Passwort hat, bekommt keinen Zugang, sondern
                einen neuen — der alte gilt danach nicht mehr. Das ist der
                Rettungsweg des Eigentümers, und es ist ein Eingriff. */}
            {link.uebernahme && (
              <p className="feld-hinweis" style={{ margin: "0 0 var(--am-raum-2)" }}>
                <strong>Achtung:</strong> Diese Person hat bereits ein Passwort. Wer den Link
                einlöst, <strong>ersetzt</strong> es — der bisherige Zugang gilt dann nicht mehr.
              </p>
            )}
            <div className="einladungslink">
              <input
                ref={feld}
                className="input"
                readOnly
                value={link.adresse}
                onFocus={(e) => e.target.select()}
                aria-label={`Einladungslink für ${link.fuer}`}
              />
              <button
                type="button"
                className="btn btn-sekundaer btn-klein einladung-kopieren"
                onClick={async () => {
                  // „Kopiert" erst sagen, wenn es wirklich geklappt hat. Die
                  // Zwischenablage darf verweigern (fehlender Fokus, fehlende
                  // Berechtigung); dann bleibt der Text markiert und Strg-C hilft.
                  try {
                    await navigator.clipboard.writeText(link.adresse);
                    setKopiert(true);
                  } catch {
                    setKopiert(false);
                    feld.current?.select();
                  }
                }}
              >
                <Copy size={14} aria-hidden="true" /> {kopiert ? "Kopiert" : "Kopieren"}
              </button>
            </div>
            {/* Der Klartext des Tokens existiert genau einmal, hier. Gespeichert
                wird nur sein SHA-256 — sonst könnte sich jeder mit Zugriff auf
                die Datenbank damit anmelden. Wer die Seite neu lädt, bekommt
                ihn deshalb nicht zurück, sondern muss einen neuen erzeugen. */}
            <p className="feld-hinweis" style={{ margin: "var(--am-raum-2) 0 0" }}>
              <strong>Jetzt kopieren.</strong> Dieser Link steht nur hier und ist nach
              einem Neuladen der Seite verloren — gespeichert wird nur seine Prüfsumme.
              Er gilt {link.tage} Tage und <strong>genau einmal</strong>; ein neuer Link
              entwertet diesen.
            </p>
          </div>
        )}

        {entfernen.isError && <Fehler text={(entfernen.error as Error).message} />}
        {einladen.isError && <Fehler text={(einladen.error as Error).message} />}
        {umbenennen.isError && <Fehler text={(umbenennen.error as Error).message} />}

        <form
          style={{ display: "flex", gap: "var(--am-raum-2)", alignItems: "flex-end" }}
          onSubmit={(e) => {
            e.preventDefault();
            if (name.trim().length >= 2) anlegen.mutate();
          }}
        >
          <div className="feld" style={{ flex: 1, marginBottom: 0 }}>
            <label htmlFor="mitgliedname">Person hinzufügen</label>
            <input
              id="mitgliedname"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="Marc Bayer"
            />
            <p className="feld-hinweis">
              Bekommt sie später einen eigenen Olares-Zugang mit derselben Kennung, wird aus
              dem Sitzplatz automatisch eine angemeldete Person — Besitz und Protokoll bleiben,
              wie sie sind.
            </p>
          </div>
          <button
            type="submit"
            className="btn btn-primaer"
            disabled={name.trim().length < 2 || anlegen.isPending}
          >
            {anlegen.isPending ? "Legt an …" : "Hinzufügen"}
          </button>
        </form>
        {anlegen.isError && <Fehler text={(anlegen.error as Error).message} />}

        <p style={{ fontSize: "0.75rem", color: "var(--am-text-gedaempft)", marginTop: "var(--am-raum-3)" }}>
          Beide sehen und ändern alles. Besitz ist Arbeitsteilung, keine Schranke. Der Name
          lässt sich für jede Person ändern, auch für den Olares-Zugang selbst — die Kennung
          bleibt.
        </p>
      </div>
    </section>
  );
}

/**
 * Das eigene Passwort ändern.
 *
 * Steht nur da, wenn es ein Passwort gibt — im Modus `olares` prüft der
 * Sidecar, und Beacon hätte nichts zu ändern. Das alte wird verlangt:
 * Sonst genügte ein fremder, offener Browser, um jemanden auszusperren.
 */
export function Passwortblock() {
  const [alt, setAlt] = useState("");
  const [neu, setNeu] = useState("");
  const [wieder, setWieder] = useState("");
  const [meldung, setMeldung] = useState<string | null>(null);

  const stand = useQuery({ queryKey: ["anmeldelage"], queryFn: lage, staleTime: 60_000 });

  const aendern = useMutation({
    mutationFn: () => passwortAendern(alt, neu),
    onSuccess: () => {
      setAlt("");
      setNeu("");
      setWieder("");
      setMeldung("Geändert. Andere Geräte wurden abgemeldet.");
    },
  });

  if (!stand.data?.angemeldet) return null;

  const bereit = alt.length > 0 && neu.length >= 12 && neu === wieder;

  return (
    <section className="block">
      <div className="block-kopf">
        <h2>Ihr Passwort</h2>
      </div>
      <div className="block-inhalt">
        <form
          onSubmit={(e) => {
            e.preventDefault();
            setMeldung(null);
            if (bereit) aendern.mutate();
          }}
        >
          <div className="feld">
            <label htmlFor="pw-alt">Bisheriges Passwort</label>
            <input id="pw-alt" className="input" type="password" autoComplete="current-password" value={alt} onChange={(e) => setAlt(e.target.value)} />
          </div>
          <div className="feld">
            <label htmlFor="pw-neu">Neues Passwort</label>
            <input id="pw-neu" className="input" type="password" autoComplete="new-password" value={neu} onChange={(e) => setNeu(e.target.value)} />
            <p className="feld-hinweis">
              Mindestens zwölf Zeichen. Eine lange Wortfolge trägt weiter als kurze
              Sonderzeichen — und ein Wechsel meldet alle anderen Geräte ab.
            </p>
          </div>
          <div className="feld">
            <label htmlFor="pw-wieder">Noch einmal</label>
            <input id="pw-wieder" className="input" type="password" autoComplete="new-password" value={wieder} onChange={(e) => setWieder(e.target.value)} />
          </div>
          <button type="submit" className="btn btn-primaer" disabled={!bereit || aendern.isPending}>
            {aendern.isPending ? "Ändert …" : "Passwort ändern"}
          </button>
        </form>
        {aendern.isError && <Fehler text={(aendern.error as Error).message} />}
        {meldung && <p className="feld-hinweis">{meldung}</p>}
      </div>
    </section>
  );
}

/** Was eine Rolle im Satz heißt. „viewer" steht im Datenbank-Typ, bewirkt
 *  aber nichts — es wird deshalb nirgends angeboten, nur benannt, falls
 *  es aus einer alten Zeile kommt. */
const ROLLENTEXT: Record<string, string> = {
  owner: "Eigentümerin",
  admin: "Verwalter",
  member: "Mitglied",
  viewer: "Mitglied",
};
