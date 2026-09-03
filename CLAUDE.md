# aicrm — Projekt-Briefing für Claude Code

> **Produkt:** aicrm — schlankes, KI-gestütztes CRM für den AImighty-Vertrieb
> **Maintainer:** Kai Böhm (kaivo.studio)
> **Plattform:** Olares OS (Kubernetes-basiert), wie Insilo
> **Status:** Ausbaustufe 1 — Kern steht (Firmen, Kontakte, Deals, Board)
> **Letzte Aktualisierung:** 3. September 2026

---

## Was wir bauen

Ein CRM, das den Vertriebsprozess von AImighty abbildet und dabei
**vollständig auf der eigenen Box läuft**. AImighty verkauft, dass Daten
das Haus nicht verlassen — ein CRM in einer US-Cloud wäre der
Widerspruch, den kein Kunde übersieht.

**Bedienung nach HubSpot, Aussehen nach AImighty.** HubSpot liefert das
Muster: linke Navigation, dichte Listenansichten mit Filtern,
dreispaltige Datensatzseite, Pipeline als Board mit Ziehen und Ablegen.
Farbe, Schrift und Raum kommen aus dem AImighty-Designsystem. Ein
Pixel-Nachbau inklusive HubSpot-Orange war ausdrücklich nicht gewollt.

**Kein HubSpot-Import.** Grüne Wiese, entschieden am 3.9.2026. Das Schema
richtet sich nach dem, was der AImighty-Vertrieb braucht: die
Produktleiter Assistent / Analyst / Experte, Servicetage, Kaufrollen.

---

## Stand

**Fertig und geprüft:**

| Teil | Zustand |
|---|---|
| Schema + Zeilensicherheit | 2 Migrationen, 13 Tests grün |
| Backend | 18 API-Pfade, FastAPI, asyncpg |
| Oberfläche | Start, Board, Firmen, Kontakte, Aufgaben, Einstellungen, zwei Datensatzseiten |
| KI | Zusammenfassung, nächster Schritt, Anschreiben-Entwurf |
| Olares-Chart | lintet und rendert, **nie auf einer echten Box installiert** |

