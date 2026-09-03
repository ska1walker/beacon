"use client";

/**
 * Hell / Dunkel / Wie das System.
 *
 * Der Dunkelmodus des AImighty-Systems ist kein Farbfilter, sondern eine
 * eigene Rollenverteilung: im Hellmodus handelt Hanseatenblau und Gold
 * zeichnet aus, im Dunkelmodus handelt Gold — „Blau auf Blau trägt nicht"
 * ist die dokumentierte Ausnahme. Beides steckt in den Token; hier wird
 * nur die Klasse `dunkel` am <html> gesetzt.
 *
 * Ein Cookie, keine Server-Persistenz: Die Wahl ist gerätebezogen sinnvoll
 * — am Schreibtisch hell, abends am Telefon dunkel — und hat im
 * Benutzerkonto nichts verloren.
 */

import { Monitor, Moon, Sun } from "lucide-react";
import { useEffect, useState } from "react";

export const DARSTELLUNG_COOKIE = "aicrm-darstellung";

export type Darstellung = "hell" | "dunkel" | "system";

/**
 * Läuft als Inline-Script vor dem ersten Anstrich (siehe layout.tsx).
 * Ohne das blitzt bei dunkler Einstellung kurz die helle Fläche auf.
 * Bewusst als String und ohne Abhängigkeiten — er läuft, bevor React da ist.
 */
export const DARSTELLUNG_SCRIPT = `
(function () {
  try {
    var m = document.cookie.match(/(?:^|;\\s*)aicrm-darstellung=([^;]*)/);
    var wahl = m ? m[1] : "system";
    var dunkel =
      wahl === "dunkel" ||
      (wahl !== "hell" &&
        window.matchMedia("(prefers-color-scheme: dark)").matches);
    if (dunkel) document.documentElement.classList.add("dunkel");
  } catch (e) {}
})();
`;

function setzeCookie(wert: Darstellung) {
  const ablauf = new Date();
  ablauf.setTime(ablauf.getTime() + 365 * 86400 * 1000);
  document.cookie = `${DARSTELLUNG_COOKIE}=${wert}; Path=/; Expires=${ablauf.toUTCString()}; SameSite=Lax`;
}

function liesCookie(): Darstellung {
  if (typeof document === "undefined") return "system";
  const m = document.cookie.match(/(?:^|;\s*)aicrm-darstellung=([^;]*)/);
  const wert = m?.[1];
  return wert === "hell" || wert === "dunkel" ? wert : "system";
}

function wende(wahl: Darstellung) {
  const dunkel =
    wahl === "dunkel" ||
    (wahl === "system" && window.matchMedia("(prefers-color-scheme: dark)").matches);
  document.documentElement.classList.toggle("dunkel", dunkel);
}

const WAHLEN: { wert: Darstellung; text: string; Zeichen: typeof Sun }[] = [
  { wert: "system", text: "System", Zeichen: Monitor },
  { wert: "hell", text: "Hell", Zeichen: Sun },
  { wert: "dunkel", text: "Dunkel", Zeichen: Moon },
];

export function Darstellungsschalter() {
  // Vor der Hydration nichts markieren: Der Server kennt den Cookie nicht
  // und würde sonst eine andere Auswahl rendern als der Browser.
  const [wahl, setWahl] = useState<Darstellung | null>(null);

  useEffect(() => {
    const gespeichert = liesCookie();
    setWahl(gespeichert);
    wende(gespeichert);

    // Steht die Wahl auf „System", muss ein Wechsel der Systemeinstellung
    // sofort durchschlagen — ohne Neuladen.
    const medium = window.matchMedia("(prefers-color-scheme: dark)");
    const beiWechsel = () => {
      if (liesCookie() === "system") wende("system");
    };
    medium.addEventListener("change", beiWechsel);
    return () => medium.removeEventListener("change", beiWechsel);
  }, []);

  return (
    <div className="darstellung-schalter" role="group" aria-label="Darstellung">
      {WAHLEN.map(({ wert, text, Zeichen }) => (
        <button
          key={wert}
          type="button"
          className={`darstellung-knopf${wahl === wert ? " aktiv" : ""}`}
          aria-pressed={wahl === wert}
          title={text}
          onClick={() => {
            setWahl(wert);
            setzeCookie(wert);
            wende(wert);
          }}
        >
          <Zeichen size={14} strokeWidth={1.75} aria-hidden="true" />
          <span className="nur-vorleser">{text}</span>
        </button>
      ))}
    </div>
  );
}
