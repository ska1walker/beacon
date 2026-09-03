/**
 * InSilo — Tailwind-Preset
 * Bindet dieselben CSS-Variablen wie tokens/globals.css. Werte stehen nur
 * dort — dieses Preset liest sie über var(--am-*), es dupliziert nichts.
 *
 * Einbinden:
 *   // tailwind.config.js
 *   import insilo from "./tailwind.insilo.preset.js";
 *   export default { presets: [insilo], content: [...] };
 *
 * Dunkelmodus: Klasse `dunkel` am <html>, nicht `dark` — konsistent mit dem
 * AImighty-App-System (`html.dunkel { ... }` in globals.css).
 */
export default {
  darkMode: ["class", "dunkel"],
  theme: {
    extend: {
      fontFamily: {
        sans: ["Geist Sans", "ui-sans-serif", "system-ui", "sans-serif"],
        mono: ["Geist Mono", "ui-monospace", "SF Mono", "monospace"],
      },
      colors: {
        blau: {
          25: "var(--am-blau-25)",
          50: "var(--am-blau-50)",
          100: "var(--am-blau-100)",
          200: "var(--am-blau-200)",
          300: "var(--am-blau-300)",
          400: "var(--am-blau-400)",
          500: "var(--am-blau-500)",
          600: "var(--am-blau-600)",
          700: "var(--am-blau-700)",
          800: "var(--am-blau-800)",
          900: "var(--am-blau-900)",
          950: "var(--am-blau-950)",
        },
        gold: {
          200: "var(--am-gold-200)",
          300: "var(--am-gold-300)",
          400: "var(--am-gold-400)",
          500: "var(--am-gold-500)",
          600: "var(--am-gold-600)",
          700: "var(--am-gold-700)",
          800: "var(--am-gold-800)",
          900: "var(--am-gold-900)",
        },
        // Halbsemantisch — bevorzugt gegenüber blau-*/gold-* in Bauteilen
        seite: "var(--am-seite)",
        "flaeche-1": "var(--am-flaeche-1)",
        "flaeche-2": "var(--am-flaeche-2)",
        "flaeche-3": "var(--am-flaeche-3)",
        trennlinie: "var(--am-trennlinie)",
        rand: "var(--am-rand)",
        "rand-betont": "var(--am-rand-betont-farbe)",
        "text-primaer": "var(--am-text-primaer)",
        "text-sekundaer": "var(--am-text-sekundaer)",
        "text-gedaempft": "var(--am-text-gedaempft)",
        "text-deaktiviert": "var(--am-text-deaktiviert)",
        handlung: "var(--am-handlung-ruhend)",
        "handlung-hover": "var(--am-handlung-hover)",
        "handlung-aktiv": "var(--am-handlung-aktiv)",
        "handlung-text": "var(--am-handlung-text)",
        auszeichnung: "var(--am-gold-auszeichnung)",
        erfolg: "var(--am-erfolg)",
        hinweis: "var(--am-hinweis)",
        achtung: "var(--am-achtung)",
        fehler: "var(--am-fehler)",
        "erfolg-flaeche": "var(--am-erfolg-flaeche)",
        "hinweis-flaeche": "var(--am-hinweis-flaeche)",
        "achtung-flaeche": "var(--am-achtung-flaeche)",
        "fehler-flaeche": "var(--am-fehler-flaeche)",
      },
      spacing: {
        1: "var(--am-raum-1)",
        2: "var(--am-raum-2)",
        3: "var(--am-raum-3)",
        4: "var(--am-raum-4)",
        6: "var(--am-raum-6)",
        8: "var(--am-raum-8)",
        12: "var(--am-raum-12)",
        16: "var(--am-raum-16)",
        "ziel-zeiger": "var(--am-ziel-zeiger)",
        "ziel-beruehrung": "var(--am-ziel-beruehrung)",
      },
      maxWidth: {
        inhalt: "var(--am-spur-inhalt)",
      },
      borderRadius: {
        klein: "var(--am-radius-klein)",
        mittel: "var(--am-radius-mittel)",
        gross: "var(--am-radius-gross)",
        voll: "var(--am-radius-voll)",
      },
      borderWidth: {
        ruhend: "var(--am-rand-ruhend)",
        betont: "var(--am-rand-betont)",
      },
      transitionDuration: {
        kurz: "var(--am-dauer-kurz)",
        lang: "var(--am-dauer-lang)",
      },
      ringColor: {
        fokus: "var(--am-fokus-ring)",
      },
    },
  },
};
