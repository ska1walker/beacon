# Betrieb und Entwicklung

## Lokal aufsetzen

Voraussetzungen: PostgreSQL 16, Python 3.11+, Node 22+.

```bash
# 1. Datenbank
brew services start postgresql@16
psql -d postgres -c "create role aicrm login password 'aicrm_dev_only';"
psql -d postgres -c "alter role aicrm createdb;"   # nur für die Tests
createdb -O aicrm aicrm
```

**Die Rolle darf kein Superuser sein, und die Migrationen laufen mit
genau dieser Rolle.** Beides ist keine Förmlichkeit:

- Ein **Superuser umgeht die Zeilensicherheit vollständig**, auch das
  `force row level security` aus Migration 0002. Eine Einrichtung mit
  Superuser sieht funktionierend aus und trennt die Mandanten nicht.
- Läuft die Migration unter einer *anderen* Rolle, gehören die Tabellen
  dieser anderen Rolle. Die Anwendung ist dann Nicht-Eigentümerin, und
  die Erstanlage von Nutzer und Organisation scheitert an den Policies
  auf den Identitätstabellen. Auf der Box gehören die Tabellen der
  injizierten Rolle — die lokale Einrichtung bildet das nach.

```bash
# 2. Schema
PGPASSWORD=aicrm_dev_only psql -h localhost -U aicrm -d aicrm \
  -f supabase/migrations/0001_initial_schema.sql
PGPASSWORD=aicrm_dev_only psql -h localhost -U aicrm -d aicrm \
  -f supabase/migrations/0002_rls_policies.sql

# 3. Backend
cd backend
python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"
.venv/bin/uvicorn app.main:app --port 8000

# 4. Oberfläche
cd frontend && npm install
BACKEND_URL=http://localhost:8000 npm run dev

# 5. Beispieldaten
python3 scripts/seed-dev.py
```

`backend/.env` trägt lokal `DEV_USER=kai`. Ohne Envoy gibt es keinen
`X-Bfl-User`-Kopf; dieser Wert tut so, als wäre jemand angemeldet. **Auf
der Box bleibt er leer** — dort ist ein fehlender Kopf ein Fehler und kein
Anlass, jemanden zu erfinden.

## Tests

```bash
cd backend && .venv/bin/python -m pytest
```

Die Tests legen eine eigene Datenbank `aicrm_test` an, spielen die
Migrationen ein und werfen sie danach weg. Sie laufen gegen echtes
Postgres, nicht gegen Attrappen — die Zeilensicherheit ist der Kern
dessen, was geprüft wird, und die gibt es nur in einer echten Datenbank.

Der wichtigste Test ist `test_mandanten_sehen_einander_nicht`. Er wurde
gegengeprüft: Nimmt man das `force row level security` aus Migration 0002
heraus, schlägt er fehl, und zwar mit „die eine Organisation sieht die
Firmen der anderen". Genau dieser Fehler wäre sonst erst aufgefallen,
wenn zwei Leute auf derselben Box arbeiten.

## Chart prüfen

```bash
bash scripts/check-chart.sh
```

Prüft Versionsgleichlauf, Namensgleichheit, verbotene Konstrukte
(`.Files.Get`, Helm-Hooks, NodePort), die Herkunft des Image-Tags und ob
die Migrations-ConfigMap noch zur Quelle passt. Läuft `helm lint` und
`helm template` mit.

Nach jeder Änderung an `supabase/migrations/`:

```bash
python3 scripts/regen-migrations.py
```

## Was noch nie passiert ist

**Das Chart ist auf keiner echten Olares-Box installiert worden.** Es
lintet, es rendert, und das eingebettete SQL kommt nachweislich
unversehrt heraus. Aber alles, was erst zur Laufzeit auffällt — das
Zusammenspiel mit dem injizierten Postgres, das Zeitfenster bis zum
`ns-owner`-Label, der Envoy vor der Oberfläche, der Weg der Kopfzeile
`X-Bfl-User` durch die Next.js-Weiterleitung — ist ungeprüft.

Die Reihenfolge bei der ersten Installation: erst die Abbilder bauen und
nach GHCR schieben, dann das Chart hochladen. Für den Ablauf gibt es im
Insilo-Repo den Skill `olares-release`.

## Sicherung

Eine Deinstallation über den Markt löscht die Datenbank. `/app/data`
überlebt sie, die Datenbank nicht.

Dagegen schreibt die Anwendung alle sechs Stunden einen vollständigen
Abzug nach `/app/data/sicherungen/` und liest ihn beim ersten Start nach
einer Neuinstallation von allein zurück. Der Abzug liegt mit Rechten
0600, weil er den Schlüssel zum Sprachmodell enthält.

Zwei Dinge, die man wissen muss:

- **Zurückgespielt wird nur in die erste Organisation der Box.** Meldet
  sich ein zweiter Mensch an, bekommt er eine leere Organisation. Ohne
  diese Bedingung wäre der Wiederanlauf ein Leck zwischen Mandanten.
- **Wiederherstellen überschreibt nichts.** Was heute da ist, bleibt; es
  wird nur ergänzt, was fehlt. Die Antwort nennt beide Zahlen getrennt.

Die Ausfuhr unter *Einstellungen → Sicherung* lädt denselben Abzug
herunter — **ohne** den Schlüssel zum Sprachmodell, denn diese Datei
verlässt die Box.

Von Hand geht weiterhin:

```bash
pg_dump -h <box> -U aicrm aicrm > aicrm-$(date +%F).sql
```

## Insilo anschließen

Nach einer Besprechung schickt Insilo ein signiertes Ereignis mit dem
fertigen Protokoll. In aicrm unter *Einstellungen → Eingehende Quellen*
eine Quelle anlegen, Adresse und Geheimnis kopieren und in Insilo unter
*Einstellungen → Webhooks* eintragen. Der Vertrag steht in
`insilo/docs/WEBHOOKS.md` und wird eingehalten, nicht neu erfunden.

Ein Protokoll landet direkt am Geschäft, wenn der Firmenname im Titel
steht und genau ein offenes Geschäft dazu existiert. Alles andere wartet
im Eingang — ein Protokoll am falschen Kunden ist schlimmer als eines,
das eine Minute wartet.

> **Offen: der Weg auf der Box.** Der Empfangspfad ist geprüft, die
> Zustellung nicht. Insilo müsste aicrm über dessen öffentliche Adresse
> erreichen, und davor sitzt der Envoy-Sidecar mit Authelia — derselbe
> Wall, an dem Insilo beim Sprachmodell gescheitert ist. Der
> wahrscheinliche Weg ist eine `options.policies`-Regel im
> OlaresManifest, die `^/api/eingang/` öffentlich stellt; die Signatur
> trägt die Authentifizierung an dieser Stelle ohnehin. Geprüft ist das
> nicht, und es lässt sich nur auf einer Box prüfen.
