import Image from "next/image";

/**
 * Die Wortmarke von AImighty in der Kopfecke.
 *
 * Zwei Dateien statt einer umgefärbten: Beide tragen dasselbe goldene
 * Wappen, nur „mighty" wechselt zwischen Dunkelblau und Weiß. Welche
 * gilt, entscheidet das CSS am Datenattribut der Darstellung — so ist
 * kein Skript nötig, und beim ersten Bild steht schon die richtige da.
 *
 * Die Dateien kommen unverändert aus `aimighty/marke/logo/`. Sie werden
 * eingebunden, nicht nachgebaut: keine Nachzeichnung, keine
 * Farbkorrektur (siehe `public/marke/README.md`).
 */
export function Marke() {
  return (
    <span className="marke-logo">
      <Image
        src="/marke/aimighty-hell.svg"
        alt="AImighty"
        width={472}
        height={167}
        priority
        className="marke-logo-bild hell"
      />
      <Image
        src="/marke/aimighty-dunkel.svg"
        alt=""
        aria-hidden="true"
        width={472}
        height={167}
        priority
        className="marke-logo-bild dunkel"
      />
    </span>
  );
}
