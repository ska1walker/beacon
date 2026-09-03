"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  Building2,
  CheckSquare,
  FileText,
  Handshake,
  Inbox,
  LayoutDashboard,
  MessageCircleQuestion,
  TrendingUp,
  Settings,
  Users,
} from "lucide-react";
import { Darstellungsschalter } from "@/components/darstellung";
import { Sitzplatzwahl } from "@/components/sitzplatz";

// Die Hülle hat drei Bereiche: Navigation, Inhalt, Ablage. Die Ablage
// trägt Kontext zum gewählten Ding und ist nie eine zweite Inhaltsspalte —
// die Seiten liefern sie über <aside class="huelle-ablage">.
const ZIELE = [
  { pfad: "/", text: "Start", Zeichen: LayoutDashboard },
  { pfad: "/deals", text: "Deals", Zeichen: Handshake },
  { pfad: "/angebote", text: "Angebote", Zeichen: FileText },
  { pfad: "/prognose", text: "Prognose", Zeichen: TrendingUp },
  { pfad: "/firmen", text: "Firmen", Zeichen: Building2 },
  { pfad: "/kontakte", text: "Kontakte", Zeichen: Users },
  { pfad: "/aufgaben", text: "Aufgaben", Zeichen: CheckSquare },
  { pfad: "/fragen", text: "Fragen", Zeichen: MessageCircleQuestion },
  { pfad: "/eingang", text: "Eingang", Zeichen: Inbox },
];

const NACHRANGIG = [{ pfad: "/einstellungen", text: "Einstellungen", Zeichen: Settings }];

function istAktiv(pfad: string, aktuell: string): boolean {
  if (pfad === "/") return aktuell === "/";
  return aktuell === pfad || aktuell.startsWith(`${pfad}/`);
}

export function Huelle({ children }: { children: React.ReactNode }) {
  const aktuell = usePathname();

  return (
    <div className="huelle">
      <nav className="huelle-nav" aria-label="Hauptnavigation">
        <div className="huelle-kopfecke">
          <Link href="/" className="marke">
            <span className="marke-punkt" aria-hidden="true" />
            <span className="marke-text">aicrm</span>
          </Link>
        </div>

        <div className="huelle-nav-gruppe">
          {ZIELE.map(({ pfad, text, Zeichen }) => (
            <Link
              key={pfad}
              href={pfad}
              className={`huelle-nav-item${istAktiv(pfad, aktuell) ? " aktiv" : ""}`}
              aria-current={istAktiv(pfad, aktuell) ? "page" : undefined}
            >
              <Zeichen size={18} strokeWidth={1.75} aria-hidden="true" />
              <span>{text}</span>
            </Link>
          ))}
        </div>

        <div className="huelle-nav-spacer" />

        <div className="huelle-nav-gruppe">
          {NACHRANGIG.map(({ pfad, text, Zeichen }) => (
            <Link
              key={pfad}
              href={pfad}
              className={`huelle-nav-item${istAktiv(pfad, aktuell) ? " aktiv" : ""}`}
              data-nachrangig="true"
            >
              <Zeichen size={18} strokeWidth={1.75} aria-hidden="true" />
              <span>{text}</span>
            </Link>
          ))}
        </div>

        <div className="huelle-fuss">
          <Sitzplatzwahl />
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
