"use client";

import { useQuery } from "@tanstack/react-query";
import { use, useEffect, useState } from "react";
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
  // Welches Beacon? Auf dem Handy ist die Adresszeile abgeschnitten, und
  // ein Einladungslink von einer fremden Box sieht sonst aus wie einer von
  // der eigenen. Der Ursprung steht deshalb im Text.
  const [wo, setWo] = useState("");
  useEffect(() => {
    setWo(window.location.host);
  }, []);
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

  const { name, kennung, uebernahme } = einladung.data;

  return (
    <Tor
      // Die **Kennung** steht oben, nicht der Anzeigename. Sie entscheidet,
      // wessen Zugang hier eingerichtet wird; der Anzeigename ist nur ein
      // Etikett und kann auf eine ganz andere Person zeigen. Genau das ist
      // am 8. September passiert: „Willkommen, Kai" über der Kennung
      // `marc-bayer`, auf einer fremden Box.
      titel={uebernahme ? "Zugang zurücksetzen" : "Zugang einrichten"}
      unter={
        <>
          Für die Kennung <strong className="tor-kennung">{kennung}</strong>
          {name && name !== kennung ? <> ({name})</> : null} bei{" "}
          <strong className="tor-wo">{wo}</strong>.
          {uebernahme ? (
            <>
              {" "}Dieses Konto <strong>hat bereits ein Passwort</strong>. Wenn Sie
              fortfahren, wird es ersetzt und der bisherige Zugang gilt nicht mehr.
              Fahren Sie nur fort, wenn dieses Konto Ihres ist.
            </>
          ) : (
            <> Danach sind Sie angemeldet.</>
          )}
        </>
      }
      fehler={fehler}
      laeuft={laeuft}
      knopf={uebernahme ? "Passwort ersetzen" : "Zugang einrichten"}
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
