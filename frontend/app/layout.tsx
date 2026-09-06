import type { Metadata, Viewport } from "next";
import localFont from "next/font/local";
import { DARSTELLUNG_SCRIPT } from "@/components/darstellung";
import { NAVIGATION_SCRIPT } from "@/components/navigation";
import { Huelle } from "@/components/huelle";
import { Abfrageanbieter } from "@/components/abfrageanbieter";
import "./globals.css";

// Geist aus dem Repo, nicht vom Google-CDN — auch nicht zur Bauzeit. Das
// ist keine Vorliebe: AImighty verkauft, dass nichts das Haus verlässt,
// und eine Schriftanfrage an einen fremden Server wäre genau das.
const geistSans = localFont({
  src: "./fonts/Geist-Variable.woff2",
  weight: "100 900",
  variable: "--font-geist-sans",
  display: "swap",
});

const geistMono = localFont({
  src: "./fonts/GeistMono-Variable.woff2",
  weight: "100 900",
  variable: "--font-geist-mono",
  display: "swap",
});

export const metadata: Metadata = {
  title: "Beacon — Vertrieb",
  description: "KI-gestütztes CRM für den AImighty-Vertrieb. Läuft auf der eigenen Box.",
};

export const viewport: Viewport = {
  themeColor: "#051729",
  width: "device-width",
  initialScale: 1,
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="de" className={`${geistSans.variable} ${geistMono.variable}`} suppressHydrationWarning>
      <head>
        {/* Setzt die Klasse `dunkel` vor dem ersten Anstrich — sonst
            blitzt bei dunkler Einstellung kurz die helle Fläche auf. */}
        <script dangerouslySetInnerHTML={{ __html: DARSTELLUNG_SCRIPT }} />
        {/* Dasselbe für die eingeklappte Navigation — sonst springt die
            Leiste beim Laden von breit auf schmal. */}
        <script dangerouslySetInnerHTML={{ __html: NAVIGATION_SCRIPT }} />
      </head>
      <body>
        <Abfrageanbieter>
          <Huelle>{children}</Huelle>
        </Abfrageanbieter>
      </body>
    </html>
  );
}
