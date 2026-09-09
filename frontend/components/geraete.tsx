"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Laptop, Smartphone, Monitor } from "lucide-react";
import { api } from "@/lib/api";
import { lage } from "@/lib/anmeldung";
import { datumZeit } from "@/lib/format";
import type { Geraet } from "@/lib/typen";
import { Fehler, Laedt } from "@/components/zustaende";
import { Erklaerung } from "@/components/erklaerung";

/**
 * Wo bin ich überall angemeldet — und wie werde ich es wieder los.
 *
 * Eine Sitzung lebt dreißig Tage. Ohne diese Liste bliebe ein vergessener
 * Browser im Zug so lange offen, ohne dass es jemand sehen könnte. Was
 * hier steht, kommt aus der eigenen Zeile: kein Token, keine Adresse, nur
 * was beim Wiedererkennen hilft.
 */

/** Aus einer Browserkennung wird etwas, das ein Mensch wiedererkennt. */
export function geraetName(agent: string | null): string {
  const a = agent ?? "";
  if (!a) return "Unbekanntes Gerät";
  const browser =
    /Edg\//.test(a) ? "Edge"
    : /OPR\//.test(a) ? "Opera"
    : /Firefox\//.test(a) ? "Firefox"
    : /Chrome\//.test(a) ? "Chrome"
    : /Safari\//.test(a) ? "Safari"
    : "Browser";
  const system =
    /iPhone/.test(a) ? "iPhone"
    : /iPad/.test(a) ? "iPad"
    : /Android/.test(a) ? "Android"
    : /Mac OS X|Macintosh/.test(a) ? "Mac"
    : /Windows/.test(a) ? "Windows"
    : /Linux/.test(a) ? "Linux"
    : "";
  return system ? `${browser} auf ${system}` : browser;
}

function Zeichen({ agent }: { agent: string | null }) {
  const a = agent ?? "";
  if (/iPhone|Android/.test(a)) return <Smartphone size={16} aria-hidden="true" />;
  if (/iPad|Mac OS X|Macintosh/.test(a)) return <Laptop size={16} aria-hidden="true" />;
  return <Monitor size={16} aria-hidden="true" />;
}

export function Geraeteblock() {
  const client = useQueryClient();
  const stand = useQuery({ queryKey: ["anmeldelage"], queryFn: lage, staleTime: 60_000 });

  const geraete = useQuery({
    queryKey: ["geraete"],
    queryFn: () => api.get<Geraet[]>("/api/anmeldung/geraete"),
    enabled: Boolean(stand.data?.angemeldet),
  });

  const beenden = useMutation({
    mutationFn: (id: string) => api.del(`/api/anmeldung/geraete/${id}`),
    onSuccess: () => client.invalidateQueries({ queryKey: ["geraete"] }),
  });

  const alleAnderen = useMutation({
    mutationFn: () => api.post<{ beendet: number }>("/api/anmeldung/geraete/andere-beenden"),
    onSuccess: () => client.invalidateQueries({ queryKey: ["geraete"] }),
  });

  // Ohne eigene Anmeldung gibt es keine Sitzungen, die man beenden könnte —
  // dann prüft der Olares-Sidecar, und der Knopf wäre eine Attrappe.
  if (!stand.data?.angemeldet) return null;
  if (geraete.isPending) return <Laedt />;
  if (geraete.isError) return <Fehler text={(geraete.error as Error).message} />;

  const liste = geraete.data!;
  const andere = liste.filter((g) => !g.aktuell).length;

  return (
    <section className="block">
      <div className="block-kopf">
        <h2>Ihre Geräte</h2>
        {andere > 0 && (
          <button
            type="button"
            className="btn btn-still btn-klein"
            onClick={() => alleAnderen.mutate()}
            disabled={alleAnderen.isPending}
          >
            {alleAnderen.isPending ? "Meldet ab …" : `Andere abmelden (${andere})`}
          </button>
        )}
      </div>
      <div className="block-inhalt">
        <Erklaerung
          kurz="Wo Sie gerade angemeldet sind."
          lang={
            <>
              Eine Anmeldung gilt dreißig Tage, im Leerlauf sieben. Ein vergessener Browser
              stünde ohne diese Liste so lange offen, ohne dass es jemand sehen könnte.
              Abmelden wirkt sofort und auf dem Server — der Keks auf dem anderen Gerät ist
              danach wertlos, nicht bloß versteckt.
            </>
          }
        />

        <ul className="geraeteliste">
          {liste.map((g) => (
            <li key={g.id} className="geraet" data-aktuell={g.aktuell ? "true" : undefined}>
              <span className="geraet-zeichen" aria-hidden="true">
                <Zeichen agent={g.agent} />
              </span>
              <span className="geraet-text">
                <span className="geraet-name" title={g.agent ?? undefined}>
                  {geraetName(g.agent)}
                  {g.aktuell && <span className="geraet-jetzt">dieses Gerät</span>}
                </span>
                <span className="geraet-zeiten">
                  zuletzt {datumZeit(g.zuletzt_am)} · angemeldet seit {datumZeit(g.erstellt_am)}
                </span>
              </span>
              {!g.aktuell && (
                <button
                  type="button"
                  className="btn btn-still btn-klein"
                  aria-label={`${geraetName(g.agent)} abmelden`}
                  onClick={() => beenden.mutate(g.id)}
                  disabled={beenden.isPending}
                >
                  Abmelden
                </button>
              )}
            </li>
          ))}
        </ul>

        {beenden.isError && <Fehler text={(beenden.error as Error).message} />}
        {alleAnderen.isError && <Fehler text={(alleAnderen.error as Error).message} />}
      </div>
    </section>
  );
}
