"use client";

import { useQuery } from "@tanstack/react-query";
import { ArrowLeft, Printer } from "lucide-react";
import Link from "next/link";
import { use } from "react";
import { api } from "@/lib/api";
import { datum, euroGenau } from "@/lib/format";
import type { OrgSettings, Quote } from "@/lib/typen";
import { Fehler, Laedt } from "@/components/zustaende";

/**
 * Die Fassung, die beim Kunden landet.
 *
 * Sie liegt bewusst auf einer eigenen Seite statt in einem Dialog: Ein
 * Druck aus einem Aufklapper heraus nimmt die halbe Anwendung mit aufs
 * Papier. Hier steht nur das Dokument, und `@media print` blendet die
 * Bedienleiste aus.
 */
export default function DruckSeite({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);

  const angebot = useQuery({
    queryKey: ["angebot", id],
    queryFn: () => api.get<Quote>(`/api/quotes/${id}`),
  });

  const einstellungen = useQuery({
    queryKey: ["einstellungen"],
    queryFn: () => api.get<OrgSettings>("/api/settings"),
  });

  if (angebot.isPending || einstellungen.isPending) return <Laedt />;
  if (angebot.isError) return <Fehler text={(angebot.error as Error).message} />;

  const q = angebot.data!;
  const a = einstellungen.data!;
  const e = q.empfaenger;

  const absenderZeile = [a.absender_name, a.absender_strasse, `${a.absender_plz ?? ""} ${a.absender_ort ?? ""}`.trim()]
    .filter(Boolean)
    .join(" · ");

  return (
    <div className="druck-seite">
      <div className="druck-leiste">
        <Link href={`/angebote/${id}`} className="btn btn-still btn-klein">
          <ArrowLeft size={14} aria-hidden="true" />
          Zurück
        </Link>
        <button type="button" className="btn btn-primaer btn-klein" onClick={() => window.print()}>
          <Printer size={14} aria-hidden="true" />
          Drucken
        </button>
      </div>

      {!a.absender_name && (
        <div className="hinweis" data-art="achtung" style={{ marginBottom: "var(--am-raum-6)" }}>
          <span>
            Es sind keine Absenderangaben hinterlegt. Ohne sie ist dieses Blatt kein
            versandfähiges Angebot — Name, Anschrift, Vertretung und Umsatzsteuer-Nummer
            stehen unter <Link href="/einstellungen">Einstellungen</Link>.
          </span>
        </div>
      )}

      <article className="dokument">
        <header className="dokument-kopf">
          <div className="dokument-marke">
            <span className="marke-punkt" aria-hidden="true" />
            <span>{a.absender_name ?? "Absender fehlt"}</span>
          </div>
        </header>

        {absenderZeile && <p className="dokument-absenderzeile">{absenderZeile}</p>}

        <address className="dokument-empfaenger">
          {e?.name ?? "Empfänger fehlt"}
          {e?.ansprechpartner && (
            <>
              <br />
              {e.ansprechpartner}
            </>
          )}
          {e?.street && (
            <>
              <br />
              {e.street}
            </>
          )}
          {(e?.postal_code || e?.city) && (
            <>
              <br />
              {[e.postal_code, e.city].filter(Boolean).join(" ")}
            </>
          )}
        </address>

        <div className="dokument-meta">
          <div>
            <span>Angebotsnummer</span>
            <strong className="mono">{q.number}</strong>
          </div>
          <div>
            <span>Datum</span>
            <strong>{datum(q.created_at)}</strong>
          </div>
          {q.valid_until && (
            <div>
              <span>Gültig bis</span>
              <strong>{datum(q.valid_until)}</strong>
            </div>
          )}
        </div>

        <h1 className="dokument-titel">{q.title}</h1>

        {q.intro_text && <p className="dokument-text">{q.intro_text}</p>}

        <table className="dokument-tabelle">
          <thead>
            <tr>
              <th style={{ width: "2rem" }}>Pos.</th>
              <th>Leistung</th>
              <th style={{ textAlign: "right", width: "4rem" }}>Menge</th>
              <th style={{ textAlign: "right", width: "7rem" }}>Einzelpreis</th>
              <th style={{ textAlign: "right", width: "7rem" }}>Betrag</th>
            </tr>
          </thead>
          <tbody>
            {q.items.map((i, index) => (
              <tr key={i.id}>
                <td className="mono">{index + 1}</td>
                <td>
                  <strong>{i.title}</strong>
                  {i.description && <div className="dokument-zeilentext">{i.description}</div>}
                  {i.discount_percent > 0 && (
                    <div className="dokument-zeilentext">Nachlass {i.discount_percent} %</div>
                  )}
                </td>
                <td className="am-zahl">{i.quantity}</td>
                <td className="am-zahl">{euroGenau(i.unit_price_cents)}</td>
                <td className="am-zahl">{euroGenau(i.line_total_cents)}</td>
              </tr>
            ))}
          </tbody>
        </table>

        <table className="dokument-summe">
          <tbody>
            <tr>
              <td>Nettobetrag</td>
              <td className="am-zahl">{euroGenau(q.net_cents)}</td>
            </tr>
            {q.discount_total_cents > 0 && (
              <tr>
                <td>Nachlass</td>
                <td className="am-zahl">− {euroGenau(q.discount_total_cents)}</td>
              </tr>
            )}
            <tr>
              <td>Umsatzsteuer {Math.round(q.tax_rate * 100)} %</td>
              <td className="am-zahl">{euroGenau(q.tax_cents)}</td>
            </tr>
            <tr className="dokument-summe-gesamt">
              <td>Gesamtbetrag</td>
              <td className="am-zahl">{euroGenau(q.gross_cents)}</td>
            </tr>
          </tbody>
        </table>

        {(q.terms_text || a.standard_bedingungen) && (
          <section className="dokument-bedingungen">
            <h2>Bedingungen</h2>
            <p className="dokument-text">{q.terms_text ?? a.standard_bedingungen}</p>
          </section>
        )}

        <footer className="dokument-fuss">
          <div>
            {a.absender_name}
            {a.absender_strasse && <br />}
            {a.absender_strasse}
            {(a.absender_plz || a.absender_ort) && <br />}
            {[a.absender_plz, a.absender_ort].filter(Boolean).join(" ")}
          </div>
          <div>
            {a.absender_telefon && (
              <>
                {a.absender_telefon}
                <br />
              </>
            )}
            {a.absender_email}
            {a.absender_website && <br />}
            {a.absender_website}
          </div>
          <div>
            {a.vertretung && (
              <>
                Vertreten durch {a.vertretung}
                <br />
              </>
            )}
            {a.registergericht}
            {a.ust_id && <br />}
            {a.ust_id && `USt-IdNr. ${a.ust_id}`}
          </div>
          <div>
            {a.bank_name}
            {a.bank_iban && <br />}
            {a.bank_iban}
          </div>
        </footer>
      </article>
    </div>
  );
}
