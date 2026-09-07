"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Download, Headphones, Trash2 } from "lucide-react";
import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";
import { datumZeit } from "@/lib/format";
import { dauerText, fortschrittText, istDeutsch, modellName } from "@/lib/podcast";
import type { OrgSettings, Podcast, PodcastStatus, Sprecher, Stimmenstand } from "@/lib/typen";
import { Erklaerung } from "@/components/erklaerung";
import { Fehler } from "@/components/zustaende";

/**
 * Gespräch vorbereiten — der Bestand als kurzer Podcast.
 *
 * Drei Bauteile: der Block auf der Firmen- und Lead-Seite, der „Heute
 * vorbereitet"-Kasten auf der Startseite und die Einrichtung der
 * Sprachausgabe unter Einstellungen. Alles auf der Box: Skript vom
 * Sprachmodell, Stimme von Speaches, Datei unter /app/data.
 */

function usePodcastStatus() {
  return useQuery({
    queryKey: ["podcast-status"],
    queryFn: () => api.get<PodcastStatus>("/api/podcasts/status"),
    staleTime: 5 * 60_000,
  });
}

function Skript({ p }: { p: Podcast }) {
  const [offen, setOffen] = useState(false);
  if (!p.segmente.length) return null;
  return (
    <div className="podcast-skript">
      <button type="button" className="btn btn-still btn-klein" aria-expanded={offen} onClick={() => setOffen((o) => !o)}>
        {offen ? "Skript schließen" : "Skript lesen"}
      </button>
      {offen && (
        <dl className="podcast-skript-text">
          {p.segmente.map((s, i) => (
            <div key={i} className="podcast-absatz" data-sprecher={s.sprecher}>
              <dt>{s.sprecher === "moderatorin" ? "Moderatorin" : "Kollege"}</dt>
              <dd>{s.text}</dd>
            </div>
          ))}
        </dl>
      )}
    </div>
  );
}

/** Eine fertige Folge: Titel, Player, Skript, Herunterladen, Löschen. */
function Folge({ p, beiLoeschen, kompakt = false }: { p: Podcast; beiLoeschen?: () => void; kompakt?: boolean }) {
  const audio = `/api/podcasts/${p.id}/audio`;
  return (
    <div className="podcast-folge">
      <div className="podcast-folge-kopf">
        <Headphones size={16} aria-hidden="true" />
        <div style={{ minWidth: 0, flex: 1 }}>
          <div className="podcast-titel">{p.titel ?? "Gespräch vorbereiten"}</div>
          <div className="podcast-meta">
            {datumZeit(p.created_at)}
            {p.dauer_s ? ` · ${dauerText(p.dauer_s)}` : ""}
            {p.anlass && !kompakt ? ` · ${p.anlass}` : ""}
          </div>
        </div>
      </div>
      <audio controls preload="none" src={audio} className="podcast-player">
        <track kind="captions" />
      </audio>
      {!kompakt && (
        <div className="btn-reihe podcast-aktionen">
          <a className="btn btn-still btn-klein" href={audio} download>
            <Download size={14} aria-hidden="true" /> Herunterladen
          </a>
          <Skript p={p} />
          {beiLoeschen && (
            <button type="button" className="btn btn-still btn-klein" onClick={beiLoeschen} style={{ marginLeft: "auto" }}>
              <Trash2 size={14} aria-hidden="true" /> Löschen
            </button>
          )}
        </div>
      )}
    </div>
  );
}

