"use client";

import { useMutation, useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { Sparkles } from "lucide-react";
import { use, useState } from "react";
import { api } from "@/lib/api";
import { datum, personName } from "@/lib/format";
import type { Activity, Contact, KIErgebnis, KIStatus } from "@/lib/typen";
import { Seitenkopf } from "@/components/seitenkopf";
import { Stufenpille } from "@/components/stufe";
import { Zeitleiste } from "@/components/zeitleiste";
import { Fehler, Laedt } from "@/components/zustaende";
import { Eigenschaftswerteblock } from "@/components/eigenschaften";
import { Stammdaten } from "@/components/stammdaten";
import { KontaktFirmen } from "@/components/kontakt-firmen";
import { STUFEN_TEXT } from "@/lib/format";

/** Entwurf für eine Ansprache. Er wird hingelegt, nie versendet. */
function Entwurfsblock({ kontaktId }: { kontaktId: string }) {
  const [anlass, setAnlass] = useState("");

  const status = useQuery({
    queryKey: ["ki-status"],
    queryFn: () => api.get<KIStatus>("/api/ki/status"),
    staleTime: 5 * 60_000,
  });

  const entwurf = useMutation({
    mutationFn: () =>
      api.post<KIErgebnis>("/api/ki/entwurf", { contact_id: kontaktId, anlass, kanal: "email" }),
    onSuccess: (e) => setText(e.text),
  });
  const [text, setText] = useState("");
  const [betreff, setBetreff] = useState("");
  // Die letzte eingegangene Mail dieses Kontakts — der häufigste Anlass
  // für einen Entwurf ist eine Antwort, nicht ein Kaltstart.
  const letzteMail = useQuery({
    queryKey: ["aktivitaeten", { contact_id: kontaktId }],
    queryFn: () => api.get<Activity[]>(`/api/activities?contact_id=${kontaktId}`),
    select: (liste) => liste.find((a) => a.kind === "email" && a.payload?.richtung === "eingehend") ?? null,
  });
  const post = useQuery({ queryKey: ["post-status"], queryFn: () => api.get<{ eingerichtet: boolean; hinweis: string | null }>("/api/post/status") });
  const senden = useMutation({
    mutationFn: () => api.post("/api/post/senden", { contact_id: kontaktId, subject: betreff || anlass, text }),
    onSuccess: () => { setText(""); setBetreff(""); },
  });

  const bereit = status.data?.ready ?? false;

  return (
    <section className="block">
      <div className="block-kopf">
        <h2>Ansprache entwerfen</h2>
      </div>
      <div className="block-inhalt">
        {!bereit && status.data?.hint && (
          <div className="hinweis" data-art="achtung">
            <span>{status.data.hint}</span>
          </div>
        )}

        <div className="feld" style={{ marginTop: bereit ? 0 : "var(--am-raum-4)" }}>
          <label htmlFor="anlass">Anlass</label>
          <input
            id="anlass"
            value={anlass}
            onChange={(e) => setAnlass(e.target.value)}
            placeholder="Nach der Messe nachfassen"
            disabled={!bereit}
          />
        </div>

        {letzteMail.data && (
          <button
            type="button"
            className="btn btn-still btn-klein"
            style={{ marginBottom: "var(--am-raum-2)" }}
            onClick={() => {
              const m = letzteMail.data!;
              setAnlass(`Antwort auf „${(m.subject ?? "").replace(/^Von [^:]+: /, "")}“: ${(m.body ?? "").slice(0, 400)}`);
              setBetreff(`AW: ${(m.subject ?? "").replace(/^Von [^:]+: /, "")}`);
            }}
          >
            Auf letzte Mail antworten
          </button>
        )}
        <button
          type="button"
          className="btn btn-sekundaer btn-klein"
          disabled={!bereit || !anlass.trim() || entwurf.isPending}
          onClick={() => entwurf.mutate()}
        >
          <Sparkles size={14} aria-hidden="true" />
          {entwurf.isPending ? "Schreibt …" : "Entwurf erzeugen"}
        </button>

        {entwurf.isError && <Fehler text={(entwurf.error as Error).message} />}

        {(entwurf.data || text) && (
          <div className="ki-block" style={{ marginTop: "var(--am-raum-4)" }}>
            <div className="ki-block-kopf">Entwurf{entwurf.data ? ` · ${entwurf.data.model}` : ""} — ein Mensch schickt</div>
            <div className="feld"><label htmlFor="mail-betreff">Betreff</label><input id="mail-betreff" value={betreff} onChange={(e) => setBetreff(e.target.value)} placeholder={anlass} /></div>
            <div className="notiz-feld"><textarea rows={8} value={text} onChange={(e) => setText(e.target.value)} aria-label="Nachricht" /></div>
            {senden.isError && <Fehler text={(senden.error as Error).message} />}
            {senden.isSuccess && <p style={{ fontSize: "0.8125rem", color: "var(--am-erfolg)" }}>Übergeben — steht im Verlauf.</p>}
            <div className="btn-reihe" style={{ marginTop: "var(--am-raum-3)" }}>
              <button type="button" className="btn btn-primaer btn-klein" disabled={!post.data?.eingerichtet || !text.trim() || senden.isPending} title={post.data?.hinweis ?? undefined} onClick={() => senden.mutate()}>
                {senden.isPending ? "Übergibt …" : "Senden"}
              </button>
              <button type="button" className="btn btn-still btn-klein" onClick={() => navigator.clipboard.writeText(text)}>In die Zwischenablage</button>
            </div>
            {!post.data?.eingerichtet && post.data?.hinweis && <p style={{ fontSize: "0.75rem", color: "var(--am-text-gedaempft)", marginTop: "var(--am-raum-2)" }}>{post.data.hinweis}</p>}
          </div>
        )}
      </div>
    </section>
  );
}

export default function KontaktSeite({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);

  const kontakt = useQuery({
    queryKey: ["kontakt", id],
    queryFn: () => api.get<Contact>(`/api/contacts/${id}`),
  });

  if (kontakt.isPending) return <Laedt />;
  if (kontakt.isError) return <Fehler text={(kontakt.error as Error).message} />;

  const k = kontakt.data!;

  return (
    <>
      <Seitenkopf
        titel={personName(k.first_name, k.last_name)}
        zahl={[k.job_title, k.company_name].filter(Boolean).join(" · ") || undefined}
        pfad={{ text: "← Kontakte", href: "/kontakte" }}
      />

      <div className="datensatz">
        <div>
          <Stammdaten
            titel="Über diesen Kontakt"
            pfad={`/api/contacts/${id}`}
            abfrageSchluessel={["kontakt", id]}
            zurueckNach="/kontakte"
            loeschtext="Der Kontakt wird aus allen Listen genommen. Verlauf und Zuordnungen bleiben 30 Tage wiederherstellbar."
            kopfrechts={<Stufenpille stufe={k.lifecycle_stage} />}
            werte={k as unknown as Record<string, unknown>}
            felder={[
              { key: "first_name", text: "Vorname" },
              { key: "last_name", text: "Nachname" },
              { key: "email", text: "E-Mail", art: "email", zeige: (v) => <a href={`mailto:${String(v)}`}>{String(v)}</a> },
              { key: "phone", text: "Telefon" },
              { key: "mobile", text: "Mobil" },
              { key: "job_title", text: "Position" },
              { key: "buying_role", text: "Kaufrolle" },
              { key: "lifecycle_stage", text: "Stufe", art: "select", optionen: Object.entries(STUFEN_TEXT).map(([wert, text]) => ({ wert, text })) },
              { key: "source", text: "Herkunft" },
              { key: "linkedin_url", text: "LinkedIn" },
              { key: "notes", text: "Notizen", art: "textarea" },
            ]}
          />

          <KontaktFirmen kontaktId={id} />

          <Eigenschaftswerteblock entity="contacts" id={id} werte={k.custom} abfrageSchluessel={["kontakt", id]} />
        </div>

        <Zeitleiste bezug={{ contact_id: id }} />

        <div>
          <Entwurfsblock kontaktId={id} />
        </div>
      </div>
    </>
  );
}
