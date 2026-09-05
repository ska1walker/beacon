"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { use, useEffect, useState } from "react";
import { api } from "@/lib/api";
import { datumZeit, KAMPAGNE_STATUS_ART, KAMPAGNE_STATUS_TEXT } from "@/lib/format";
import type { Kampagne, Kampagnenvorschau, Liste, OrgSettings, Vorlage } from "@/lib/typen";
import { Seitenkopf } from "@/components/seitenkopf";
import { Fehler, Laedt } from "@/components/zustaende";

/** Vorlagen: eine wählen, oder den aktuellen Text als neue ablegen. */
function Vorlagen({ betreff, text, beiWahl }: { betreff: string; text: string; beiWahl: (v: Vorlage) => void }) {
  const client = useQueryClient();
  const vorlagen = useQuery({ queryKey: ["vorlagen"], queryFn: () => api.get<Vorlage[]>("/api/vorlagen") });
  const [name, setName] = useState("");
  const ablegen = useMutation({
    mutationFn: () => api.post<Vorlage>("/api/vorlagen", { name, betreff, text }),
    onSuccess: () => { setName(""); client.invalidateQueries({ queryKey: ["vorlagen"] }); },
  });
  const loeschen = useMutation({
    mutationFn: (id: string) => api.del(`/api/vorlagen/${id}`),
    onSuccess: () => client.invalidateQueries({ queryKey: ["vorlagen"] }),
  });
  return (
    <section className="block">
      <div className="block-kopf"><h2>Vorlagen</h2></div>
      <div className="block-inhalt">
        {vorlagen.data && vorlagen.data.length > 0 ? (
          <ul style={{ listStyle: "none", padding: 0, margin: "0 0 var(--am-raum-3)", display: "grid", gap: "var(--am-raum-1)" }}>
            {vorlagen.data.map((v) => (
              <li key={v.id} style={{ display: "flex", alignItems: "center", gap: "var(--am-raum-2)" }}>
                <button type="button" className="btn btn-still btn-klein" onClick={() => beiWahl(v)}>{v.name}</button>
                <span style={{ flex: 1, fontSize: "0.8125rem", color: "var(--am-text-gedaempft)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{v.betreff}</span>
                <button type="button" className="btn btn-still btn-klein" aria-label={`Vorlage ${v.name} löschen`} onClick={() => loeschen.mutate(v.id)}>×</button>
              </li>
            ))}
          </ul>
        ) : (
          <p style={{ fontSize: "0.8125rem", color: "var(--am-text-gedaempft)", marginBottom: "var(--am-raum-3)" }}>Noch keine Vorlage. Betreff und Text unten schreiben, dann hier ablegen.</p>
        )}
        <div style={{ display: "flex", gap: "var(--am-raum-2)" }}>
          <input value={name} onChange={(e) => setName(e.target.value)} placeholder="Als Vorlage ablegen: Name" aria-label="Name der Vorlage" style={{ flex: 1 }} />
          <button type="button" className="btn btn-sekundaer btn-klein" disabled={!name.trim() || !betreff.trim() || !text.trim() || ablegen.isPending} onClick={() => ablegen.mutate()}>Ablegen</button>
        </div>
        {ablegen.isError && <Fehler text={(ablegen.error as Error).message} />}
      </div>
    </section>
  );
}

export default function KampagneSeite({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const router = useRouter();
  const client = useQueryClient();
  const kampagne = useQuery({ queryKey: ["kampagne", id], queryFn: () => api.get<Kampagne>(`/api/kampagnen/${id}`), refetchInterval: (q) => (q.state.data?.status === "laeuft" ? 5000 : false) });
  const vorschau = useQuery({ queryKey: ["kampagne", id, "vorschau"], queryFn: () => api.get<Kampagnenvorschau>(`/api/kampagnen/${id}/vorschau`) });
  const listen = useQuery({ queryKey: ["listen"], queryFn: () => api.get<Liste[]>("/api/listen") });
  const einstellungen = useQuery({ queryKey: ["einstellungen"], queryFn: () => api.get<OrgSettings>("/api/settings"), staleTime: 60_000 });

  const [name, setName] = useState("");
  const [betreff, setBetreff] = useState("");
  const [text, setText] = useState("");
  const [listeId, setListeId] = useState("");
  const [geaendert, setGeaendert] = useState(false);
  useEffect(() => {
    if (kampagne.data && !geaendert) {
      setName(kampagne.data.name); setBetreff(kampagne.data.betreff); setText(kampagne.data.text); setListeId(kampagne.data.liste_id ?? "");
    }
  }, [kampagne.data, geaendert]);

  const frisch = () => {
    client.invalidateQueries({ queryKey: ["kampagne", id] });
    client.invalidateQueries({ queryKey: ["kampagnen"] });
  };
  const speichern = useMutation({
    mutationFn: () => api.patch<Kampagne>(`/api/kampagnen/${id}`, { name, betreff, text, liste_id: listeId || null }),
    onSuccess: () => { setGeaendert(false); frisch(); },
  });
  const testen = useMutation({ mutationFn: () => api.post<{ an: string }>(`/api/kampagnen/${id}/testen`) });
  const starten = useMutation({ mutationFn: () => api.post<Kampagne>(`/api/kampagnen/${id}/starten`), onSuccess: () => { setSicher(false); frisch(); } });
  const abbrechen = useMutation({ mutationFn: () => api.post<Kampagne>(`/api/kampagnen/${id}/abbrechen`), onSuccess: frisch });
  const loeschen = useMutation({ mutationFn: () => api.del(`/api/kampagnen/${id}`), onSuccess: () => { client.invalidateQueries({ queryKey: ["kampagnen"] }); router.push("/kampagnen"); } });
  const [sicher, setSicher] = useState(false);

  if (kampagne.isPending) return <Laedt />;
  if (kampagne.isError) return <Fehler text={(kampagne.error as Error).message} />;
  const k = kampagne.data!;
  const entwurf = k.status === "entwurf";
  const bereit = !!einstellungen.data?.smtp_ready && !!einstellungen.data?.links_basis_wirksam;
  const v = vorschau.data;

  return (
    <>
      <Seitenkopf titel={k.name} zahl={k.liste_name ? `an „${k.liste_name}“` : "ohne Liste"} pfad={{ text: "← Kampagnen", href: "/kampagnen" }}>
        <span className="stufe" data-art={KAMPAGNE_STATUS_ART[k.status]}>{KAMPAGNE_STATUS_TEXT[k.status]}</span>
      </Seitenkopf>

      {!entwurf && (
        <dl className="kennzahlen" style={{ margin: "0 var(--am-raum-8) var(--am-raum-6)" }}>
          <div className="kennzahl"><dt>Empfänger</dt><dd>{k.empfaenger}</dd><div className="kennzahl-fuss">{k.uebergangen} übergangen (keine Einwilligung oder Adresse)</div></div>
          <div className="kennzahl"><dt>Gesendet</dt><dd>{k.gesendet}</dd><div className="kennzahl-fuss">{k.wartend} warten · {k.fehlgeschlagen} fehlgeschlagen</div></div>
          <div className="kennzahl"><dt>Klicks</dt><dd>{k.klicks}</dd><div className="kennzahl-fuss">{k.klicker} Personen</div></div>
          <div className="kennzahl"><dt>Abgemeldet</dt><dd>{k.abgemeldet}</dd><div className="kennzahl-fuss">über den Link in der Mail</div></div>
        </dl>
      )}

      <div className="datensatz">
        <div>
          <section className="block">
            <div className="block-kopf"><h2>Die Mail</h2></div>
            <div className="block-inhalt">
              <div className="feld">
                <label htmlFor="ka-name">Name <span className="optional">nur für Sie</span></label>
                <input id="ka-name" value={name} onChange={(e) => { setName(e.target.value); setGeaendert(true); }} />
              </div>
              <div className="feld">
                <label htmlFor="ka-liste">An wen</label>
                <select id="ka-liste" value={listeId} disabled={!entwurf} onChange={(e) => { setListeId(e.target.value); setGeaendert(true); }}>
                  <option value="">— Liste wählen —</option>
                  {listen.data?.map((l) => <option key={l.id} value={l.id}>{l.name} — {l.berechtigt} von {l.gemeint} dürfen Post</option>)}
                </select>
                {listeId && <p className="feld-hinweis"><Link href={`/listen/${listeId}`}>Liste ansehen</Link></p>}
              </div>
              <div className="feld">
                <label htmlFor="ka-betreff">Betreff</label>
                <input id="ka-betreff" value={betreff} disabled={!entwurf} onChange={(e) => { setBetreff(e.target.value); setGeaendert(true); }} placeholder="Neu bei uns, {{vorname}}" />
              </div>
              <div className="feld">
                <label htmlFor="ka-text">Text</label>
                <textarea id="ka-text" rows={14} value={text} disabled={!entwurf} onChange={(e) => { setText(e.target.value); setGeaendert(true); }} placeholder={"{{anrede}},\n\n…"} />
                <p className="feld-hinweis">
                  Platzhalter: <code>{"{{anrede}}"}</code> <code>{"{{vorname}}"}</code> <code>{"{{nachname}}"}</code> <code>{"{{firma}}"}</code> <code>{"{{position}}"}</code>.
                  Jeder Link wird gezählt. Der Abmeldelink kommt von selbst ans Ende — oder dorthin, wo <code>{"{{abmeldelink}}"}</code> steht.
                </p>
              </div>
              {speichern.isError && <Fehler text={(speichern.error as Error).message} />}
              <div className="btn-reihe">
                <button type="button" className="btn btn-primaer" disabled={!geaendert || speichern.isPending} onClick={() => speichern.mutate()}>
                  {speichern.isPending ? "Speichert …" : "Speichern"}
                </button>
                <button type="button" className="btn btn-sekundaer" disabled={testen.isPending || !bereit || geaendert || !betreff.trim() || !text.trim()} title={geaendert ? "Erst speichern" : undefined} onClick={() => testen.mutate()}>
                  {testen.isPending ? "Schickt …" : "Testmail an mich"}
                </button>
                {testen.isSuccess && <span style={{ fontSize: "0.8125rem", color: "var(--am-erfolg)", alignSelf: "center" }}>Unterwegs an {testen.data.an}.</span>}
              </div>
              {testen.isError && <Fehler text={(testen.error as Error).message} />}
            </div>
          </section>

          {entwurf && <Vorlagen betreff={betreff} text={text} beiWahl={(vl) => { setBetreff(vl.betreff); setText(vl.text); setGeaendert(true); }} />}
        </div>

        <div>
          {entwurf && (
            <section className="block">
              <div className="block-kopf"><h2>Senden</h2></div>
              <div className="block-inhalt">
                {v && (
                  <dl>
                    <div className="eigenschaft"><dt>Gemeint</dt><dd>{v.gemeint}</dd></div>
                    <div className="eigenschaft"><dt>Bekommen die Mail</dt><dd>{v.berechtigt}</dd></div>
                    <div className="eigenschaft"><dt>Übergangen</dt><dd>{v.uebergangen} — ohne Einwilligung oder Adresse</dd></div>
                  </dl>
                )}
                {!bereit && (
                  <div className="hinweis" data-art="achtung" style={{ marginTop: "var(--am-raum-3)" }}>
                    <span>{!einstellungen.data?.smtp_ready ? "Kein Versand eingerichtet — unter Einstellungen → E-Mail nachholen." : "Die Adresse der öffentlichen Links fehlt — unter Einstellungen → E-Mail."}</span>
                  </div>
                )}
                {starten.isError && <Fehler text={(starten.error as Error).message} />}
                <div className="btn-reihe" style={{ marginTop: "var(--am-raum-4)" }}>
                  {sicher ? (
                    <>
                      <button type="button" className="btn btn-primaer" disabled={starten.isPending} onClick={() => starten.mutate()}>
                        {starten.isPending ? "Startet …" : `Ja, an ${v?.berechtigt ?? "…"} senden`}
                      </button>
                      <button type="button" className="btn btn-still" onClick={() => setSicher(false)}>Abbrechen</button>
                    </>
                  ) : (
                    <button type="button" className="btn btn-primaer" disabled={!bereit || geaendert || !listeId || !(v && v.berechtigt > 0)} title={geaendert ? "Erst speichern" : undefined} onClick={() => setSicher(true)}>
                      Jetzt senden
                    </button>
                  )}
                </div>
                <p style={{ fontSize: "0.75rem", color: "var(--am-text-gedaempft)", marginTop: "var(--am-raum-3)" }}>
                  Eine Kampagne startet einmal. Danach lässt sie sich nicht mehr ändern, nur anhalten.
                </p>
              </div>
            </section>
          )}

          {k.status === "laeuft" && (
            <section className="block">
              <div className="block-kopf"><h2>Läuft</h2></div>
              <div className="block-inhalt">
                <p style={{ fontSize: "0.875rem", color: "var(--am-text-sekundaer)" }}>Gestartet {datumZeit(k.gestartet_am)}. Die Mails gehen nach und nach hinaus; die Zahlen oben laufen mit.</p>
                {abbrechen.isError && <Fehler text={(abbrechen.error as Error).message} />}
                <div className="btn-reihe" style={{ marginTop: "var(--am-raum-3)" }}>
                  <button type="button" className="btn btn-gefahr" disabled={abbrechen.isPending} onClick={() => abbrechen.mutate()}>Anhalten — Rest nicht senden</button>
                </div>
              </div>
            </section>
          )}

          {v && (
            <section className="block">
              <div className="block-kopf"><h2>So kommt es an</h2></div>
              <div className="block-inhalt">
                <p style={{ fontWeight: 600, marginBottom: "var(--am-raum-2)" }}>{v.beispiel_betreff || <span style={{ color: "var(--am-text-gedaempft)" }}>(kein Betreff)</span>}</p>
                <pre style={{ whiteSpace: "pre-wrap", fontFamily: "inherit", fontSize: "0.875rem", margin: 0 }}>{v.beispiel_text || "(kein Text)"}</pre>
              </div>
            </section>
          )}

          {entwurf && (
            <div className="btn-reihe" style={{ padding: "0 var(--am-raum-2)" }}>
              <button type="button" className="btn btn-still" disabled={loeschen.isPending} onClick={() => loeschen.mutate()}>Kampagne löschen</button>
            </div>
          )}
        </div>
      </div>
    </>
  );
}