/** Der Block auf der Firmen- und Lead-Seite. */
export function Podcastblock({ entity, entityId }: { entity: "companies" | "deals"; entityId: string }) {
  const client = useQueryClient();
  const status = usePodcastStatus();
  const schluessel = ["podcasts", entity, entityId];
  const liste = useQuery({
    queryKey: schluessel,
    queryFn: () => api.get<Podcast[]>(`/api/podcasts?entity=${entity}&entity_id=${entityId}`),
    refetchInterval: (q) => (q.state.data?.some((p) => p.status === "laeuft") ? 2500 : false),
  });

  const erzeugen = useMutation({
    mutationFn: () => api.post<Podcast>("/api/podcasts", { entity, entity_id: entityId }),
    onSuccess: () => client.invalidateQueries({ queryKey: schluessel }),
  });
  const loeschen = useMutation({
    mutationFn: (id: string) => api.del(`/api/podcasts/${id}`),
    onSuccess: () => {
      client.invalidateQueries({ queryKey: schluessel });
      client.invalidateQueries({ queryKey: ["podcasts-heute"] });
    },
  });

  const folgen = liste.data ?? [];
  const laufend = folgen.find((p) => p.status === "laeuft");
  const fertige = folgen.filter((p) => p.status === "fertig");
  const letzter = folgen[0];
  const bereit = Boolean(status.data?.llm_ready && status.data?.tts_ready);

  return (
    <section className="block">
      <div className="block-kopf">
        <h2>Gespräch vorbereiten</h2>
        <button
          type="button"
          className="btn btn-sekundaer btn-klein"
          disabled={!bereit || Boolean(laufend) || erzeugen.isPending}
          onClick={() => erzeugen.mutate()}
          title={bereit ? undefined : status.data?.hint}
        >
          <Headphones size={14} aria-hidden="true" />
          {laufend ? "Entsteht …" : "Podcast erzeugen"}
        </button>
      </div>
      <div className="block-inhalt">
        {status.data && !bereit && (
          <p className="erfassung-hinweis" style={{ marginBottom: "var(--am-raum-3)" }}>
            {status.data.hint} <Link href="/einstellungen?bereich=ki">Einstellungen öffnen.</Link>
          </p>
        )}
        {!laufend && !folgen.length && bereit && (
          <p style={{ fontSize: "0.875rem", color: "var(--am-text-gedaempft)" }}>
            Ein kurzes Gespräch zweier Stimmen über alles, was hier steht — zum Anhören vor dem Termin.
          </p>
        )}
        {laufend && (
          <p className="erfassung-hinweis podcast-stand" aria-live="polite" style={{ marginBottom: "var(--am-raum-3)" }}>
            {fortschrittText(laufend.fortschritt)}
          </p>
        )}
        {erzeugen.isError && <Fehler text={(erzeugen.error as Error).message} />}
        {letzter?.status === "fehler" && <Fehler text={`Die letzte Folge ist gescheitert: ${letzter.fehler ?? "unbekannt"}`} />}
        {fertige.map((p, i) => (
          <Folge key={p.id} p={p} kompakt={i > 0} beiLoeschen={() => loeschen.mutate(p.id)} />
        ))}
      </div>
    </section>
  );
}

/** Auf der Startseite: Folgen zu den Terminen der nächsten 24 Stunden. */
export function HeuteVorbereitet() {
  const heute = useQuery({
    queryKey: ["podcasts-heute"],
    queryFn: () => api.get<Podcast[]>("/api/podcasts/heute"),
    staleTime: 60_000,
  });
  if (!heute.data?.length) return null;
  return (
    <section className="block">
      <div className="block-kopf">
        <h2>Heute vorbereitet</h2>
        <span className="stufe">{heute.data.length === 1 ? "eine Folge" : `${heute.data.length} Folgen`}</span>
      </div>
      <div className="block-inhalt">
        {heute.data.map((p) => (
          <div key={p.id} className="podcast-heute">
            <div className="podcast-meta">
              <Link href={p.entity === "deals" ? `/deals/${p.entity_id}` : `/firmen/${p.entity_id}`}>{p.name ?? "—"}</Link>
              {p.termin_titel ? ` · ${p.termin_titel}` : ""}
              {p.termin_am ? ` · ${datumZeit(p.termin_am)}` : ""}
            </div>
            <Folge p={p} kompakt />
          </div>
        ))}
      </div>
    </section>
  );
}

// ── Einstellungen ────────────────────────────────────────────────────────

function Stimmwahl({
  id, label, wert, setWert, stand, hinweis,
}: {
  id: string; label: string; wert: string; setWert: (w: string) => void; stand: Stimmenstand | undefined; hinweis?: string;
}) {
  const deutsch = (l: string[]) => l.filter(istDeutsch);
  const installiert = stand ? deutsch(stand.installiert) : [];
  const verfuegbar = stand ? deutsch(stand.verfuegbar) : [];
  const bekannt = installiert.includes(wert) || verfuegbar.includes(wert) || !stand;
  return (
    <div className="feld">
      <label htmlFor={id}>{label}</label>
      <select id={id} value={wert} onChange={(ev) => setWert(ev.target.value)}>
        {!bekannt && wert && <option value={wert}>{modellName(wert)}</option>}
        {installiert.length > 0 && (
          <optgroup label="Installiert">
            {installiert.map((m) => <option key={m} value={m}>{modellName(m)}</option>)}
          </optgroup>
        )}
        {verfuegbar.length > 0 && (
          <optgroup label="Verfügbar — wird beim Einrichten geladen">
            {verfuegbar.map((m) => <option key={m} value={m}>{modellName(m)}</option>)}
          </optgroup>
        )}
      </select>
      {hinweis && <p className="feld-hinweis">{hinweis}</p>}
    </div>
  );
}

