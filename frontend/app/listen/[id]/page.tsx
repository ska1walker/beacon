"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { use, useEffect, useState } from "react";
import { api } from "@/lib/api";
import { datum, EINWILLIGUNG_TEXT, personName } from "@/lib/format";
import type { Bedingung, Contact, Feldauskunft, Liste, Listenmitglied } from "@/lib/typen";
import { Filterbau } from "@/components/filterbau";
import { Seitenkopf } from "@/components/seitenkopf";
import { Fehler, Laedt, Leer } from "@/components/zustaende";

/** Kontakte suchen und in eine statische Liste legen. */
function Hinzufuegen({ liste, drin }: { liste: Liste; drin: Set<string> }) {
  const client = useQueryClient();
  const [q, setQ] = useState("");
  const treffer = useQuery({
    queryKey: ["kontakt-suche", q],
    queryFn: () => api.get<Contact[]>(`/api/contacts?q=${encodeURIComponent(q)}&limit=20`),
    enabled: q.trim().length >= 2,
  });
  const hinzu = useMutation({
    mutationFn: (contact_ids: string[]) => api.post<Liste>(`/api/listen/${liste.id}/mitglieder`, { contact_ids }),
    onSuccess: () => {
      client.invalidateQueries({ queryKey: ["liste", liste.id] });
      client.invalidateQueries({ queryKey: ["listen"] });
    },
  });
  const neu = (treffer.data ?? []).filter((k) => !drin.has(k.id));
  return (
    <section className="block">
      <div className="block-kopf"><h2>Kontakte hinzufügen</h2></div>
      <div className="block-inhalt">
        <div className="feld">
          <label htmlFor="liste-suche">Name, E-Mail oder Firma</label>
          <input id="liste-suche" value={q} onChange={(e) => setQ(e.target.value)} placeholder="mindestens zwei Zeichen" />
        </div>
        {treffer.data && neu.length === 0 && q.trim().length >= 2 && (
          <p className="erfassung-hinweis">Niemand gefunden, der nicht schon drin ist.</p>
        )}
        {neu.length > 0 && (
          <>
            <ul style={{ listStyle: "none", padding: 0, margin: 0, display: "grid", gap: "var(--am-raum-1)" }}>
              {neu.map((k) => (
                <li key={k.id} style={{ display: "flex", alignItems: "center", gap: "var(--am-raum-3)" }}>
                  <button type="button" className="btn btn-still btn-klein" disabled={hinzu.isPending} onClick={() => hinzu.mutate([k.id])}>+</button>
                  <span>{personName(k.first_name, k.last_name)}</span>
                  <span style={{ color: "var(--am-text-gedaempft)", fontSize: "0.8125rem" }}>{k.email ?? "ohne E-Mail"}{k.company_name ? ` · ${k.company_name}` : ""}</span>
                </li>
              ))}
            </ul>
            <div className="btn-reihe" style={{ marginTop: "var(--am-raum-3)" }}>
              <button type="button" className="btn btn-sekundaer btn-klein" disabled={hinzu.isPending} onClick={() => hinzu.mutate(neu.map((k) => k.id))}>
                Alle {neu.length} hinzufügen
              </button>
            </div>
          </>
        )}
        {hinzu.isError && <Fehler text={(hinzu.error as Error).message} />}
      </div>
    </section>
  );
}

