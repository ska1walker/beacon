"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, Circle } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { api, suchparameter } from "@/lib/api";
import {
  AUFGABEN_ART_TEXT,
  AUFGABEN_PHASE_TEXT,
  anzahl as anzahlText,
  datumZeit,
  frist,
  PRIORITAET_TEXT,
} from "@/lib/format";
import type { AufgabenArt, Aufgabenuebersicht, Deal, Mitglied, Task } from "@/lib/typen";
import { Seitenkopf } from "@/components/seitenkopf";
import { Prioritaetspille } from "@/components/prioritaet";
import { Segmentliste } from "@/components/segmentliste";
import { Fehler, Laedt, Leer } from "@/components/zustaende";

type Reiter = "heute" | "ueberfaellig" | "bevorstehend" | "alle" | "erledigt";

export default function AufgabenSeite() {
  const client = useQueryClient();
  const [reiter, setReiter] = useState<Reiter>("heute");
  const [tabelle, setTabelle] = useState(false);
  const [nurMeine, setNurMeine] = useState(false);

  // Schnellanlage: Titel und Art reichen. Wer erst ein Formular öffnen
  // muss, schreibt die Aufgabe auf einen Zettel.
  const [titel, setTitel] = useState("");
  const [art, setArt] = useState<AufgabenArt>("todo");
  const [faellig, setFaellig] = useState("");
  const [dealId, setDealId] = useState("");

  const uebersicht = useQuery({
    queryKey: ["aufgaben-uebersicht"],
    queryFn: () => api.get<Aufgabenuebersicht>("/api/tasks/uebersicht"),
  });

  const mitglieder = useQuery({
    queryKey: ["mitglieder"],
    queryFn: () => api.get<Mitglied[]>("/api/mitglieder"),
  });

  const deals = useQuery({
    queryKey: ["deals-auswahl"],
    queryFn: () => api.get<Deal[]>("/api/deals?status=open&limit=200"),
  });

  const parameter = suchparameter({
    status: reiter === "erledigt" ? "done" : "open",
    faellig: reiter === "alle" || reiter === "erledigt" ? "" : reiter,
    mein: nurMeine ? "true" : "",
  });

  const aufgaben = useQuery({
    enabled: !tabelle,
    queryKey: ["aufgaben", parameter],
    queryFn: () => api.get<Task[]>(`/api/tasks${parameter}`),
  });

  const frisch = () => {
    client.invalidateQueries({ queryKey: ["aufgaben"] });
    client.invalidateQueries({ queryKey: ["aufgaben-uebersicht"] });
    client.invalidateQueries({ queryKey: ["segment", "tasks"] });
  };

  const anlegen = useMutation({
    mutationFn: () =>
      api.post<Task>("/api/tasks", {
        title: titel,
        art,
        due_at: faellig ? `${faellig}T09:00:00` : null,
        deal_id: dealId || null,
        company_id: deals.data?.find((d) => d.id === dealId)?.company_id ?? null,
      }),
    onSuccess: () => {
      setTitel("");
      setFaellig("");
      setDealId("");
      frisch();
    },
  });

  const setzen = useMutation({
    mutationFn: ({ id, teil }: { id: string; teil: Record<string, unknown> }) =>
      api.patch<Task>(`/api/tasks/${id}`, teil),
    onSuccess: frisch,
  });

  const z = uebersicht.data;
  const REITER: { wert: Reiter; text: string; zahl?: number }[] = [
    { wert: "heute", text: "Heute fällig", zahl: z?.heute },
    { wert: "ueberfaellig", text: "Überfällig", zahl: z?.ueberfaellig },
    { wert: "bevorstehend", text: "Bevorstehend", zahl: z?.bevorstehend },
    { wert: "alle", text: "Alle offenen", zahl: z?.offen },
    { wert: "erledigt", text: "Erledigt" },
  ];

  return (
    <>
      <Seitenkopf
        titel="Aufgaben"
        zahl={z ? `${anzahlText(z.offen, "offene Aufgabe", "offene Aufgaben")}` : undefined}
      >
        {(mitglieder.data?.length ?? 0) > 1 && (
          <button
            type="button"
            className={`btn btn-klein ${nurMeine ? "btn-primaer" : "btn-sekundaer"}`}
            aria-pressed={nurMeine}
            onClick={() => setNurMeine((m) => !m)}
          >
            {nurMeine ? "Nur meine" : "Alle Personen"}
          </button>
        )}
        <button
          type="button"
          className={`btn btn-klein ${tabelle ? "btn-primaer" : "btn-sekundaer"}`}
          aria-pressed={tabelle}
          onClick={() => setTabelle((t) => !t)}
        >
          {tabelle ? "Tabelle" : "Liste"}
        </button>
      </Seitenkopf>

      {tabelle ? (
        <Segmentliste
          entity="tasks"
          basisPfad="/aufgaben"
          suchePlatzhalter="Titel oder Notiz"
          leerTitel="Keine Aufgabe gefunden"
          leerText="Entweder ist der Filter zu eng, oder es ist gerade nichts offen."
          stapelfelder={[
            { schluessel: "status", text: "Zustand" },
            { schluessel: "phase", text: "Phase" },
            { schluessel: "art", text: "Art" },
            { schluessel: "prioritaet", text: "Dringlichkeit" },
            { schluessel: "assigned_to", text: "Zugewiesen" },
          ]}
        />
      ) : (
        <>
          <div className="ansichtsleiste" role="tablist" aria-label="Ansichten">
            {REITER.map((r) => (
              <button
                key={r.wert}
                type="button"
                role="tab"
                aria-selected={reiter === r.wert}
                className={`ansicht-reiter${reiter === r.wert ? " aktiv" : ""}`}
                onClick={() => setReiter(r.wert)}
              >
                {r.text}
                {r.zahl !== undefined && r.zahl > 0 && (
                  <span
                    className="zahlpille"
                    data-warnung={r.wert === "ueberfaellig" ? "true" : undefined}
                  >
                    {r.zahl}
                  </span>
                )}
              </button>
            ))}
          </div>

          <div className="werkzeugleiste">
            <form
              style={{ display: "flex", gap: "var(--am-raum-2)", flex: "1 1 520px", flexWrap: "wrap" }}
              onSubmit={(e) => {
                e.preventDefault();
                if (titel.trim()) anlegen.mutate();
              }}
            >
              <input
                style={{ flex: "2 1 220px" }}
                value={titel}
                onChange={(e) => setTitel(e.target.value)}
                placeholder="Was ist zu tun?"
                aria-label="Neue Aufgabe"
              />
              <select
                style={{ flex: "0 0 130px" }}
                value={art}
                onChange={(e) => setArt(e.target.value as AufgabenArt)}
                aria-label="Art"
              >
                {Object.entries(AUFGABEN_ART_TEXT).map(([wert, text]) => (
                  <option key={wert} value={wert}>
                    {text}
                  </option>
                ))}
              </select>
              <input
                style={{ flex: "0 0 150px" }}
                type="date"
                value={faellig}
                onChange={(e) => setFaellig(e.target.value)}
                aria-label="Fällig am"
              />
              <select
                style={{ flex: "1 1 180px" }}
                value={dealId}
                onChange={(e) => setDealId(e.target.value)}
                aria-label="Geschäft"
              >
                <option value="">— ohne Geschäft —</option>
                {deals.data?.map((d) => (
                  <option key={d.id} value={d.id}>
                    {d.name}
                    {d.company_name ? ` · ${d.company_name}` : ""}
                  </option>
                ))}
              </select>
              <button type="submit" className="btn btn-primaer" disabled={!titel.trim() || anlegen.isPending}>
                Anlegen
              </button>
            </form>
          </div>

          {anlegen.isError && (
            <div style={{ padding: "0 var(--am-raum-8)" }}>
              <Fehler text={(anlegen.error as Error).message} />
            </div>
          )}

          <div className="liste">
            {aufgaben.isPending && <Laedt />}
            {aufgaben.isError && <Fehler text={(aufgaben.error as Error).message} />}
            {aufgaben.data?.length === 0 && (
              <Leer
                titel={reiter === "ueberfaellig" ? "Nichts liegengeblieben" : "Nichts zu tun"}
                text={
                  reiter === "heute"
                    ? "Für heute ist nichts eingetragen."
                    : "In diesem Zeitraum steht nichts an."
                }
              />
            )}
            {aufgaben.data?.map((a) => (
              <Aufgabenzeile
                key={a.id}
                aufgabe={a}
                laeuft={setzen.isPending}
                beiSetzen={(teil) => setzen.mutate({ id: a.id, teil })}
              />
            ))}
          </div>
        </>
      )}
    </>
  );
}