/** Sprachausgabe: Adresse, Schlüssel, zwei Stimmen, Probe, Automatik. */
export function Sprachausgabeblock({ e }: { e: OrgSettings }) {
  const client = useQueryClient();
  const [adresse, setAdresse] = useState(e.tts_endpoint_url ?? "");
  const [schluessel, setSchluessel] = useState("");
  const [modell1, setModell1] = useState(e.tts_modell);
  const [modell2, setModell2] = useState(e.tts_modell_2);
  const [automatisch, setAutomatisch] = useState(e.podcast_automatisch);
  const [probeUrl, setProbeUrl] = useState<string | null>(null);
  const probeRef = useRef<string | null>(null);

  useEffect(() => {
    setAdresse(e.tts_endpoint_url ?? "");
    setModell1(e.tts_modell);
    setModell2(e.tts_modell_2);
    setAutomatisch(e.podcast_automatisch);
  }, [e]);

  useEffect(() => () => { if (probeRef.current) URL.revokeObjectURL(probeRef.current); }, []);

  const stimmen = useQuery({
    queryKey: ["podcast-stimmen"],
    queryFn: () => api.get<Stimmenstand>("/api/podcasts/stimmen"),
    enabled: e.tts_ready,
    retry: false,
    refetchInterval: (q) => (Object.values(q.state.data?.installationen ?? {}).includes("laeuft") ? 3000 : false),
  });

  const speichern = useMutation({
    mutationFn: () =>
      api.put<OrgSettings>("/api/settings", {
        tts_endpoint_url: adresse.trim() || null,
        // Leer heißt „nicht angefasst" — wie beim Modellschlüssel.
        tts_api_key: schluessel,
        tts_modell: modell1,
        tts_modell_2: modell2,
        podcast_automatisch: automatisch,
      }),
    onSuccess: () => {
      setSchluessel("");
      client.invalidateQueries({ queryKey: ["einstellungen"] });
      client.invalidateQueries({ queryKey: ["podcast-status"] });
      client.invalidateQueries({ queryKey: ["podcast-stimmen"] });
    },
  });

  const einrichten = useMutation({
    mutationFn: (modell: string) => api.post("/api/podcasts/stimmen/einrichten", { modell }),
    onSuccess: () => client.invalidateQueries({ queryKey: ["podcast-stimmen"] }),
  });

  const probe = useMutation({
    mutationFn: async (sprecher: Sprecher) => {
      const antwort = await fetch("/api/podcasts/probe", {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ sprecher }),
      });
      if (!antwort.ok) {
        let grund = `Anfrage fehlgeschlagen (${antwort.status})`;
        try { const k = await antwort.json(); if (typeof k?.detail === "string") grund = k.detail; } catch { /* Statuscode bleibt */ }
        throw new Error(grund);
      }
      return URL.createObjectURL(await antwort.blob());
    },
    onSuccess: (url) => {
      if (probeRef.current) URL.revokeObjectURL(probeRef.current);
      probeRef.current = url;
      setProbeUrl(url);
    },
  });

  const fehlt = (m: string) => Boolean(stimmen.data && m && !stimmen.data.installiert.includes(m));
  const laedt = (m: string) => stimmen.data?.installationen[m] === "laeuft";
  const installationsFehler = Object.entries(stimmen.data?.installationen ?? {}).find(([, s]) => s.startsWith("fehler"));

  return (
    <section className="block">
      <div className="block-kopf">
        <h2>Sprachausgabe</h2>
        <span className="stufe" data-art={e.tts_ready ? "won" : undefined}>
          {e.tts_ready ? "eingerichtet" : "nicht eingerichtet"}
        </span>
      </div>
      <div className="block-inhalt">
        <Erklaerung
          kurz="Für „Gespräch vorbereiten“ als Podcast: Beacon spricht die Folgen über einen Sprachdienst auf dieser Box — meist Speaches."
          lang={<>Beacon spricht einen OpenAI-kompatiblen Sprachdienst an (<code>/v1/audio/speech</code>). Auf der Box heißt die Adresse
            meist <code>http://speaches.&lt;namespace&gt;.svc.cluster.local:8000</code>; den Namespace nennt <code>kubectl get svc -A | grep speaches</code>.
            Deutsche Stimmen sind Piper-Modelle; beim Einrichten lädt der Sprachdienst sie selbst von Hugging Face — ohne Kundendaten,
            und nur dieses eine Mal. Thorsten klingt gut, die weiblichen Stimmen sind hörbar einfacher. Die fertigen Folgen liegen
            unter <code>/app/data/podcasts</code> und verlassen die Box nicht.</>}
        />
        <form onSubmit={(ev) => { ev.preventDefault(); speichern.mutate(); }}>
          <div className="feld">
            <label htmlFor="tts-adresse">Adresse</label>
            <input id="tts-adresse" value={adresse} onChange={(ev) => setAdresse(ev.target.value)} placeholder="http://speaches.speachesv3-shared.svc.cluster.local:8000" />
            <p className="feld-hinweis">Ohne <code>/v1</code> — das hängt Beacon selbst an.</p>
          </div>
          <div className="feld">
            <label htmlFor="tts-schluessel">Zugangsschlüssel <span className="optional">optional</span></label>
            <input
              id="tts-schluessel" type="password" value={schluessel} onChange={(ev) => setSchluessel(ev.target.value)}
              placeholder={e.tts_api_key_set ? "hinterlegt — leer lassen, um ihn zu behalten" : "keiner hinterlegt"} autoComplete="off"
            />
          </div>
          {stimmen.isError && e.tts_ready && <Fehler text={(stimmen.error as Error).message} />}
          <Stimmwahl id="tts-stimme-1" label="Stimme des Kollegen" wert={modell1} setWert={setModell1} stand={stimmen.data} hinweis="Kennt den Bestand und antwortet daraus." />
          <Stimmwahl id="tts-stimme-2" label="Stimme der Moderatorin" wert={modell2} setWert={setModell2} stand={stimmen.data} hinweis="Führt durch die Folge und stellt die Fragen." />
          <div className="feld">
            <label style={{ display: "flex", alignItems: "flex-start", gap: "var(--am-raum-2)", cursor: "pointer" }}>
              <input type="checkbox" style={{ marginTop: "0.2em" }} checked={automatisch} onChange={(ev) => setAutomatisch(ev.target.checked)} />
              Gespräche mit Termin automatisch vorbereiten — 24 Stunden vorher, für Termine mit Firma oder Lead
            </label>
          </div>
          {speichern.isError && <Fehler text={(speichern.error as Error).message} />}
          <div className="btn-reihe">
            <button type="submit" className="btn btn-primaer" disabled={speichern.isPending}>
              {speichern.isPending ? "Wird gespeichert …" : "Speichern"}
            </button>
            {speichern.isSuccess && <span style={{ fontSize: "0.8125rem", color: "var(--am-erfolg)" }}>Gespeichert.</span>}
          </div>
        </form>

        {e.tts_ready && (
          <div className="podcast-einrichtung">
            {[e.tts_modell, e.tts_modell_2].filter((m, i, a) => m && a.indexOf(m) === i).map((m) => (
              fehlt(m) && (
                <p key={m} className="erfassung-hinweis" style={{ marginBottom: "var(--am-raum-2)" }}>
                  {laedt(m) ? (
                    <>{modellName(m)} wird heruntergeladen … das dauert einige Minuten.</>
                  ) : (
                    <>
                      {modellName(m)} ist noch nicht installiert.{" "}
                      <button type="button" className="btn btn-still btn-klein" onClick={() => einrichten.mutate(m)} disabled={einrichten.isPending}>
                        Stimme einrichten
                      </button>
                    </>
                  )}
                </p>
              )
            ))}
            {installationsFehler && <Fehler text={`${modellName(installationsFehler[0])}: ${installationsFehler[1]}`} />}
            {einrichten.isError && <Fehler text={(einrichten.error as Error).message} />}
            <div className="btn-reihe">
              <button type="button" className="btn btn-sekundaer btn-klein" onClick={() => probe.mutate("kollege")} disabled={probe.isPending}>
                {probe.isPending ? "Spricht …" : "Kollegen hören"}
              </button>
              <button type="button" className="btn btn-sekundaer btn-klein" onClick={() => probe.mutate("moderatorin")} disabled={probe.isPending}>
                Moderatorin hören
              </button>
            </div>
            {probe.isError && <Fehler text={(probe.error as Error).message} />}
            {probeUrl && (
              <audio controls autoPlay src={probeUrl} className="podcast-player" style={{ marginTop: "var(--am-raum-3)" }}>
                <track kind="captions" />
              </audio>
            )}
          </div>
        )}
      </div>
    </section>
  );
}
