# Beacon — Projekt-Briefing für Claude Code

> **Produkt:** Beacon — schlankes, KI-gestütztes CRM für den AImighty-Vertrieb
> **Maintainer:** Kai Böhm (kaivo.studio)
> **Plattform:** Olares OS (Kubernetes-basiert), wie Insilo
> **Status:** Der Vertriebsprozess ist durchgängig abgebildet
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

Der Weg vom ersten Kontakt bis zum Abschluss ist durchgängig da.

| Teil | Zustand |
|---|---|
| Schema + Zeilensicherheit | 12 Migrationen, alle Fachtabellen unter FORCE |
| Backend | rund 100 API-Pfade, FastAPI + asyncpg |
| Oberfläche | Start, Board, Angebote, Prognose, Firmen, Kontakte, Aufgaben, Fragen, Eingang, Einstellungen |
| Angebote | Katalog, Positionen, Summen, Druckfassung mit Briefkopf |
| Qualifizierung | sechs Felder, gerechnete Punktzahl, Verlustgründe |
| Prognose | gewichtet, Trefferquote, Verlustanalyse, nach Produkt |
| KI | Notiz→Struktur, Tagesbriefing, Fragen an den Bestand, Angebotsvorschlag, Qualifizierung aus dem Verlauf, Anschreiben |
| Insilo-Kopplung | signierter Empfang, Zuordnung, Eingangskorb |
| Zusammenarbeit | Sitzplätze am geteilten Olares-Zugang, Besitz, Filter „Nur meine" |
| Eigene Eigenschaften | je Objekt: Text, Zahl, Datum, Ja/Nein, Auswahl — geprüft beim Schreiben |
| Pipelines | mehrere nebeneinander, Stufen anlegen/ändern/ordnen/löschen mit Zielangabe |
| Kontakte | anlegen, bearbeiten, löschen; Hauptfirma plus weitere Firmen |
| Segmentierung | Bedingungen auf jedes Feld (auch eigene), gespeicherte Ansichten als Reiter, wählbare Spalten, Sortierung am Kopf, Auswahl und Stapeländerung — dieselbe Komponente für Firmen und Kontakte |
| Stammdaten | Firma, Kontakt, Geschäft, Angebot: ein Bearbeiten-Schalter, Löschen mit Rückfrage |
| Katalog, Verlustgründe, Aufgaben, Verlauf | vollständig pflegbar; Systemeinträge bleiben Geschichte |
| Post | Vertrag für Relay: signiert hinein und hinaus, Entwurf → Senden nur durch Menschen |
| Anreicherung | Firmen und Kontakte aus Website, Suchdienst und LinkedIn-Treffern; jeder Wert mit Quelle, Kontaktdaten nur wörtlich belegt, nie überschreiben; leere Felder von selbst, Rest als Vorschlag |
| Sicherung | alle sechs Stunden, Wiederanlauf nach Deinstallation |
| Tests | 184 Backend, 11 Frontend |
| Olares-Chart | lintet (`helm` und `olares-cli chart lint`), rendert, **läuft seit 3.9.2026 auf Kais Box** (0.1.4, Upload-Quelle) |
| Veröffentlichung | Repo `github.com/ska1walker/beacon` (öffentlich), Abbilder `ghcr.io/ska1walker/beacon-{frontend,backend}` per Tag, Katalogeintrag **live** in `bayerhazard/aimighty-market` (0.1.4); Icon nach Marcs Idee 6 (`docs/icon/`) |

