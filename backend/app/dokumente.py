"""Dateien am Datensatz — ablegen, wiederfinden, ausliefern.

Die Datei liegt auf der Platte, die Zeile in der Datenbank. Was hier
steht, ist die Naht zwischen beidem, und an einer Naht reißt es.

Drei Dinge, die deshalb nicht verhandelbar sind:

- **Ein Dateiname aus dem Internet kommt nie in einen Pfad.** Der Name,
  den der Mensch sieht, steht in der Datenbank; auf der Platte heißt die
  Datei nach ihrer Kennung. `../../etc/passwd` ist damit nur ein
  hässlicher Anzeigename und kein Angriff.
- **Ausgeliefert wird als Anhang, nicht als Seite.** Eine hochgeladene
  HTML- oder SVG-Datei, die der Browser im Ursprung von Beacon anzeigt,
  wäre eingeschleustes Skript mit allen Rechten des Angemeldeten. Nur
  Bilder und PDF dürfen im Fenster erscheinen — und SVG gehört nicht
  dazu, das ist ein Dokument mit Skriptfähigkeit.
- **Erst schreiben, dann eintragen.** Eine Zeile ohne Datei zeigt ins
  Leere; eine Datei ohne Zeile ist nur verschenkter Platz. Von beiden
  Fehlern ist der zweite der harmlosere.
"""

from __future__ import annotations

import hashlib
import os
import pathlib
import re
from uuid import UUID

from app.config import settings

ORDNER = "dokumente"

# 25 MB. Größer wird es zum Dateiserver, und dafür gibt es Drive auf der
# Box. Die Grenze steht hier und nicht im Router, damit Test und
# Fehlermeldung dieselbe Zahl nennen.
MAX_BYTES = 25 * 1024 * 1024

# Was der Browser im Fenster zeigen darf. Alles andere lädt herunter.
# SVG fehlt mit Absicht: Es kann Skript enthalten und liefe dann im
# Ursprung von Beacon.
INLINE = frozenset({
    "application/pdf",
    "image/png", "image/jpeg", "image/gif", "image/webp", "image/avif",
})

# Endungen, die Olares' Dateiverwaltung und der Browser gleichermaßen
# harmlos behandeln. Unbekanntes bekommt gar keine Endung — der Name in
# der Datenbank trägt sie ohnehin.
_ENDUNG = re.compile(r"^\.[A-Za-z0-9]{1,8}$")


def ablage() -> pathlib.Path:
    ordner = pathlib.Path(settings.app_data_dir) / ORDNER
    ordner.mkdir(parents=True, exist_ok=True)
    return ordner


def endung_von(name: str) -> str:
    """Die Endung des Anzeigenamens — oder nichts.

    Sie dient allein dazu, dass die Datei in Olares' Dateiverwaltung
    erkennbar bleibt. Alles, was nicht wie eine gewöhnliche Endung
    aussieht, fällt weg.
    """
    endung = pathlib.PurePosixPath(name.replace("\\", "/")).suffix
    return endung.lower() if _ENDUNG.match(endung) else ""


def anzeigename(name: str) -> str:
    """Was der Mensch sieht. Ohne Pfadanteile, ohne Steuerzeichen.

    Der Name geht später in einen `Content-Disposition`-Kopf; ein
    Zeilenumbruch darin wäre eine eingeschleuste Kopfzeile.
    """
    nur_name = pathlib.PurePosixPath(name.replace("\\", "/")).name
    sauber = "".join(z for z in nur_name if z.isprintable() and z not in '"\\').strip()
    return sauber[:200] or "datei"


def schreiben(org_id: UUID, dokument_id: UUID, name: str, daten: bytes) -> tuple[str, str]:
    """Legt die Datei ab. Gibt Pfad (relativ zu app_data) und Prüfsumme.

    Geschrieben wird erst unter `.teil` und dann umbenannt: Ein Abbruch
    mitten im Schreiben hinterlässt so keine halbe Datei, die aussieht,
    als wäre sie ganz.
    """
    ordner = ablage() / str(org_id)
    ordner.mkdir(parents=True, exist_ok=True)
    ziel = ordner / f"{dokument_id}{endung_von(name)}"
    vorlaeufig = ziel.with_name(ziel.name + ".teil")
    vorlaeufig.write_bytes(daten)
    os.chmod(vorlaeufig, 0o600)
    vorlaeufig.rename(ziel)
    return f"{ORDNER}/{org_id}/{ziel.name}", hashlib.sha256(daten).hexdigest()


def pfad(relativ: str | None) -> pathlib.Path | None:
    """Der absolute Pfad — und nur, wenn er wirklich in der Ablage liegt.

    `resolve()` löst `..` und Verweise auf, **bevor** verglichen wird.
    Ein Vergleich auf der Zeichenkette ließe sich mit `dokumente/../..`
    aushebeln.
    """
    if not relativ:
        return None
    wurzel = (pathlib.Path(settings.app_data_dir) / ORDNER).resolve()
    ziel = (pathlib.Path(settings.app_data_dir) / relativ).resolve()
    if wurzel != ziel and wurzel not in ziel.parents:
        return None
    return ziel


def loeschen(relativ: str | None) -> None:
    p = pfad(relativ)
    if p is not None:
        p.unlink(missing_ok=True)


def darf_im_fenster(typ: str | None) -> bool:
    return (typ or "").split(";")[0].strip().lower() in INLINE