export default function ListeSeite({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const router = useRouter();
  const client = useQueryClient();
  const liste = useQuery({ queryKey: ["liste", id], queryFn: () => api.get<Liste>(`/api/listen/${id}`) });
  const mitglieder = useQuery({ queryKey: ["liste", id, "mitglieder"], queryFn: () => api.get<Listenmitglied[]>(`/api/listen/${id}/mitglieder`) });
  const auskunft = useQuery({
    queryKey: ["segment-felder", "contacts"],
    queryFn: () => api.get<Feldauskunft>("/api/ansichten/felder?entity=contacts"),
    staleTime: 5 * 60_000,
  });

  const [name, setName] = useState("");
  const [filter, setFilter] = useState<Bedingung[]>([]);
  const [verknuepfung, setVerknuepfung] = useState<"und" | "oder">("und");
  const [geaendert, setGeaendert] = useState(false);
  useEffect(() => {
    if (liste.data && !geaendert) {
      setName(liste.data.name);
      setFilter(liste.data.filter);
      setVerknuepfung(liste.data.verknuepfung);
    }
  }, [liste.data, geaendert]);

  const frisch = () => {
    client.invalidateQueries({ queryKey: ["liste", id] });
    client.invalidateQueries({ queryKey: ["listen"] });
  };
  const speichern = useMutation({
    mutationFn: () => api.patch<Liste>(`/api/listen/${id}`, { name, filter, verknuepfung }),
    onSuccess: () => { setGeaendert(false); frisch(); },
  });
  const entfernen = useMutation({
    mutationFn: (contact_id: string) => api.del(`/api/listen/${id}/mitglieder/${contact_id}`),
    onSuccess: frisch,
  });
  const loeschen = useMutation({
    mutationFn: () => api.del(`/api/listen/${id}`),
    onSuccess: () => { client.invalidateQueries({ queryKey: ["listen"] }); router.push("/listen"); },
  });
  const [sicher, setSicher] = useState(false);

  if (liste.isPending) return <Laedt />;
  if (liste.isError) return <Fehler text={(liste.error as Error).message} />;
  const l = liste.data!;
  const drin = new Set((mitglieder.data ?? []).map((m) => m.id));

  return (
    <>
      <Seitenkopf titel={l.name} zahl={`${l.art === "aktiv" ? "aktive" : "statische"} Liste · ${l.gemeint} gemeint · ${l.berechtigt} dürfen Post`} pfad={{ text: "← Listen", href: "/listen" }}>
        <Link href={`/kampagnen?liste=${l.id}`} className="btn btn-sekundaer">Kampagne an diese Liste</Link>
      </Seitenkopf>

      <div className="datensatz">
        <div>
          <section className="block">
            <div className="block-kopf"><h2>Über diese Liste</h2></div>
            <div className="block-inhalt">
              <div className="feld">
                <label htmlFor="liste-name">Name</label>
                <input id="liste-name" value={name} onChange={(e) => { setName(e.target.value); setGeaendert(true); }} />
              </div>
              {l.art === "aktiv" && auskunft.data && (
                <div className="feld">
                  <label>Wer ist drin</label>
                  <Filterbau
                    auskunft={auskunft.data}
                    bedingungen={filter}
                    verknuepfung={verknuepfung}
                    beiAendern={(neu) => { setFilter(neu); setGeaendert(true); }}
                    beiVerknuepfung={(v) => { setVerknuepfung(v); setGeaendert(true); }}
                  />
                </div>
              )}
              {speichern.isError && <Fehler text={(speichern.error as Error).message} />}
              <div className="btn-reihe">
                <button type="button" className="btn btn-primaer" disabled={!geaendert || speichern.isPending} onClick={() => speichern.mutate()}>
                  {speichern.isPending ? "Speichert …" : "Speichern"}
                </button>
                {sicher ? (
                  <>
                    <button type="button" className="btn btn-gefahr" disabled={loeschen.isPending} onClick={() => loeschen.mutate()}>Ja, Liste löschen</button>
                    <button type="button" className="btn btn-still" onClick={() => setSicher(false)}>Abbrechen</button>
                  </>
                ) : (
                  <button type="button" className="btn btn-still" onClick={() => setSicher(true)}>Liste löschen</button>
                )}
              </div>
            </div>
          </section>

          {l.art === "statisch" && <Hinzufuegen liste={l} drin={drin} />}
        </div>

        <div>
          <section className="block">
            <div className="block-kopf">
              <h2>{l.art === "aktiv" ? "Wer gerade drin ist" : "Mitglieder"}</h2>
              <span className="stufe">{mitglieder.data?.length ?? "…"}</span>
            </div>
            <div className="block-inhalt">
              {mitglieder.isPending && <Laedt />}
              {mitglieder.data && mitglieder.data.length === 0 && (
                <Leer titel="Noch niemand" text={l.art === "aktiv" ? "Der Filter trifft zurzeit keinen Kontakt." : "Links Kontakte suchen und hinzufügen — oder in der Kontaktliste mehrere wählen und „Zur Liste“ drücken."} />
              )}
              {mitglieder.data && mitglieder.data.length > 0 && (
                <table className="tabelle">
                  <thead>
                    <tr><th>Kontakt</th><th>Firma</th><th>Einwilligung</th>{l.art === "statisch" && <th>Seit</th>}<th></th></tr>
                  </thead>
                  <tbody>
                    {mitglieder.data.map((m) => (
                      <tr key={m.id}>
                        <td className="haupt">
                          <Link href={`/kontakte/${m.id}`} className="zellen-link">{personName(m.first_name, m.last_name)}</Link>
                          <div style={{ fontSize: "0.8125rem", color: "var(--am-text-gedaempft)" }}>{m.email ?? "ohne E-Mail"}</div>
                        </td>
                        <td>{m.company_name ?? "—"}</td>
                        <td>
                          <span className="stufe" data-art={m.einwilligung === "bestaetigt" || m.einwilligung === "bestandskunde" ? "won" : m.einwilligung === "abgemeldet" ? "lost" : undefined}>
                            {EINWILLIGUNG_TEXT[m.einwilligung] ?? m.einwilligung}
                          </span>
                        </td>
                        {l.art === "statisch" && <td>{datum(m.hinzugefuegt_am)}</td>}
                        <td style={{ textAlign: "right" }}>
                          {l.art === "statisch" && (
                            <button type="button" className="btn btn-still btn-klein" disabled={entfernen.isPending} onClick={() => entfernen.mutate(m.id)}>Entfernen</button>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          </section>
        </div>
      </div>
    </>
  );
}