/** Eine Zeile: abhaken, Phase setzen, sehen worum es geht. */
function Aufgabenzeile({
  aufgabe,
  laeuft,
  beiSetzen,
}: {
  aufgabe: Task;
  laeuft: boolean;
  beiSetzen: (teil: Record<string, unknown>) => void;
}) {
  const erledigt = aufgabe.status === "done";
  const ueberfaellig =
    !erledigt && aufgabe.due_at && new Date(aufgabe.due_at) < new Date();

  return (
    <div className="aufgabe" data-erledigt={erledigt ? "true" : undefined}>
      <button
        type="button"
        className="aufgabe-haken"
        aria-label={erledigt ? "Wieder öffnen" : "Als erledigt abhaken"}
        disabled={laeuft}
        onClick={() => beiSetzen({ status: erledigt ? "open" : "done" })}
      >
        {erledigt ? <CheckCircle2 size={18} aria-hidden="true" /> : <Circle size={18} aria-hidden="true" />}
      </button>

      <div className="aufgabe-mitte">
        <div className="aufgabe-titel">{aufgabe.title}</div>
        <div className="aufgabe-zeile">
          <span>{AUFGABEN_ART_TEXT[aufgabe.art] ?? aufgabe.art}</span>
          {aufgabe.deal_id && (
            <Link href={`/deals/${aufgabe.deal_id}`} className="zellen-link">
              {aufgabe.deal_name}
            </Link>
          )}
          {aufgabe.ticket_id && (
            <Link href={`/tickets/${aufgabe.ticket_id}`} className="zellen-link">
              {aufgabe.ticket_betreff}
            </Link>
          )}
          {aufgabe.contact_id && (
            <Link href={`/kontakte/${aufgabe.contact_id}`} className="zellen-link">
              {aufgabe.kontakt_name?.trim() || "Kontakt"}
            </Link>
          )}
          {!aufgabe.deal_id && !aufgabe.ticket_id && !aufgabe.contact_id && aufgabe.company_name && (
            <span>{aufgabe.company_name}</span>
          )}
          {aufgabe.zustaendig_name && <span>{aufgabe.zustaendig_name}</span>}
        </div>
      </div>

      <Prioritaetspille prioritaet={aufgabe.prioritaet} />

      {!erledigt && (
        <select
          className="aufgabe-phase"
          value={aufgabe.phase}
          aria-label="Phase"
          disabled={laeuft}
          onChange={(e) => beiSetzen({ phase: e.target.value })}
        >
          {Object.entries(AUFGABEN_PHASE_TEXT).map(([wert, text]) => (
            <option key={wert} value={wert}>
              {text}
            </option>
          ))}
        </select>
      )}

      <span className="frist" data-ueberfaellig={ueberfaellig ? "true" : undefined}>
        {erledigt
          ? `erledigt ${datumZeit(aufgabe.completed_at)}`
          : aufgabe.due_at
            ? frist(aufgabe.due_at)
            : "ohne Frist"}
      </span>
    </div>
  );
}
