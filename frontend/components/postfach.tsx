"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { datumZeit } from "@/lib/format";
import type { OrgSettings } from "@/lib/typen";
import { Fehler } from "@/components/zustaende";

type Bilanz = { gelesen: number; tickets: number; uebergangen: number; doppelt: number };

/**
 * Das Postfach, aus dem Tickets entstehen.
 *
 * aicrm sitzt hier als **zweiter** Klient auf einem Postfach, vor dem
 * schon ein Mensch sitzt — in diesem Haus Relay. Deshalb steht der Satz
 * über das Nichtanfassen so deutlich da: Wer eine Einrichtung vornimmt,
 * muss wissen, dass sein Posteingang danach genauso aussieht wie vorher.
 *
 * Der Knopf „Jetzt abholen" ist kein Komfort. Zugangsdaten, die erst
 * beim nächsten Takt stillschweigend scheitern, sind keine Einrichtung,
 * sondern eine Hoffnung.
 */
export function Postfachblock() {
  const client = useQueryClient();
  const einstellungen = useQuery({
    queryKey: ["einstellungen"],
    queryFn: () => api.get<OrgSettings>("/api/settings"),
  });

  const [host, setHost] = useState("");
  const [port, setPort] = useState("993");
  const [benutzer, setBenutzer] = useState("");
  const [passwort, setPasswort] = useState("");
  const [ordner, setOrdner] = useState("INBOX");
  const [takt, setTakt] = useState("5");
  const [aktiv, setAktiv] = useState(false);
  const [bilanz, setBilanz] = useState<Bilanz | null>(null);

  const e = einstellungen.data;
  useEffect(() => {
    if (!e) return;
    setHost(e.imap_host ?? "");
    setPort(String(e.imap_port ?? 993));
    setBenutzer(e.imap_benutzer ?? "");
    setOrdner(e.imap_ordner ?? "INBOX");
    setTakt(String(e.imap_takt_minuten ?? 5));
    setAktiv(e.imap_aktiv ?? false);
  }, [e]);

  const speichern = useMutation({
    mutationFn: () =>
      api.put<OrgSettings>("/api/settings", {
        imap_host: host || null,
        imap_port: Number(port) || 993,
        imap_benutzer: benutzer || null,
        // Leer heißt „nicht anfassen" — sonst wäre das hinterlegte
        // Passwort nach dem ersten Speichern weg.
        ...(passwort ? { imap_passwort: passwort } : {}),
        imap_ordner: ordner || "INBOX",
        imap_takt_minuten: Number(takt) || 5,
        imap_aktiv: aktiv,
      }),
    onSuccess: () => {
      setPasswort("");
      client.invalidateQueries({ queryKey: ["einstellungen"] });
    },
  });

  const abholen = useMutation({
    mutationFn: () => api.post<Bilanz>("/api/settings/postfach/abholen"),
    onSuccess: (b) => {
      setBilanz(b);
      client.invalidateQueries({ queryKey: ["einstellungen"] });
      client.invalidateQueries({ queryKey: ["segment", "tickets"] });
    },
  });

  return (
    <section className="block">
      <div className="block-kopf">
        <h2>Postfach</h2>
        {e?.imap_aktiv && <span className="pille pille-erfolg">holt ab</span>}
      </div>
      <div className="block-inhalt">
        <p style={{ fontSize: "0.875rem", color: "var(--am-text-sekundaer)", marginBottom: "var(--am-raum-4)" }}>
          aicrm holt eingehende Post ab und macht Tickets daraus. Es <strong>fasst dabei nichts
          an</strong>: keine Nachricht wird als gelesen markiert, nichts verschoben, nichts
          gelöscht. Ihr Posteingang sieht danach aus wie vorher — auch in Relay. Gemerkt wird
          nur, bis wohin gelesen wurde.
        </p>

        <div style={{ display: "grid", gridTemplateColumns: "2fr 1fr", gap: "0 var(--am-raum-4)" }}>
          <div className="feld">
            <label htmlFor="imap-host">IMAP-Server</label>
            <input id="imap-host" value={host} onChange={(x) => setHost(x.target.value)} placeholder="imap.beispiel.de" />
            <p className="feld-hinweis">Steht in Relay unter den Kontoeinstellungen.</p>
          </div>
          <div className="feld">
            <label htmlFor="imap-port">Port</label>
            <input id="imap-port" type="number" value={port} onChange={(x) => setPort(x.target.value)} />
          </div>
        </div>

        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "0 var(--am-raum-4)" }}>
          <div className="feld">
            <label htmlFor="imap-benutzer">Benutzer</label>
            <input id="imap-benutzer" value={benutzer} onChange={(x) => setBenutzer(x.target.value)} placeholder="support@aimighty.de" />
          </div>
          <div className="feld">
            <label htmlFor="imap-passwort">
              Passwort {e?.imap_passwort_set && <span className="optional">hinterlegt</span>}
            </label>
            <input
              id="imap-passwort"
              type="password"
              value={passwort}
              autoComplete="new-password"
              onChange={(x) => setPasswort(x.target.value)}
              placeholder={e?.imap_passwort_set ? "leer lassen, um es zu behalten" : ""}
            />
          </div>
        </div>

        <div style={{ display: "grid", gridTemplateColumns: "2fr 1fr", gap: "0 var(--am-raum-4)" }}>
          <div className="feld">
            <label htmlFor="imap-ordner">Ordner</label>
            <input id="imap-ordner" value={ordner} onChange={(x) => setOrdner(x.target.value)} />
          </div>
          <div className="feld">
            <label htmlFor="imap-takt">Alle … Minuten</label>
            <input id="imap-takt" type="number" min={1} max={1440} value={takt} onChange={(x) => setTakt(x.target.value)} />
          </div>
        </div>

        <label className="quelle-freigabe">
          <input type="checkbox" checked={aktiv} onChange={(x) => setAktiv(x.target.checked)} />
          <span>
            Regelmäßig abholen.
            {" "}
            <span style={{ color: "var(--am-text-gedaempft)" }}>
              Abgeschaltet passiert nur etwas, wenn Sie unten auf Abholen drücken.
            </span>
          </span>
        </label>

        {e?.imap_letzter_fehler && (
          <div style={{ marginTop: "var(--am-raum-3)" }}>
            <Fehler text={`Letzter Versuch: ${e.imap_letzter_fehler}`} />
          </div>
        )}
        {speichern.isError && <Fehler text={(speichern.error as Error).message} />}
        {abholen.isError && <Fehler text={(abholen.error as Error).message} />}

        {bilanz && !abholen.isError && (
          <p className="erfassung-hinweis">
            {bilanz.gelesen === 0
              ? "Nichts Neues im Postfach."
              : `${bilanz.gelesen} gelesen · ${bilanz.tickets} Tickets · ` +
                `${bilanz.uebergangen} übergangen (Automaten) · ${bilanz.doppelt} schon bekannt`}
          </p>
        )}

        <div className="btn-reihe" style={{ marginTop: "var(--am-raum-4)" }}>
          <button type="button" className="btn btn-primaer" disabled={speichern.isPending} onClick={() => speichern.mutate()}>
            {speichern.isPending ? "Speichert …" : "Speichern"}
          </button>
          <button
            type="button"
            className="btn btn-sekundaer"
            disabled={abholen.isPending || !host || !benutzer}
            onClick={() => abholen.mutate()}
          >
            {abholen.isPending ? "Holt ab …" : "Jetzt abholen"}
          </button>
          {e?.imap_zuletzt && (
            <span style={{ fontSize: "0.75rem", color: "var(--am-text-gedaempft)", alignSelf: "center" }}>
              zuletzt {datumZeit(e.imap_zuletzt)}
            </span>
          )}
        </div>
      </div>
    </section>
  );
}
