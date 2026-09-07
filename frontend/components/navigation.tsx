"use client";

/**
 * Die Leiste einklappen — auf Symbole, mit ⌘B.
 *
 * Ein Cookie, keine Server-Persistenz: Ob die Leiste schmal ist, hängt am
 * Bildschirm, vor dem jemand sitzt, nicht an der Person. Das Attribut am
 * <html> setzt ein Inline-Script vor dem ersten Anstrich, sonst springt die
 * Leiste beim Laden von breit auf schmal.
 */

import { PanelLeftClose, PanelLeftOpen } from "lucide-react";
import { useEffect, useState } from "react";

export const NAVIGATION_COOKIE = "beacon-navigation";
const EINGEKLAPPT = "eingeklappt";

export const NAVIGATION_SCRIPT = `
(function () {
  try {
    var m = document.cookie.match(/(?:^|;\\s*)beacon-navigation=([^;]*)/);
    if (m && m[1] === "eingeklappt") document.documentElement.setAttribute("data-navigation", "eingeklappt");
  } catch (e) {}
})();
`;

function setzeCookie(eingeklappt: boolean) {
  const ablauf = new Date();
  ablauf.setTime(ablauf.getTime() + 365 * 86400 * 1000);
  document.cookie = `${NAVIGATION_COOKIE}=${eingeklappt ? EINGEKLAPPT : "offen"}; Path=/; Expires=${ablauf.toUTCString()}; SameSite=Lax`;
}

function liesCookie(): boolean {
  if (typeof document === "undefined") return false;
  const m = document.cookie.match(/(?:^|;\s*)beacon-navigation=([^;]*)/);
  return m?.[1] === EINGEKLAPPT;
}

function wende(eingeklappt: boolean) {
  if (eingeklappt) document.documentElement.setAttribute("data-navigation", EINGEKLAPPT);
  else document.documentElement.removeAttribute("data-navigation");
}

/** [eingeklappt | null vor der Hydration, umschalten] */
export function useNavigationKlapp(): [boolean | null, () => void] {
  const [eingeklappt, setEingeklappt] = useState<boolean | null>(null);
  useEffect(() => {
    setEingeklappt(liesCookie());
  }, []);

  function umschalten() {
    setEingeklappt((alt) => {
      const neu = !(alt ?? liesCookie());
      wende(neu);
      setzeCookie(neu);
      return neu;
    });
  }

  useEffect(() => {
    function taste(e: KeyboardEvent) {
      // Firefox bindet ⌘B an die Lesezeichen — preventDefault gewinnt,
      // solange die Seite den Fokus hat. Dasselbe Muster wie ⌘K in suche.tsx.
      if ((e.metaKey || e.ctrlKey) && !e.shiftKey && !e.altKey && e.key.toLowerCase() === "b") {
        e.preventDefault();
        umschalten();
      }
    }
    window.addEventListener("keydown", taste);
    return () => window.removeEventListener("keydown", taste);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return [eingeklappt, umschalten];
}

export function Klappschalter({ eingeklappt, umschalten }: { eingeklappt: boolean | null; umschalten: () => void }) {
  const zu = eingeklappt === true;
  const text = zu ? "Navigation ausklappen" : "Navigation einklappen";
  return (
    <button
      type="button"
      className="huelle-klapp"
      onClick={umschalten}
      aria-label={text}
      title={`${text} (⌘B)`}
      aria-keyshortcuts="Meta+B Control+B"
      aria-expanded={!zu}
    >
      {zu ? <PanelLeftOpen size={18} strokeWidth={1.75} aria-hidden="true" /> : <PanelLeftClose size={18} strokeWidth={1.75} aria-hidden="true" />}
    </button>
  );
}
