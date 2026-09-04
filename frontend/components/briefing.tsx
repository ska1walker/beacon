"use client";

import { useMutation, useQuery } from "@tanstack/react-query";
import { AlertTriangle, Clock, FileClock, Inbox, MessageSquareOff, Sparkles, Target } from "lucide-react";
import Link from "next/link";
import { api } from "@/lib/api";
import { anzahl, euro } from "@/lib/format";
import type { Briefing, KIStatus, Posten } from "@/lib/typen";
import { Fehler, Laedt } from "@/components/zustaende";

const GRUPPEN: {
  schluessel: keyof Briefing;
  titel: string;
  Zeichen: typeof Clock;
  erklaerung: string;
}[] = [
  {
    schluessel: "faellige_aufgaben",
    titel: "Fällig",
    Zeichen: Clock,
    erklaerung: "Aufgaben, deren Frist heute oder früher lag.",
  },
  {
    schluessel: "ueberfaellige_geschaefte",
    titel: "Abschlussdatum verstrichen",
    Zeichen: AlertTriangle,
    erklaerung: "Offene Leads, deren geplanter Abschluss vorbei ist.",
  },
  {
    schluessel: "ablaufende_angebote",
    titel: "Bindefrist läuft ab",
    Zeichen: FileClock,
    erklaerung: "Verschickte Angebote, deren Frist in den nächsten sieben Tagen endet.",
  },
  {
    schluessel: "verstummte_geschaefte",
    titel: "Seit Wochen still",
    Zeichen: MessageSquareOff,
    erklaerung: "Offene Leads, bei denen seit über drei Wochen nichts passiert ist.",
  },
  {
    schluessel: "offener_eingang",
    titel: "Im Eingang",
    Zeichen: Inbox,
    erklaerung: "Protokolle und Post, die noch niemandem zugeordnet sind.",
  },
  {
    schluessel: "ohne_naechsten_schritt",
    titel: "Ohne nächsten Schritt",
    Zeichen: Target,
    erklaerung: "Fortgeschrittene Leads, bei denen nicht steht, was als Nächstes kommt.",
  },
];

function PostenZeile({ p }: { p: Posten }) {
  const ziel = p.deal_id ? `/deals/${p.deal_id}` : p.company_id ? `/firmen/${p.company_id}` : p.art === "eingang" ? "/eingang" : null;
  const inhalt = (
    <>
      <span className="haupt">{p.titel}</span>
      {p.hinweis && <span className="briefing-hinweis">{p.hinweis}</span>}
      {p.betrag_cents ? <span className="briefing-betrag">{euro(p.betrag_cents)}</span> : null}
    </>
  );
  return (
    <li className="briefing-zeile">
      {ziel ? (
        <Link href={ziel} className="briefing-link">
          {inhalt}
        </Link>
      ) : (
        <span className="briefing-link">{inhalt}</span>
      )}
    </li>
  );
}

export function Tagesbriefing() {
  const abfrage = useQuery({
    queryKey: ["briefing"],
    queryFn: () => api.get<Briefing>("/api/briefing"),
  });

  const kiStatus = useQuery({
    queryKey: ["ki-status"],
    queryFn: () => api.get<KIStatus>("/api/ki/status"),
    staleTime: 5 * 60_000,
  });

  const text = useMutation({
    mutationFn: () => api.post<{ text: string; modell: string }>("/api/briefing/text"),
  });

  if (abfrage.isPending) return <Laedt />;
  if (abfrage.isError) return <Fehler text={(abfrage.error as Error).message} />;

  const b = abfrage.data!;
  const bereit = kiStatus.data?.ready ?? false;

  if (b.gesamt === 0) {
    return (
      <section className="block">
        <div className="block-kopf">
          <h2>Heute</h2>
        </div>
        <div className="block-inhalt">
          <p style={{ fontSize: "0.875rem", color: "var(--am-text-sekundaer)" }}>
            Nichts liegt an. Ein guter Tag, um jemanden anzurufen.
          </p>
        </div>
      </section>
    );
  }

  return (
    <section className="block">
      <div className="block-kopf">
        <h2>Heute — {anzahl(b.gesamt, "Punkt", "Punkte")}</h2>
        <button
          type="button"
          className="btn btn-still btn-klein"
          onClick={() => text.mutate()}
          disabled={!bereit || text.isPending}
          title={bereit ? undefined : kiStatus.data?.hint}
        >
          <Sparkles size={14} aria-hidden="true" />
          {text.isPending ? "Ordnet …" : "Reihenfolge vorschlagen"}
        </button>
      </div>

      <div className="block-inhalt">
        {text.isError && <Fehler text={(text.error as Error).message} />}
        {text.data && (
          <div className="ki-block" style={{ marginBottom: "var(--am-raum-6)" }}>
            <div className="ki-block-kopf">
              <Sparkles size={11} aria-hidden="true" /> Vorschlag zur Reihenfolge
            </div>
            <p className="ki-block-text">{text.data.text}</p>
          </div>
        )}

        {GRUPPEN.map(({ schluessel, titel, Zeichen, erklaerung }) => {
          const posten = b[schluessel] as Posten[];
          if (!posten?.length) return null;
          return (
            <div key={schluessel} className="briefing-gruppe">
              <h3 className="briefing-titel">
                <Zeichen size={14} aria-hidden="true" />
                {titel}
                <span className="board-spalte-anzahl">{posten.length}</span>
              </h3>
              <p className="briefing-erklaerung">{erklaerung}</p>
              <ul className="briefing-liste">
                {posten.map((p, i) => (
                  <PostenZeile key={`${schluessel}-${i}`} p={p} />
                ))}
              </ul>
            </div>
          );
        })}
      </div>
    </section>
  );
}