**Nicht gebaut, bewusst:** Ausfuhr/Sicherung (siehe „Das größte offene
Risiko"), Mehrsprachigkeit, Hintergrundjobs, Volltextsuche über
Aktivitäten, E-Mail-Anbindung, Insilo-Kopplung.

---

## Plattform-Kontext: Olares OS

Dieselben Constraints wie bei Insilo. Die wichtigsten für dieses Repo:

1. **Keine eigene Anmeldung.** Der Envoy-Sidecar prüft den
   Authelia-Token, bevor ein Request ankommt. Die Identität steht im Kopf
   `X-Bfl-User`. Fehlt er, wird abgewiesen — nie geraten.

2. **Nur ClusterIP.** Kein NodePort, kein LoadBalancer, kein
   hostNetwork. Von außen führt der Weg nur über den deklarierten
   Entrance.

3. **Datenbank-Zugangsdaten werden injiziert** als `.Values.postgres.*`.
   Nie hartkodieren.

4. **Ein Upgrade friert `values.yaml` ein.** Olares spielt beim
   Aktualisieren die bei der *Installation* gespeicherten Werte zurück
   und übernimmt die Vorgaben des neuen Charts nicht. Deshalb hängt der
   Image-Tag an `.Chart.AppVersion`, und `values.yaml` trägt `tag: ""`.
   Neue Wertschlüssel immer über `(default (dict) .Values.x).y` lesen —
   ein Punktzugriff auf einen Block, den es in der Vorversion nicht gab,
   lässt das Upgrade mit „nil pointer" scheitern.

5. **Eine Deinstallation löscht die Datenbank.** `/app/data` überlebt,
   die Datenbank nicht. Siehe unten.

6. **Namensregel:** Ordnername, `Chart.yaml.name`, `metadata.name` und
   `metadata.appid` müssen alle exakt `aicrm` sein.

7. **Keine Helm-Hooks, kein `.Files.Get`.** Ersteres läuft vor dem
   `ns-owner`-Label und kommt nie durch, Zweiteres lehnt der Markt-Linter
   ab. Deshalb Migrationen als eingebettete ConfigMap plus
   Vorlauf-Container mit Wiederholschleife.

---

## Das größte offene Risiko

**Eine Deinstallation löscht sämtliche Vertriebsdaten, ohne Weg zurück.**

Olares legt die Datenbank bei einer Neuinstallation frisch an. Für Insilo
war das verschmerzbar, weil die Tonaufnahmen unter `/app/data` liegen und
`backend/app/konfiguration.py` einen Abzug der Einrichtung danebenlegt.
aicrm hat nichts dergleichen: Firmen, Kontakte, Geschäfte und der ganze
Verlauf leben ausschließlich in der Datenbank.

Der Ausfuhrpfad ist deshalb der **erste Punkt der nächsten Ausbaustufe**.
`permission.appData` steht bereits im Manifest, damit der Ablageort da
ist, wenn es so weit ist. Bis dahin: nicht auf einer Box betreiben, auf
der die App wieder entfernt werden könnte, ohne dass vorher jemand
`pg_dump` laufen lässt.

---

## Tech-Stack

Bewusst derselbe wie Insilo — was dort trägt, muss hier nicht neu
gelernt werden.

**Oberfläche:** Next.js 15 (App Router) · TypeScript strict · Tailwind v4
· TanStack Query · lucide-react. Kein next-intl: Das CRM ist ein
internes Werkzeug und bleibt einsprachig deutsch.

**Backend:** FastAPI · asyncpg (kein ORM) · Pydantic v2 · httpx.

**Datenbank:** PostgreSQL 16 von Olares. `pg_trgm`, `pgcrypto`,
`uuid-ossp`. **Kein `vector`** — diese Ausbaustufe rechnet keine
Einbettungen, und eine Erweiterung, die niemand nutzt, lässt nur die
lokale Einrichtung scheitern.

**Sprachmodell:** OpenAI-kompatibler Endpunkt, Adresse pro Organisation
in `org_settings`. **Kein Vorgabewert** — dieselbe Entscheidung wie bei
Insilo seit v0.1.72, aus demselben Grund: Jede geratene Adresse ist auf
einer anderen Box falsch.

---

## Designsystem

**Die Werte stehen in `frontend/app/globals.css`.** Der Token-Block und
die Bauteile darunter sind unverändert aus dem AImighty-Paket über Insilo
übernommen; darunter steht ein eigener Abschnitt mit den CRM-Bauteilen.
**Dieser Abschnitt enthält keinen einzigen Farbwert, nur `--am-*`.** Wer
eine Farbe ändern will, ändert das Token.

- **Gold zeichnet aus, es handelt nicht** — Ausnahme Dunkelmodus, dort
  handelt es, weil Blau auf Blau nicht trägt. Beides steckt in den Token.
- **Farbe trägt eine Aussage nie allein.** Jede Stufenpille hat Text,
  jeder Fehler ein Zeichen und einen Satz.
- **Was die KI geschrieben hat, ist als solches erkennbar** — goldener
  Punkt in der Zeitleiste, Beschriftung „KI", Modellname darunter. Nicht
  aus Zierde: In einem Jahr muss unterscheidbar sein, was ein Mensch
  notiert hat.
- **Keine Verläufe, kein Glas, keine Parallaxe, keine KI-Funken.**

`frontend/tailwind.aimighty.preset.js` ist eine unveränderte Kopie aus
der Lieferung und liest die Token über `var(--am-*)`.

---

## Wie hier gearbeitet wird

1. **Bei Schema-Änderungen:** Migration in `supabase/migrations/0NNN_*.sql`,
   RLS auf jede neue Tabelle **plus `force row level security`**, dann
   `python3 scripts/regen-migrations.py`. Ohne FORCE ist die
   Zeilensicherheit lautlos wirkungslos, weil das Backend als
   Tabelleneigentümer verbindet — der Test
   `test_mandanten_sehen_einander_nicht` fängt genau das.

2. **Bei Chart-Änderungen:** vor dem Commit `bash scripts/check-chart.sh`.

3. **Bei Backend-Änderungen:** Keine Auth-Logik bauen. Jede Abfrage auf
   Fachdaten läuft über `acquire_as(user_id)` — `acquire()` ohne Kontext
   ist nur für die Erstanlage da.

4. **Bei UI-Arbeit:** Erst schauen, ob `globals.css` das Bauteil schon
   hat. Werte nie am Bauteil setzen.

5. **Bei KI-Funktionen:** Ergebnis immer als Aktivität der Art `ai`
   festhalten, nie in ein Feld schreiben, das jemand von Hand gefüllt
   hat. Ist kein Endpunkt eingerichtet, sagt die Oberfläche das —
   niemals in einen Verbindungsfehler laufen lassen.

6. **Sprache:** Oberfläche und Docs deutsch, Sie-Form. Code und
   Commit-Messages englisch. Bezeichner im Code englisch, Kommentare
   deutsch — wie in Insilo.

7. **Bei Unsicherheit:** stoppen und Kai fragen.

---

## Lokale Entwicklung

Siehe `docs/BETRIEB.md`. Kurz:

```bash
brew services start postgresql@16
backend/.venv/bin/uvicorn app.main:app --port 8000   # aus backend/
cd frontend && BACKEND_URL=http://localhost:8000 npm run dev
python3 scripts/seed-dev.py                           # Beispieldaten
```

---

## Was NICHT gebaut wird

- ❌ Eigene Anmeldung (Olares macht das)
- ❌ Cloud-Sync zwischen Boxen
- ❌ Telemetrie, Tracking, Phone-Home
- ❌ Schriften vom CDN — auch nicht zur Bauzeit
- ❌ Ein zweites Designsystem
