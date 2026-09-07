// Was von einem Fehler an die Box geht — und was nicht.
//
// Meldung und Stack, gekürzt auf das, was das Backend annimmt. Keine
// Formulardaten, keine Cookies: Der Bericht soll den Fehler finden helfen,
// nicht den Menschen davor beschreiben.

export interface Fehlerbericht {
  nachricht: string;
  stack: string;
  pfad: string;
  agent: string;
}

export const HOECHSTENS_JE_SEITE = 5;

export function fehlerMeldung(fehler: unknown, pfad: string, agent = ""): Fehlerbericht {
  let nachricht = "Unbekannter Fehler";
  let stack = "";
  if (fehler instanceof Error) {
    nachricht = `${fehler.name}: ${fehler.message}`;
    stack = fehler.stack ?? "";
  } else if (typeof fehler === "string") {
    nachricht = fehler;
  } else if (fehler && typeof fehler === "object" && "message" in fehler) {
    nachricht = String((fehler as { message: unknown }).message);
  } else if (fehler !== undefined && fehler !== null) {
    nachricht = String(fehler);
  }
  return {
    nachricht: nachricht.slice(0, 2000),
    stack: stack.slice(0, 8000),
    pfad: pfad.slice(0, 500),
    agent: agent.slice(0, 300),
  };
}
