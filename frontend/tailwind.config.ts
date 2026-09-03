import type { Config } from "tailwindcss";
// Das Preset kommt unverändert aus dem AImighty-Designpaket. Es dupliziert
// keine Werte, sondern liest die CSS-Variablen aus app/globals.css.
// Änderungen gehören in die Quelle, nicht in diese Kopie.
import aimightyPreset from "./tailwind.aimighty.preset";

const aimighty = aimightyPreset as unknown as Config;

const config: Config = {
  presets: [aimighty],
  content: [
    "./app/**/*.{ts,tsx,mdx}",
    "./components/**/*.{ts,tsx,mdx}",
    "./lib/**/*.{ts,tsx}",
  ],
  plugins: [],
};

export default config;