**Nicht gebaut, bewusst:** Mehrsprachigkeit (internes Werkzeug),
E-Mail-Versand aus der Anwendung, Kampagnen und Sequenzen, Kalender-
Anbindung, mobile Ansicht über das Responsive hinaus.

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
   `metadata.appid` müssen alle exakt `beacon` sein.

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
Beacon hat nichts dergleichen: Firmen, Kontakte, Geschäfte und der ganze
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
   ist nur für die Erstanlage da. Protokolliert wird mit
   `audit.log_fuer(conn, user, …)`: Es hält Person **und** Zugang fest,
   denn am geteilten Olares-Konto sind das zwei verschiedene Dinge.

   **Zwei Menschen, ein Zugang.** Olares installiert eine App pro Nutzer;
   ein zweites Olares-Konto kommt nicht an den Entrance. Kai und Marc
   teilen deshalb einen Zugang, und der *Sitzplatz* (Cookie, Kopf
   `X-Beacon-Sitzplatz`) sagt, wem die Arbeit zugeschrieben wird. Das ist
   Zuschreibung, keine Anmeldung — ein Sitzplatz greift nur innerhalb
   derselben Organisation, sonst 403.

   **Eigene Eigenschaften** liegen als `custom jsonb` an Firma, Kontakt
   und Geschäft; die Datenbank sieht nur JSON. Geprüft wird beim Schreiben
   in `app/eigenschaften.py` gegen die Definition. PATCH führt zusammen
   (`custom || $n`), `null` löscht einen Wert. Typ und Schlüssel einer
   Definition sind nach dem Anlegen fest.

4. **Bei UI-Arbeit:** Erst schauen, ob `globals.css` das Bauteil schon
   hat. Werte nie am Bauteil setzen.

5. **Bei KI-Funktionen** gelten vier Regeln, jede teuer bezahlt:

   - **Zahlen kommen nie aus dem Modell.** Preise aus dem Katalog,
     Zählungen aus der Datenbank. Ein Modell, das einen Betrag erfindet,
     erfindet ihn plausibel — und plausibel falsch kommt bis zum Kunden
     durch.
   - **Kein Datum ausrechnen lassen.** Das Modell kennt das heutige nicht.
     Es nennt die Zeitangabe aus dem Text, gerechnet wird im Backend.
   - **Ergebnis als Aktivität der Art `ai` festhalten**, nie in ein Feld
     schreiben, das jemand von Hand gefüllt hat. Vorschläge füllen die
     Maske, speichern tut ein Mensch.
   - **Ohne Fundstelle keine Antwort.** Wo nichts gefunden wurde, wird
     kein Modell gefragt. Ist kein Endpunkt eingerichtet, sagt die
     Oberfläche das, statt in einen Verbindungsfehler zu laufen.

6. **Sprache:** Oberfläche und Docs deutsch, Sie-Form. Code und
   Commit-Messages englisch. Bezeichner im Code englisch, Kommentare
   deutsch — wie in Insilo.

7. **Bei eingehenden Ereignissen:** Signatur über den **rohen** Body
   prüfen, zeitkonstant vergleichen, den Idempotenzschlüssel des
   Absenders achten. Zugeordnet wird nur, was eindeutig ist — ein
   Protokoll am falschen Kunden ist schlimmer als eines im Eingangskorb.

8. **Bei der Anreicherung** (`app/anreicherung.py`) kommt eine fünfte
   KI-Regel dazu: **Kontaktdaten nur wörtlich belegt.** E-Mail, Telefon,
   LinkedIn, Website, Straße, PLZ und Beschäftigtenzahl müssen in der
   gelesenen Quelle stehen, sonst fallen sie weg — egal, wie sicher das
   Modell klingt. Vorhandene Werte werden nie überschrieben, nur zum
   Vorschlag. LinkedIn wird nie direkt abgerufen; was Suchtreffer von
   öffentlichen Profilen zeigen, ist die Quelle. Ein nachdenkendes Modell
   braucht Platz: 6.000 Token für die Zuordnung, sonst kommt nur das
   Nachdenken an.

9. **Beim Veröffentlichen:** `docs/BETRIEB.md`, Abschnitt
   „Veröffentlichen". Version an drei Stellen, Tag `vX.Y.Z` baut die
   Abbilder (`release.yml`), das Chart wird immer als Paket geprüft
   (`olares-cli chart lint dist/beacon-X.Y.Z.tgz`), und **erst nach einer
   laufenden Installation auf einer Box** geht der Eintrag per PR in
   `bayerhazard/aimighty-market`. Die Regeln dahinter stehen im Skill
   `insilo/.claude/skills/olares-release/SKILL.md`.

10. **Bei Unsicherheit:** stoppen und Kai fragen.

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
