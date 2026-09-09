"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ArrowDown,
  ArrowUp,
  Bookmark,
  Columns3,
  Download,
  Filter as FilterZeichen,
  Search,
  Trash2,
  X,
} from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import { api, suchparameter } from "@/lib/api";
import { ausfuhrPfad, EXPORTIERBAR } from "@/lib/ausfuhr";
import { anzahl as anzahlText, datum, euro, OHNE_WERT, OPERATOR_TEXT } from "@/lib/format";
import type {
  Liste,
  Ansicht,
  Bedingung,
  Feldauskunft,
  LifecycleStage,
  Objektart,
  Segmentfeld,
} from "@/lib/typen";
import { Filterbau } from "@/components/filterbau";
import { Stufenpille } from "@/components/stufe";
import { Mehrfachplaettchen } from "@/components/mehrfachauswahl";
import { Prioritaetspille } from "@/components/prioritaet";
import { Fehler, Laedt, Leer } from "@/components/zustaende";

type Datensatz = Record<string, unknown> & { id: string; custom?: Record<string, unknown> };

/** Der Zustand einer Liste — gespeichert ist er eine Ansicht. */
interface Lage {
  filter: Bedingung[];
  verknuepfung: "und" | "oder";
  spalten: string[];
  sort_feld: string;
  sort_richtung: "asc" | "desc";
}

function gleich(a: Lage, b: Lage): boolean {
  return JSON.stringify(a) === JSON.stringify(b);
}

/**
 * Nur Bedingungen, die schon etwas aussagen.
 *
 * Wer eine Bedingung anlegt, hat im ersten Moment ein leeres Wertfeld.
 * Die mitzuschicken hieße, den Server nach „Ort ist nichts“ zu fragen —
 * er antwortet mit einem Fehler, und die Liste stünde bei jedem neuen
 * Filter kurz auf Rot. Sie zählt erst, wenn sie vollständig ist.
 */
function nutzbar(bedingungen: Bedingung[]): Bedingung[] {
  return bedingungen.filter((b) => {
    if (!b.feld || !b.operator) return false;
    if (OHNE_WERT.has(b.operator)) return true;
    if (Array.isArray(b.wert)) return b.wert.length > 0;
    return b.wert !== null && b.wert !== undefined && String(b.wert).trim() !== "";
  });
}

/**
 * Die Listenansicht, wie HubSpot sie führt: gespeicherte Ansichten als
 * Reiter, Bedingungen darunter, wählbare Spalten, Sortierung am
 * Spaltenkopf, Auswahl und Aktionen für den Stapel.
 *
 * Dieselbe Komponente trägt Firmen und Kontakte. Was die beiden
 * unterscheidet, kommt vom Server: `/api/ansichten/felder` sagt, welche
 * Felder es gibt, wie sie heißen und welche Operatoren zu ihnen passen.
 * Eine selbst angelegte Eigenschaft ist damit ohne eine Zeile Code hier
 * filterbar und als Spalte wählbar.
 */
