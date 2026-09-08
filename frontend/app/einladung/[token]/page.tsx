"use client";

import { useQuery } from "@tanstack/react-query";
import { use, useState } from "react";
import { ApiFehler } from "@/lib/api";
import { einladungEinloesen, einladungLesen } from "@/lib/anmeldung";
import { Tor } from "@/components/tor";

const MINDESTENS = 12;

export default function EinladungsSeite({
  params,
}: {
  params: Promise<{ token: string }>;
}) {
  const { token } = use(params);
  const [passwort, setPasswort] = useState("");
  const [wiederholung, setWiederholung] = useState("");
  const [fehler, setFehler] = useState<string | null>(null);
  const [laeuft, setLaeuft] = useState(false);

  const einladung = useQuery({
    queryKey: ["einladung", token],
    queryFn: () => einladungLesen(token),
    retry: false,
  });

  async function senden() {
    setFehler(null);
    if (passwort.length < MINDESTENS) {
      setFehler(`Das Passwort muss mindestens ${MINDESTENS} Zeichen haben.`);
      return;
    }
    if (passwort !== wiederholung) {
      setFehler("Die beiden Eingaben sind nicht gleich.");
      return;
    }
    setLaeuft(true);
    try {
      await einladungEinloesen(token, passwort);
      // Das Einlösen meldet gleich an — der Keks ist gesetzt.
      window.location.assign("/");
    } catch (e) {
      const f = e as ApiFehler;
      setFehler(
        f.status === 404
          ? "Diese Einladung gilt nicht mehr. Bitten Sie um einen neuen Link."
          : f.message,
      );
      setLaeuft(false);
    }
  }

  if (einladung.isPending) {
    return <Tor titel="Einladung" knopf="Zugang einrichten" laeuft onSenden={() => {}}>{null}</Tor>;
  }

  if (einladung.isError) {
    return (
      <Tor
        titel="Einladung"
        unter="Dieser Link gilt nicht mehr. Einladungen laufen ab und gelten genau einmal."
        knopf="Zur Anmeldung"
        onSenden={() => window.location.assign("/anmelden")}
      >
        {null}
      </Tor>
    );
  }

  return (
    <Tor
      titel={`Willkommen, ${einladung.data.name}`}
      unter={
        <>
          Setzen Sie ein Passwort für die Kennung <strong>{einladung.data.kennung}</strong>.
          Danach sind Sie angemeldet.
        </>
      }
      fehler={fehler}
      laeuft={laeuft}
      knopf="Zugang einrichten"
      onSenden={senden}
      fuss={`Mindestens ${MINDESTENS} Zeichen. Eine lange Wortfolge ist besser als kurze Sonderzeichen.`}
    >
      <div className="feld">
        <label htmlFor="ein-passwort">Passwort</label>
        <input
          id="ein-passwort"
          className="input"
          type="password"
          value={passwort}
          onChange={(e) => setPasswort(e.target.value)}
          autoComplete="new-password"
          required
          autoFocus
        />
      </div>
      <div className="feld">
        <label htmlFor="ein-wieder">Noch einmal</label>
        <input
          id="ein-wieder"
          className="input"
          type="password"
          value={wiederholung}
          onChange={(e) => setWiederholung(e.target.value)}
          autoComplete="new-password"
          required
        />
      </div>
    </Tor>
  );
}
