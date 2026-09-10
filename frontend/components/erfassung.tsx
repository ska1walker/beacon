"use client";

import { useMutation } from "@tanstack/react-query";
import { ClipboardPaste, ImageUp, Sparkles, X } from "lucide-react";
import Link from "next/link";
import { useRef, useState } from "react";
import { api } from "@/lib/api";
import type { Erfassungsvorschlag } from "@/lib/typen";
import { Fehler } from "@/components/zustaende";

const MAX_BYTES = 6 * 1024 * 1024;
const TYPEN = ["image/png", "image/jpeg", "image/webp", "image/gif"];

/**
 * Hineinwerfen, was da ist — und die Maske füllt sich.
 *
 * Der Weg, auf dem Kontakte wirklich ins CRM kommen, ist keine Maske mit
 * vierzehn Feldern. Es ist eine E-Mail-Signatur in der Zwischenablage,
 * ein abfotografiertes Visitenkärtchen, drei Zeilen aus einem
 * Messeprotokoll. Wer das abtippen muss, tippt es nicht ab.
 *
 * Zwei Dinge entscheiden, ob sich das gut anfühlt:
 *
 * - **Einfügen ist der Hauptweg, nicht der Dateiauswähler.** Wer einen
 *   Ausschnitt macht, hat ihn in der Zwischenablage, nicht auf der
 *   Platte. Strg+V im Feld genügt darum, für Text wie für Bild.
 * - **Gefüllt wird, nicht gespeichert.** Das Ergebnis steht danach in
 *   der Maske und lässt sich ändern. Anlegen drückt ein Mensch.
 */
