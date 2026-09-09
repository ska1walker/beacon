"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";
import { ApiFehler } from "@/lib/api";
import { anmelden, zielPfad } from "@/lib/anmeldung";
import { Tor } from "@/components/tor";

function Maske() {
  const router = useRouter();
  const parameter = useSearchParams();
  const [name, setName] = useState("");
  const [passwort, setPasswort] = useState("");
  const [fehler, setFehler] = useState<string | null>(null);
  const [laeuft, setLaeuft] = useState(false);

  async function senden() {
    setFehler(null);
    setLaeuft(true);
    try {
      await anmelden(name.trim(), passwort);
      // Harter Wechsel statt `router.push`: Der Keks ist neu, und jede
      // zwischengespeicherte Antwort aus der Zeit davor ist eine Antwort
      // für jemand anderen.
      window.location.assign(zielPfad(parameter.get("weiter")));
    } catch (e) {
      const f = e as ApiFehler;
      setFehler(
        f.status === 429
          ? "Zu viele Versuche. Bitte warten Sie eine Viertelstunde."
          : "Name oder Passwort stimmt nicht.",
      );
      setPasswort("");
      setLaeuft(false);
    }
  }

  return (
    <Tor
      titel="Anmelden"
      unter="Bitte melden Sie sich an, um mit Ihrem Bestand zu arbeiten."
      fehler={fehler}
      laeuft={laeuft}
      knopf="Anmelden"
      onSenden={senden}
      fuss={
        <>
          <Link href="/passwort-vergessen">Passwort vergessen?</Link>
          <br />
          Noch kein Zugang? Der Eigentümer erzeugt Ihnen einen Einladungslink.
        </>
      }
    >
      <div className="feld">
        <label htmlFor="tor-name">Name</label>
        <input
          id="tor-name"
          className="input"
          value={name}
          onChange={(e) => setName(e.target.value)}
          autoComplete="username"
          autoCapitalize="none"
          spellCheck={false}
          required
          autoFocus
        />
      </div>
      <div className="feld">
        <label htmlFor="tor-passwort">Passwort</label>
        <input
          id="tor-passwort"
          className="input"
          type="password"
          value={passwort}
          onChange={(e) => setPasswort(e.target.value)}
          autoComplete="current-password"
          required
        />
      </div>
    </Tor>
  );
}

export default function AnmeldeSeite() {
  // `useSearchParams` verlangt eine Grenze, sonst rendert Next die ganze
  // Seite zur Anfragezeit statt beim Bauen.
  return (
    <Suspense fallback={null}>
      <Maske />
    </Suspense>
  );
}
