"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  Building2,
  CheckSquare,
  Ellipsis,
  FileText,
  Handshake,
  Inbox,
  LayoutDashboard,
  LifeBuoy,
  Lightbulb,
  ListChecks,
  Megaphone,
  MessageCircleQuestion,
  Settings,
  Star,
  TrendingUp,
  Users,
  type LucideIcon,
} from "lucide-react";
import { useEffect, useState } from "react";
import { Darstellungsschalter } from "@/components/darstellung";
import { Marke } from "@/components/marke";
import { Klappschalter, useNavigationKlapp } from "@/components/navigation";
import { Personenanzeige } from "@/components/person";
import { Suchfeld } from "@/components/suche";
import {
  GRUPPEN,
  NACHRANGIG,
  favoritenZiele,
  istAktiv,
  mobilRest,
  mobilZiele,
  type NavZeichen,
  type NavZiel,
} from "@/lib/navigation";
import { useFavoriten } from "@/lib/wer";

// Die Hülle hat drei Bereiche: Navigation, Inhalt, Ablage. Die Ablage
// trägt Kontext zum gewählten Ding und ist nie eine zweite Inhaltsspalte —
// die Seiten liefern sie über <aside class="huelle-ablage">.
//
// Die Navigation selbst steht in lib/navigation.ts als Daten; hier hängen
// nur die Symbole daran.
const ZEICHEN: Record<NavZeichen, LucideIcon> = {
  start: LayoutDashboard,
  leads: Handshake,
  angebote: FileText,
  prognose: TrendingUp,
  aufgaben: CheckSquare,
  firmen: Building2,
  kontakte: Users,
  listen: ListChecks,
  eingang: Inbox,
  tickets: LifeBuoy,
  kampagnen: Megaphone,
  fragen: MessageCircleQuestion,
  erkenntnisse: Lightbulb,
  einstellungen: Settings,
};

export function Huelle({ children }: { children: React.ReactNode }) {
  const aktuell = usePathname();
  const { favoriten, umschalten } = useFavoriten();
  const [eingeklappt, klappen] = useNavigationKlapp();
  const [mehrOffen, setMehrOffen] = useState(false);
  useEffect(() => setMehrOffen(false), [aktuell]);

  const meine = favoritenZiele(favoriten);

  return (
    <div className="huelle">
      <nav className="huelle-nav" aria-label="Hauptnavigation">
        <div className="huelle-kopfecke">
          <Link href="/" className="marke" aria-label="AImighty Beacon — zur Startseite">
            <Marke />
            <span className="marke-produkt" aria-hidden="true">Beacon</span>
          </Link>
          <Klappschalter eingeklappt={eingeklappt} umschalten={klappen} />
        </div>

        <div className="huelle-suche">
          <Suchfeld />
        </div>

        {meine.length > 0 && (
          <NavGruppe titel="Favoriten" ziele={meine} aktuell={aktuell} favoriten={favoriten} umschalten={umschalten} eingeklappt={eingeklappt === true} />
        )}
        {GRUPPEN.map((g) => (
          <NavGruppe key={g.titel} titel={g.titel} ziele={g.ziele} aktuell={aktuell} favoriten={favoriten} umschalten={umschalten} eingeklappt={eingeklappt === true} />
        ))}

        <div className="huelle-nav-spacer" />

        <NavGruppe ziele={NACHRANGIG} aktuell={aktuell} favoriten={favoriten} umschalten={umschalten} eingeklappt={eingeklappt === true} nachrangig />

        {/* Die schmale Leiste unten: Favoriten oder die Vorgabe, dazu „Mehr“. */}
        <div className="huelle-nav-mobil">
          {mobilZiele(favoriten).map((z) => (
            <NavLink key={z.pfad} ziel={z} aktuell={aktuell} />
          ))}
          <button
            type="button"
            className={`huelle-nav-item${mehrOffen ? " aktiv" : ""}`}
            aria-expanded={mehrOffen}
            aria-controls="huelle-nav-mehr"
            onClick={() => setMehrOffen((o) => !o)}
          >
            <Ellipsis size={18} strokeWidth={1.75} aria-hidden="true" />
            <span>Mehr</span>
          </button>
        </div>
        {mehrOffen && (
          <div className="huelle-nav-mehr" id="huelle-nav-mehr" role="group" aria-label="Weitere Bereiche">
            {mobilRest(favoriten).map((z) => (
              <NavLink key={z.pfad} ziel={z} aktuell={aktuell} />
            ))}
          </div>
        )}

        <div className="huelle-fuss">
          <Personenanzeige />
          <div className="huelle-herkunft">
            <Darstellungsschalter />
            <span className="huelle-herkunft-recht">läuft auf dieser Box</span>
          </div>
        </div>
      </nav>

      <main className="huelle-inhalt">{children}</main>
    </div>
  );
}

function NavLink({ ziel, aktuell, eingeklappt = false, nachrangig = false }: { ziel: NavZiel; aktuell: string; eingeklappt?: boolean; nachrangig?: boolean }) {
  const Zeichen = ZEICHEN[ziel.zeichen];
  const aktiv = istAktiv(ziel.pfad, aktuell);
  return (
    <Link
      href={ziel.pfad}
      className={`huelle-nav-item${aktiv ? " aktiv" : ""}`}
      aria-current={aktiv ? "page" : undefined}
      title={eingeklappt ? ziel.text : undefined}
      data-nachrangig={nachrangig ? "true" : undefined}
    >
      <Zeichen size={18} strokeWidth={1.75} aria-hidden="true" />
      <span>{ziel.text}</span>
    </Link>
  );
}

/**
 * Eine Gruppe: Überschrift und Einträge. Der Stern steht **neben** dem
 * Link, nicht darin — ein Knopf in einem Link ist kein gültiges HTML.
 */
function NavGruppe({
  titel,
  ziele,
  aktuell,
  favoriten,
  umschalten,
  eingeklappt,
  nachrangig = false,
}: {
  titel?: string;
  ziele: NavZiel[];
  aktuell: string;
  favoriten: string[];
  umschalten: (pfad: string) => void;
  eingeklappt: boolean;
  nachrangig?: boolean;
}) {
  const id = titel ? `huelle-nav-${titel.toLowerCase()}` : undefined;
  return (
    <div className="huelle-nav-gruppe" role="group" aria-labelledby={id}>
      {titel && <p className="huelle-nav-titel" id={id}>{titel}</p>}
      {ziele.map((z) => {
        const istFavorit = favoriten.includes(z.pfad);
        return (
          <div key={z.pfad} className={`huelle-nav-eintrag${istFavorit ? " ist-favorit" : ""}`}>
            <NavLink ziel={z} aktuell={aktuell} eingeklappt={eingeklappt} nachrangig={nachrangig} />
            <button
              type="button"
              className="huelle-nav-stern"
              aria-pressed={istFavorit}
              aria-label={istFavorit ? `${z.text} als Favorit entfernen` : `${z.text} als Favorit merken`}
              title={istFavorit ? "Favorit entfernen" : "Als Favorit merken"}
              onClick={() => umschalten(z.pfad)}
            >
              <Star size={14} strokeWidth={1.75} fill={istFavorit ? "currentColor" : "none"} aria-hidden="true" />
            </button>
          </div>
        );
      })}
    </div>
  );
}