export function Erfassung({
  art,
  beiErgebnis,
}: {
  art: "contact" | "company";
  beiErgebnis: (v: Erfassungsvorschlag) => void;
}) {
  const [text, setText] = useState("");
  const [bild, setBild] = useState<{ datei: File; url: string } | null>(null);
  const [ueber, setUeber] = useState(false);
  const [hinweis, setHinweis] = useState<string | null>(null);
  const [gelesen, setGelesen] = useState<Erfassungsvorschlag | null>(null);
  const dateiwahl = useRef<HTMLInputElement>(null);

  function nimm(datei: File | null | undefined) {
    if (!datei) return;
    if (!TYPEN.includes(datei.type)) {
      return setHinweis("Das lässt sich nicht lesen. PNG, JPEG, WebP oder GIF.");
    }
    if (datei.size > MAX_BYTES) {
      return setHinweis("Das Bild ist größer als 6 MB. Ein Ausschnitt genügt meist.");
    }
    setHinweis(null);
    setBild((alt) => {
      if (alt) URL.revokeObjectURL(alt.url);
      return { datei, url: URL.createObjectURL(datei) };
    });
  }

  const lesen = useMutation({
    mutationFn: async () => {
      if (bild) {
        const f = new FormData();
        f.append("art", art);
        f.append("text", text);
        f.append("datei", bild.datei);
        return api.postForm<Erfassungsvorschlag>("/api/erfassen/bild", f);
      }
      return api.post<Erfassungsvorschlag>("/api/erfassen/text", { art, text });
    },
    onSuccess: (v) => {
      setGelesen(v);
      beiErgebnis(v);
    },
  });

  const bereit = text.trim().length >= 3 || bild !== null;

  return (
    <div className="erfassung">
      <div className="erfassung-kopf">
        <Sparkles size={14} aria-hidden="true" />
        <span>
          {art === "contact"
            ? "Signatur, Visitenkarte oder Notiz hineinwerfen"
            : "Impressum, Briefkopf oder Notiz hineinwerfen"}
        </span>
      </div>

      {/* eslint-disable-next-line jsx-a11y/no-static-element-interactions */}
      <div
        className="erfassung-wurf"
        data-ueber={ueber ? "true" : undefined}
        onDragOver={(e) => {
          e.preventDefault();
          setUeber(true);
        }}
        onDragLeave={() => setUeber(false)}
        onDrop={(e) => {
          e.preventDefault();
          setUeber(false);
          nimm(e.dataTransfer.files?.[0]);
        }}
      >
        <textarea
          rows={3}
          value={text}
          aria-label="Hingeworfene Angaben"
          placeholder={
            art === "contact"
              ? "Dr. Julia Ahrend\nPartnerin | Hanseatic Legal Partner mbB\nT +49 40 555 0199 · ahrend@hanseatic-legal.de"
              : "Nordwind Logistik GmbH · Bremen · nordwind-logistik.de"
          }
          onChange={(e) => setText(e.target.value)}
          onPaste={(e) => {
            // Ein Bild in der Zwischenablage geht vor: Wer einen
            // Ausschnitt gemacht hat, will ihn hier ablegen, nicht seinen
            // Dateinamen tippen.
            const datei = [...e.clipboardData.items]
              .find((i) => i.kind === "file")
              ?.getAsFile();
            if (datei) {
              e.preventDefault();
              nimm(datei);
            }
          }}
        />

        {bild && (
          <div className="erfassung-bild">
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img src={bild.url} alt="Eingefügtes Bild" />
            <button
              type="button"
              aria-label="Bild entfernen"
              onClick={() => {
                URL.revokeObjectURL(bild.url);
                setBild(null);
              }}
            >
              <X size={12} aria-hidden="true" />
            </button>
          </div>
        )}
      </div>

      <div className="erfassung-leiste">
        <button
          type="button"
          className="btn btn-still btn-klein"
          onClick={() => dateiwahl.current?.click()}
        >
          <ImageUp size={14} aria-hidden="true" />
          Bild wählen
        </button>
        <span className="erfassung-tipp">
          <ClipboardPaste size={12} aria-hidden="true" />
          Ein Bildschirmausschnitt lässt sich direkt einfügen
        </span>
        <span style={{ flex: 1 }} />
        <button
          type="button"
          className="btn btn-sekundaer btn-klein"
          disabled={!bereit || lesen.isPending}
          onClick={() => lesen.mutate()}
        >
          {lesen.isPending ? "Liest …" : "Auslesen"}
        </button>
      </div>

      <input
        ref={dateiwahl}
        type="file"
        accept={TYPEN.join(",")}
        hidden
        onChange={(e) => nimm(e.target.files?.[0])}
      />

      {hinweis && <p className="erfassung-hinweis warnung">{hinweis}</p>}
      {lesen.isError && <Fehler text={(lesen.error as Error).message} />}

      {gelesen && !lesen.isPending && (
        <div className="erfassung-ergebnis">
          <p className="erfassung-hinweis">
            {Object.keys(gelesen.felder).length === 1
              ? "Ein Feld gefüllt"
              : `${Object.keys(gelesen.felder).length} Felder gefüllt`}{" "}
            · gelesen von <span className="mono">{gelesen.modell}</span>. Bitte nachsehen,
            bevor Sie anlegen.
          </p>
          {gelesen.rest && (
            <p className="erfassung-hinweis">
              Passte in kein Feld: <em>{gelesen.rest}</em>
            </p>
          )}
          {gelesen.dublette && <Dublettenwarnung art={gelesen.art} d={gelesen.dublette} />}
        </div>
      )}
    </div>
  );
}

/** Den gibt es vielleicht schon — bevor der dritte Meyer im Bestand steht. */
function Dublettenwarnung({
  art,
  d,
}: {
  art: "contact" | "company";
  d: Record<string, string | null>;
}) {
  const name =
    art === "contact"
      ? [d.first_name, d.last_name].filter(Boolean).join(" ") || d.email || "Kontakt"
      : d.name || d.domain || "Firma";
  const pfad = art === "contact" ? "/kontakte" : "/firmen";

  return (
    <p className="erfassung-hinweis warnung">
      Gibt es womöglich schon: <Link href={`${pfad}/${d.id}`}>{name}</Link> ({d.grund}). Anlegen
      geht trotzdem — nur wissen Sie es jetzt.
    </p>
  );
}