export function Segmentliste({
  entity,
  basisPfad,
  suchePlatzhalter,
  leerTitel,
  leerText,
  stapelfelder,
}: {
  entity: Objektart;
  basisPfad: string;
  suchePlatzhalter: string;
  leerTitel: string;
  leerText: string;
  /** Welche Felder sich im Stapel setzen lassen — je Objekt andere. */
  stapelfelder: { schluessel: string; text: string }[];
}) {
  const router = useRouter();
  const client = useQueryClient();

  const [suche, setSuche] = useState("");
  const [ansichtId, setAnsichtId] = useState<string | null>(null);
  const [lage, setLage] = useState<Lage | null>(null);
  const [filterOffen, setFilterOffen] = useState(false);
  const [spaltenOffen, setSpaltenOffen] = useState(false);
  const [gewaehlt, setGewaehlt] = useState<string[]>([]);
  const [speichernOffen, setSpeichernOffen] = useState(false);
  const [neuerName, setNeuerName] = useState("");
  const [nurIch, setNurIch] = useState(false);

  const auskunft = useQuery({
    queryKey: ["segment-felder", entity],
    queryFn: () => api.get<Feldauskunft>(`/api/ansichten/felder?entity=${entity}`),
    staleTime: 5 * 60_000,
  });

  const ansichten = useQuery({
    queryKey: ["ansichten", entity],
    queryFn: () => api.get<Ansicht[]>(`/api/ansichten?entity=${entity}`),
  });

  // Die Grundlage: alles, Vorgabespalten, Vorgabesortierung.
  const grundlage: Lage | null = useMemo(() => {
    if (!auskunft.data) return null;
    return {
      filter: [],
      verknuepfung: "und",
      spalten: auskunft.data.vorgabe_spalten,
      sort_feld: auskunft.data.vorgabe_sortierung.feld,
      sort_richtung: auskunft.data.vorgabe_sortierung.richtung,
    };
  }, [auskunft.data]);

  useEffect(() => {
    if (grundlage && !lage) setLage(grundlage);
  }, [grundlage, lage]);

  const aktiveAnsicht = ansichten.data?.find((a) => a.id === ansichtId) ?? null;

  function ansichtLaden(a: Ansicht | null) {
    setAnsichtId(a?.id ?? null);
    setGewaehlt([]);
    if (!a) {
      setLage(grundlage);
      return;
    }
    setLage({
      filter: a.filter,
      verknuepfung: a.verknuepfung,
      spalten: a.spalten.length > 0 ? a.spalten : (grundlage?.spalten ?? []),
      sort_feld: a.sort_feld ?? grundlage?.sort_feld ?? "updated_at",
      sort_richtung: a.sort_richtung,
    });
  }

  // Was die Ansicht gespeichert hat, verglichen mit dem, was gerade gilt.
  const abweichung = useMemo(() => {
    if (!lage) return false;
    if (!aktiveAnsicht) return grundlage ? !gleich(lage, grundlage) : false;
    return !gleich(lage, {
      filter: aktiveAnsicht.filter,
      verknuepfung: aktiveAnsicht.verknuepfung,
      spalten: aktiveAnsicht.spalten.length > 0 ? aktiveAnsicht.spalten : (grundlage?.spalten ?? []),
      sort_feld: aktiveAnsicht.sort_feld ?? grundlage?.sort_feld ?? "updated_at",
      sort_richtung: aktiveAnsicht.sort_richtung,
    });
  }, [lage, aktiveAnsicht, grundlage]);

  const scharf = lage ? nutzbar(lage.filter) : [];

  const abfrageparameter = suchparameter({
    q: suche,
    filter: scharf.length > 0 ? JSON.stringify(scharf) : "",
    sort: lage?.sort_feld,
    richtung: lage?.sort_richtung,
    limit: 200,
  });

  const zeilen = useQuery({
    enabled: Boolean(lage),
    queryKey: ["segment", entity, abfrageparameter],
    queryFn: () => api.get<Datensatz[]>(`/api/${entity}${abfrageparameter}`),
  });

  const gesamt = useQuery({
    enabled: Boolean(lage),
    queryKey: ["segment-anzahl", entity, abfrageparameter],
    queryFn: () =>
      api.get<{ anzahl: number }>(
        `/api/${entity}/anzahl${suchparameter({
          q: suche,
          filter: scharf.length > 0 ? JSON.stringify(scharf) : "",
        })}`,
      ),
  });

  const speichern = useMutation({
    mutationFn: () =>
      // Halbfertige Bedingungen werden nicht mitgespeichert — sonst
      // scheitert die Ansicht beim nächsten Öffnen an sich selbst.
      aktiveAnsicht
        ? api.patch<Ansicht>(`/api/ansichten/${aktiveAnsicht.id}`, { ...lage, filter: scharf })
        : api.post<Ansicht>("/api/ansichten", {
            entity,
            name: neuerName,
            nur_ich: nurIch,
            ...lage,
            filter: scharf,
          }),
    onSuccess: (a) => {
      setSpeichernOffen(false);
      setNeuerName("");
      setNurIch(false);
      setAnsichtId(a.id);
      client.invalidateQueries({ queryKey: ["ansichten", entity] });
    },
  });

  const loeschenAnsicht = useMutation({
    mutationFn: (id: string) => api.del(`/api/ansichten/${id}`),
    onSuccess: () => {
      ansichtLaden(null);
      client.invalidateQueries({ queryKey: ["ansichten", entity] });
    },
  });

  const stapel = useMutation({
    mutationFn: (aenderung: Record<string, unknown>) =>
      api.post<{ geaendert: number }>(`/api/${entity}/mehrere`, { ids: gewaehlt, ...aenderung }),
    onSuccess: () => {
      setGewaehlt([]);
      client.invalidateQueries({ queryKey: ["segment", entity] });
      client.invalidateQueries({ queryKey: ["segment-anzahl", entity] });
    },
  });

  // Nur für Kontakte: mehrere auf einmal in eine statische Liste legen.
  const listen = useQuery({
    queryKey: ["listen"],
    queryFn: () => api.get<Liste[]>("/api/listen"),
    enabled: entity === "contacts",
  });
  const zurListe = useMutation({
    mutationFn: (liste_id: string) => api.post(`/api/listen/${liste_id}/mitglieder`, { contact_ids: gewaehlt }),
    onSuccess: () => {
      setGewaehlt([]);
      client.invalidateQueries({ queryKey: ["listen"] });
    },
  });

  const stapelLoeschen = useMutation({
    mutationFn: () =>
      api.post<{ geloescht: number }>(`/api/${entity}/mehrere/loeschen`, { ids: gewaehlt }),
    onSuccess: () => {
      setGewaehlt([]);
      client.invalidateQueries({ queryKey: ["segment", entity] });
      client.invalidateQueries({ queryKey: ["segment-anzahl", entity] });
    },
  });

  if (auskunft.isPending || !lage) return <Laedt />;
  if (auskunft.isError) return <Fehler text={(auskunft.error as Error).message} />;

  const felder = auskunft.data!.felder;
  const spalten = lage.spalten
    .map((s) => felder.find((f) => f.schluessel === s))
    .filter((f): f is Segmentfeld => Boolean(f));

  function sortiere(schluessel: string) {
    setLage((l) =>
      l
        ? {
            ...l,
            sort_feld: schluessel,
            sort_richtung: l.sort_feld === schluessel && l.sort_richtung === "asc" ? "desc" : "asc",
          }
        : l,
    );
  }

  const alleGewaehlt = (zeilen.data?.length ?? 0) > 0 && gewaehlt.length === zeilen.data!.length;

  return (
    <>
      {/* Reiter: die gespeicherten Fragen an den Bestand. */}
      <div className="ansichtsleiste" role="tablist" aria-label="Ansichten">
        <button
          type="button"
          role="tab"
          aria-selected={ansichtId === null}
          className={`ansicht-reiter${ansichtId === null ? " aktiv" : ""}`}
          onClick={() => ansichtLaden(null)}
        >
          Alle
        </button>
        {ansichten.data?.map((a) => (
          <span key={a.id} className={`ansicht-reiter-huelle${ansichtId === a.id ? " aktiv" : ""}`}>
            <button
              type="button"
              role="tab"
              aria-selected={ansichtId === a.id}
              className={`ansicht-reiter${ansichtId === a.id ? " aktiv" : ""}`}
              onClick={() => ansichtLaden(a)}
            >
              {a.name}
              {a.owner_id && <span className="ansicht-privat" title="Nur für Sie sichtbar">·</span>}
            </button>
            {ansichtId === a.id && (
              <button
                type="button"
                className="ansicht-weg"
                aria-label={`Ansicht „${a.name}" löschen`}
                onClick={() => loeschenAnsicht.mutate(a.id)}
              >
                <X size={12} aria-hidden="true" />
              </button>
            )}
          </span>
        ))}
      </div>

      <div className="werkzeugleiste">
        <div className="suchfeld">
          <Search size={16} aria-hidden="true" />
          <input
            value={suche}
            onChange={(e) => setSuche(e.target.value)}
            placeholder={suchePlatzhalter}
            aria-label="Durchsuchen"
          />
        </div>

        <button
          type="button"
          className={`btn btn-sekundaer btn-klein${scharf.length > 0 ? " traegt" : ""}`}
          aria-expanded={filterOffen}
          onClick={() => setFilterOffen((o) => !o)}
        >
          <FilterZeichen size={14} aria-hidden="true" />
          Filter
          {scharf.length > 0 && <span className="zahlpille">{scharf.length}</span>}
        </button>

        <button
          type="button"
          className="btn btn-sekundaer btn-klein"
          aria-expanded={spaltenOffen}
          onClick={() => setSpaltenOffen((o) => !o)}
        >
          <Columns3 size={14} aria-hidden="true" />
          Spalten
        </button>

        {EXPORTIERBAR.has(entity) && (
          /* Ein gewöhnlicher Link, kein `fetch`: Der Keks geht von selbst
             mit, und der Browser hält die Datei nie ganz im Speicher. */
          <a
            className="btn btn-sekundaer btn-klein"
            download
            href={ausfuhrPfad(entity, {
              q: suche,
              filter: scharf.length > 0 ? JSON.stringify(scharf) : "",
              sort: lage?.sort_feld,
              richtung: lage?.sort_richtung,
              spalten: lage?.spalten,
            })}
            title="Diese Liste als CSV — mit Filter, Spalten und Sortierung von hier"
          >
            <Download size={14} aria-hidden="true" />
            Exportieren
          </a>
        )}

        {abweichung && (
          <button
            type="button"
            className="btn btn-sekundaer btn-klein"
            onClick={() => (aktiveAnsicht ? speichern.mutate() : setSpeichernOffen(true))}
          >
            <Bookmark size={14} aria-hidden="true" />
            {aktiveAnsicht ? "Ansicht aktualisieren" : "Als Ansicht speichern"}
          </button>
        )}

        <span className="werkzeug-zahl">
          {gesamt.data ? anzahlText(gesamt.data.anzahl, "Eintrag", "Einträge") : ""}
          {gesamt.data && zeilen.data && gesamt.data.anzahl > zeilen.data.length
            ? ` · ${zeilen.data.length} gezeigt`
            : ""}
        </span>
      </div>

      {filterOffen && (
        <div className="block" style={{ marginBottom: "var(--am-raum-4)" }}>
          <div className="block-inhalt">
            <Filterbau
              auskunft={auskunft.data!}
              bedingungen={lage.filter}
              verknuepfung={lage.verknuepfung}
              beiAendern={(neu) => setLage({ ...lage, filter: neu })}
              beiVerknuepfung={(v) => setLage({ ...lage, verknuepfung: v })}
            />
          </div>
        </div>
      )}

      {spaltenOffen && (
        <div className="block" style={{ marginBottom: "var(--am-raum-4)" }}>
          <div className="block-inhalt">
            <p style={{ fontSize: "0.8125rem", color: "var(--am-text-sekundaer)", marginBottom: "var(--am-raum-3)" }}>
              Welche Spalten die Tabelle zeigt. Die Reihenfolge folgt der Feldliste.
            </p>
            <div className="spaltenwahl">
              {felder.map((f) => (
                <label key={f.schluessel}>
                  <input
                    type="checkbox"
                    checked={lage.spalten.includes(f.schluessel)}
                    onChange={(e) =>
                      setLage({
                        ...lage,
                        spalten: e.target.checked
                          ? felder.filter((x) => x.schluessel === f.schluessel || lage.spalten.includes(x.schluessel)).map((x) => x.schluessel)
                          : lage.spalten.filter((s) => s !== f.schluessel),
                      })
                    }
                  />
                  {f.text}
                </label>
              ))}
            </div>
          </div>
        </div>
      )}

      {speichernOffen && (
        <div className="block" style={{ marginBottom: "var(--am-raum-4)" }}>
          <div className="block-inhalt">
            <form
              style={{ display: "flex", gap: "var(--am-raum-2)", alignItems: "flex-end", flexWrap: "wrap" }}
              onSubmit={(e) => {
                e.preventDefault();
                if (neuerName.trim()) speichern.mutate();
              }}
            >
              <div className="feld" style={{ marginBottom: 0, flex: 1, minWidth: "14rem" }}>
                <label htmlFor="ansichtname">Name der Ansicht</label>
                <input
                  id="ansichtname"
                  value={neuerName}
                  onChange={(e) => setNeuerName(e.target.value)}
                  placeholder="Kunden in Hamburg"
                  autoFocus
                />
              </div>
              <label style={{ display: "flex", gap: "var(--am-raum-2)", alignItems: "center", paddingBottom: "var(--am-raum-2)" }}>
                <input type="checkbox" checked={nurIch} onChange={(e) => setNurIch(e.target.checked)} />
                Nur für mich
              </label>
              <button type="submit" className="btn btn-primaer" disabled={!neuerName.trim() || speichern.isPending}>
                Speichern
              </button>
              <button type="button" className="btn btn-still" onClick={() => setSpeichernOffen(false)}>
                Abbrechen
              </button>
            </form>
            {speichern.isError && <Fehler text={(speichern.error as Error).message} />}
          </div>
        </div>
      )}

      {/* Aktive Bedingungen als Zusammenfassung — auch wenn der Filterbau zu ist. */}
      {scharf.length > 0 && !filterOffen && (
        <div className="filterchips">
          {lage.filter.map((b, i) => {
            const feld = felder.find((f) => f.schluessel === b.feld);
            return (
              <span className="filterchip" key={i}>
                {feld?.text ?? b.feld} {OPERATOR_TEXT[b.operator] ?? b.operator}
                {!OHNE_WERT.has(b.operator) && ` ${Array.isArray(b.wert) ? b.wert.join(", ") : b.wert}`}
                <button
                  type="button"
                  aria-label="Bedingung entfernen"
                  onClick={() => setLage({ ...lage, filter: lage.filter.filter((_, j) => j !== i) })}
                >
                  <X size={11} aria-hidden="true" />
                </button>
              </span>
            );
          })}
          <button type="button" className="btn btn-still btn-klein" onClick={() => setLage({ ...lage, filter: [] })}>
            Alle entfernen
          </button>
        </div>
      )}

      {gewaehlt.length > 0 && (
        <Stapelleiste
          anzahl={gewaehlt.length}
          felder={stapelfelder}
          auskunft={auskunft.data!}
          laeuft={stapel.isPending || stapelLoeschen.isPending || zurListe.isPending}
          beiSetzen={(feld, wert) => stapel.mutate({ [feld]: wert })}
          beiLoeschen={() => stapelLoeschen.mutate()}
          beiAbwahl={() => setGewaehlt([])}
          listen={entity === "contacts" ? (listen.data ?? []).filter((l) => l.art === "statisch") : undefined}
          beiZurListe={(liste_id) => zurListe.mutate(liste_id)}
        />
      )}

      <div className="liste">
        {zeilen.isPending && <Laedt />}
        {zeilen.isError && <Fehler text={(zeilen.error as Error).message} />}
        {zeilen.data?.length === 0 && <Leer titel={leerTitel} text={leerText} />}
        {zeilen.data && zeilen.data.length > 0 && (
          <div className="rollbar">
            <table className="tabelle" style={{ minInlineSize: `${Math.max(42, spalten.length * 9)}rem` }}>
              <thead>
                <tr>
                  <th className="wahlspalte">
                    <input
                      type="checkbox"
                      aria-label="Alle auf dieser Seite wählen"
                      checked={alleGewaehlt}
                      onChange={(e) => setGewaehlt(e.target.checked ? zeilen.data!.map((z) => z.id) : [])}
                    />
                  </th>
                  {spalten.map((f) => (
                    <th
                      key={f.schluessel}
                      className={f.zahl ? "zahl" : undefined}
                      aria-sort={
                        lage.sort_feld === f.schluessel
                          ? lage.sort_richtung === "asc"
                            ? "ascending"
                            : "descending"
                          : "none"
                      }
                    >
                      <button type="button" className="spaltenkopf" onClick={() => sortiere(f.schluessel)}>
                        {f.text}
                        {lage.sort_feld === f.schluessel &&
                          (lage.sort_richtung === "asc" ? (
                            <ArrowUp size={12} aria-hidden="true" />
                          ) : (
                            <ArrowDown size={12} aria-hidden="true" />
                          ))}
                      </button>
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {zeilen.data.map((z) => (
                  <tr
                    key={z.id}
                    data-gewaehlt={gewaehlt.includes(z.id) ? "true" : undefined}
                    onClick={() => router.push(`${basisPfad}/${z.id}`)}
                  >
                    <td className="wahlspalte" onClick={(e) => e.stopPropagation()}>
                      <input
                        type="checkbox"
                        aria-label="Diesen Eintrag wählen"
                        checked={gewaehlt.includes(z.id)}
                        onChange={(e) =>
                          setGewaehlt((alt) =>
                            e.target.checked ? [...alt, z.id] : alt.filter((g) => g !== z.id),
                          )
                        }
                      />
                    </td>
                    {spalten.map((f, i) => (
                      <td key={f.schluessel} className={f.zahl ? "zahl" : i === 0 ? "haupt" : undefined}>
                        <Zelle feld={f} zeile={z} personen={auskunft.data!.personen} />
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </>
  );
}

/** Ein Wert in der Tabelle, nach der Art seines Feldes dargestellt. */
function Zelle({
  feld,
  zeile,
  personen,
}: {
  feld: Segmentfeld;
  zeile: Datensatz;
  personen: { id: string; name: string }[];
}) {
  const roh = feld.eigen
    ? (zeile.custom ?? {})[feld.schluessel.replace(/^custom\./, "")]
    : zeile[feld.schluessel];

  if (roh === null || roh === undefined || roh === "") return <>—</>;

  // Eine Mehrfachauswahl zeigt Plättchen, keinen Komma-Text: In einer
  // Zeile von zwölf Spalten ist „ISO 9001, ISO 27001, TISAX" ein Absatz,
  // und man sieht nicht mehr, wo ein Wert aufhört.
  if (Array.isArray(roh)) {
    const werte = roh.map(String);
    if (werte.length === 0) return <>—</>;
    return (
      <Mehrfachplaettchen
        werte={werte.map((w) => feld.optionen.find((o) => o.wert === w)?.text ?? w)}
      />
    );
  }

  if (feld.schluessel === "lifecycle_stage") {
    return <Stufenpille stufe={String(roh) as LifecycleStage} />;
  }
  if (feld.schluessel === "prioritaet") return <Prioritaetspille prioritaet={String(roh)} />;
  // Ein Auswahlfeld zeigt den Text seiner Option, nicht den gespeicherten
  // Wert. „wartet_auf_kontakt" ist ein Schlüssel, keine Beschriftung.
  if (feld.art === "auswahl") {
    const treffer = feld.optionen.find((o) => o.wert === String(roh));
    if (treffer) return <>{treffer.text}</>;
  }
  if (feld.schluessel === "open_amount_cents") return <>{euro(Number(roh))}</>;
  if (feld.art === "person") {
    return <>{personen.find((p) => p.id === String(roh))?.name ?? "—"}</>;
  }
  if (feld.art === "datum") return <>{datum(String(roh))}</>;
  if (feld.art === "jaNein") return <>{roh === true || roh === "true" ? "Ja" : "Nein"}</>;
  if (feld.schluessel === "email") {
    return (
      <a href={`mailto:${roh}`} onClick={(e) => e.stopPropagation()} className="zellen-link">
        {String(roh)}
      </a>
    );
  }
  if (feld.schluessel === "website" || feld.schluessel === "linkedin_url" || feld.schluessel === "domain") {
    const url = String(roh).startsWith("http") ? String(roh) : `https://${roh}`;
    return (
      <a
        href={url}
        target="_blank"
        rel="noreferrer noopener"
        onClick={(e) => e.stopPropagation()}
        className="zellen-link"
      >
        {String(roh).replace(/^https?:\/\/(www\.)?/, "")}
      </a>
    );
  }
  return <>{String(roh)}</>;
}

/** Was mit den gewählten Zeilen geschehen kann. */
function Stapelleiste({
  anzahl,
  felder,
  auskunft,
  laeuft,
  beiSetzen,
  beiLoeschen,
  beiAbwahl,
  listen,
  beiZurListe,
}: {
  anzahl: number;
  felder: { schluessel: string; text: string }[];
  auskunft: Feldauskunft;
  laeuft: boolean;
  beiSetzen: (feld: string, wert: string) => void;
  beiLoeschen: () => void;
  beiAbwahl: () => void;
  /** Statische Listen, in die die Auswahl gelegt werden kann — nur bei Kontakten. */
  listen?: Liste[];
  beiZurListe?: (liste_id: string) => void;
}) {
  const [feld, setFeld] = useState(felder[0]?.schluessel ?? "");
  const [wert, setWert] = useState("");
  const [sicher, setSicher] = useState(false);
  const [liste, setListe] = useState("");

  const definition = auskunft.felder.find((f) => f.schluessel === feld);

  return (
    <div className="stapelleiste">
      <strong>{anzahlText(anzahl, "Eintrag", "Einträge")} gewählt</strong>

      <select value={feld} onChange={(e) => { setFeld(e.target.value); setWert(""); }} aria-label="Feld setzen">
        {felder.map((f) => (
          <option key={f.schluessel} value={f.schluessel}>
            {f.text}
          </option>
        ))}
      </select>

      {definition?.art === "person" ? (
        <select value={wert} onChange={(e) => setWert(e.target.value)} aria-label="Wert">
          <option value="">— wählen —</option>
          {auskunft.personen.map((p) => (
            <option key={p.id} value={p.id}>{p.name}</option>
          ))}
        </select>
      ) : definition && definition.optionen.length > 0 ? (
        <select value={wert} onChange={(e) => setWert(e.target.value)} aria-label="Wert">
          <option value="">— wählen —</option>
          {definition.optionen.map((o) => (
            <option key={o.wert} value={o.wert}>{o.text}</option>
          ))}
        </select>
      ) : (
        <input value={wert} onChange={(e) => setWert(e.target.value)} placeholder="Wert" aria-label="Wert" />
      )}

      <button
        type="button"
        className="btn btn-primaer btn-klein"
        disabled={!wert || laeuft}
        onClick={() => beiSetzen(feld, wert)}
      >
        Setzen
      </button>

      {listen && listen.length > 0 && beiZurListe && (
        <>
          <select value={liste} onChange={(e) => setListe(e.target.value)} aria-label="Zur Liste">
            <option value="">Zur Liste …</option>
            {listen.map((l) => (
              <option key={l.id} value={l.id}>{l.name}</option>
            ))}
          </select>
          <button type="button" className="btn btn-sekundaer btn-klein" disabled={!liste || laeuft} onClick={() => { beiZurListe(liste); setListe(""); }}>
            Hinzufügen
          </button>
        </>
      )}

      <span className="stapel-luecke" />

      {sicher ? (
        <>
          <span className="stapel-frage">Wirklich {anzahlText(anzahl, "Eintrag", "Einträge")} löschen?</span>
          <button type="button" className="btn btn-gefahr btn-klein" onClick={beiLoeschen} disabled={laeuft}>
            Ja, löschen
          </button>
          <button type="button" className="btn btn-still btn-klein" onClick={() => setSicher(false)}>
            Abbrechen
          </button>
        </>
      ) : (
        <button type="button" className="btn btn-still btn-klein" onClick={() => setSicher(true)}>
          <Trash2 size={14} aria-hidden="true" />
          Löschen
        </button>
      )}

      <button type="button" className="btn btn-still btn-klein" onClick={beiAbwahl}>
        Auswahl aufheben
      </button>
    </div>
  );
}
