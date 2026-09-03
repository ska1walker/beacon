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


## Post anschließen — Relay oder ein anderer Dienst

E-Mails gehen nicht aus aicrm selbst hinaus und kommen nicht direkt
herein. Beides läuft über einen Dienst auf der Box — Marcs Relay, die
Outlook-Alternative. Weil dessen Schnittstelle beim Bau nicht vorlag,
gilt ein **eigener, kleiner Vertrag**, denselben Bauplan wie beim
Insilo-Eingang: signierter POST, HMAC-SHA256 über den rohen Body,
Idempotenzschlüssel. Er steht in `backend/app/routers/post.py`.

**Hinein** — der Dienst ruft `POST /api/post/eingang/<Quelle>` mit den
Kopfzeilen `X-Post-Event: mail.received`, `X-Post-Delivery-ID`,
`X-Post-Signature: sha256=…` und dem Body
`{"message_id","from","to":[…],"subject","text","received_at"}`. Die
Quelle wird unter *Einstellungen → Eingehende Quellen* angelegt (Art
`relay`), das Geheimnis einmalig gezeigt. Kennt das CRM die
Absenderadresse, liegt die Mail als Verlaufseintrag am Kontakt; sonst
wartet sie im Eingang.

**Hinaus** — aicrm schickt an die unter *Einstellungen → Postausgang*
eingetragene Adresse einen signierten POST mit
`{"to","from","subject","text","in_reply_to","sent_at"}` und der
Kopfzeile `X-Post-Signature`. Der Dienst verschickt; aicrm hält die
Nachricht im Verlauf fest. Nichts geht von allein hinaus — das Modell
entwirft, ein Mensch drückt auf Senden.

> **Offen:** Relays tatsächliche Schnittstelle. Liegt sie vor, ist ein
> kleiner Übersetzer auf Relay-Seite oder eine Anpassung in `post.py`
> nötig — der Vertrag hier ist bewusst so schmal, dass beides ein
> Nachmittag ist.

## Anreicherung anschließen — Suchdienst

Neue Firmen und Kontakte werden von selbst aus öffentlichen Quellen
ergänzt (`backend/app/anreicherung.py`). Ohne Einrichtung liest die
Anreicherung nur die **Website der Firma**: Startseite, Impressum,
Kontakt-, Team- und Über-uns-Seiten, dazu die intern verlinkten Seiten
mit solchen Namen. Das genügt für Anschrift, Telefon, Branche und
Beschreibung — und für Ansprechpartner, die auf der Team-Seite stehen.

Für alles darüber hinaus braucht sie einen **Suchdienst** unter
*Einstellungen → Anreicherung*:

| Dienst | Adresse | Schlüssel |
|---|---|---|
| SearXNG (empfohlen, läuft auf der Box) | `https://<searxng-route>.<user>.olares.com` — aicrm hängt `/search?format=json` an | meist keiner; sonst als `Authorization: Bearer` |
| Brave Search | `https://api.search.brave.com/res/v1/web/search` | Pflicht, geht als `X-Subscription-Token` |

Mit Suchdienst findet die Anreicherung die Website, wenn nur der Name
bekannt ist, und holt die **LinkedIn-Treffer**: Unternehmensseite
(`linkedin.com/company/…`) und Personenprofile (`linkedin.com/in/…`) aus
Titel und Kurztext der Suchergebnisse. LinkedIn selbst wird nie
abgerufen — das ließe die Seite ohne Anmeldung nicht zu und die
Nutzungsbedingungen verbieten es. Bei SearXNG muss das JSON-Format
freigeschaltet sein (`search.formats: [html, json]` in der
`settings.yml`).

**Was das Modell darf.** Es ordnet Fundstellen den Feldern zu und nennt
zu jedem Wert die Quelle. Kontaktdaten (E-Mail, Telefon, LinkedIn,
Website, Straße, PLZ, Beschäftigtenzahl) müssen **wörtlich** in der
Quelle stehen, sonst fallen sie weg. Branche, Position und Beschreibung
dürfen gefolgert sein und sind so gekennzeichnet. Ein Modell, das vor
der Antwort nachdenkt, bekommt 6.000 Token — mit weniger kam auf der
Box nur das Nachdenken an.

**Was geschrieben wird.** Vorgabe ist *Leere Felder füllen*: Was am
Datensatz leer war und belegt ist, steht nach dem Lauf drin, mit
Protokolleintrag (`enrich`) und Verlaufseintrag. Abweichungen zu
vorhandenen Werten und die Beschreibung bleiben ein Vorschlag mit
Quelle, den ein Mensch am Datensatz übernimmt oder verwirft. Wer nichts
ohne Klick geschrieben haben will, stellt auf *Nichts* um; wer keinen
Lauf beim Anlegen will, schaltet *Beim Anlegen von selbst anreichern*
ab — der Knopf am Datensatz bleibt.

Jeder Lauf liegt in `anreicherungen`: gelesene Adressen mit Bytes,
gestellte Suchanfragen, Vorschlag, Übernommenes. Das ist der Nachweis,
was die Box verlassen hat.

## Veröffentlichen — Abbilder, Chart, Markt

Der Weg ist derselbe wie bei Insilo, nur kürzer. Die Version steht an
**drei** Stellen und muss überall gleich sein — `scripts/check-chart.sh`
bricht sonst ab:

- `olares/Chart.yaml` → `version` **und** `appVersion`
- `olares/OlaresManifest.yaml` → `metadata.version` **und** `spec.versionName`
- `OlaresManifest.yaml` in der Wurzel ist eine **Kopie** des Chart-Manifests
  (`cp olares/OlaresManifest.yaml .`) — Marcs Regel für den Markt, der
  Guard in `check-chart.sh` verlangt Gleichheit

Das Proxy-Ziel des Frontends (`BACKEND_URL`) wird **beim Bau**
eingebrannt — `next.config.mjs` liest es in `rewrites()`, und das
Standalone-Abbild kennt zur Laufzeit keine Rewrites mehr. Das
Dockerfile setzt es auf `http://aicrm-backend:8000`; 0.1.1 lief ohne
diese Zeile gegen `localhost` und jede API-Anfrage endete mit 500.

Zwei Manifest-Angaben, die auf der Box den Unterschied machen:
`options.apiTimeout: 0` (sonst kappt der Envoy-Sidecar jede Antwort nach
15 Sekunden, und das Modell antwortet synchron im Request) und
`options.dependencies` mit `>=1.12.6-0` (v3-Pflichtform). Jede
Chart-Änderung, auch eine an Beschreibungen, braucht eine neue Version:
Der Katalog-Hash entsteht aus Name und Version, sonst synchronisiert
Olares nicht.

Der Image-Tag steht nirgends: Er folgt `Chart.AppVersion`
(`values.yaml` trägt `tag: ""`). Das ist Absicht — Olares spielt beim
Aktualisieren die Werte der Erstinstallation zurück, die Chart-Metadaten
kommen frisch an (Insilo v0.1.80, ausführlich in
`insilo/docs/HANDOFF.md`).

```bash
# 1. Version an den drei Stellen setzen, prüfen, committen
bash scripts/check-chart.sh
git commit -am "release: v0.1.1"

# 2. Tag pushen — release.yml baut ghcr.io/ska1walker/aicrm-{frontend,backend}:0.1.1
#    (öffentlich, amd64) und legt dist/aicrm-0.1.1.tgz als Artefakt ab
git tag v0.1.1 && git push origin main v0.1.1
gh run watch

# 3. Chart packen und mit dem Olares-Prüfer ansehen — immer das Paket,
#    nie den Ordner (der Prüfer verlangt Ordnername == Chart-Name)
helm package olares -d dist
olares-cli chart lint dist/aicrm-0.1.1.tgz --with-rbac --with-security-context

# 4. Auf der eigenen Box installieren, bevor irgendetwas in einen Markt geht
olares-cli profile login --olares-id <id>       # macht Kai selbst (Browser, TOTP)
olares-cli market upload dist/aicrm-0.1.1.tgz
olares-cli market install aicrm
```

**Erst ausrollen, dann hochladen.** Eine App, die nie `running`
erreicht hat, gehört in keinen Katalog.

**Der Markt** ist die eigene Quelle von aimighty
(`bayerhazard/aimighty-market`, Cloudflare Pages). Ein Eintrag besteht
aus dem Block in `functions/_apps.ts` und dem base64-gepackten Chart
unter dem Schlüssel `aicrm-<version>.tgz` in `functions/_lib.ts`. Kai
hat dort nur Leserechte — der Weg ist Fork, Branch, Pull Request an
Marc. Vor dem PR alle vier Endpunkte lokal beweisen
(`npx wrangler pages dev functions --port 8788`): `/api/v1/appstore/info`
listet die App, `/api/v1/applications/aicrm/chart` liefert die Bytes
sha256-gleich, `/api/v1/appstore/hash` hat sich bewegt. Insilos
Einreichung (PR #1 dort) ist die Vorlage; die Regeln stehen im Skill
`insilo/.claude/skills/olares-release/SKILL.md`.

**Was auf der Box noch offen ist:** die Empfangspfade
`/api/eingang/…` und `/api/post/eingang/…` liegen hinter dem
Envoy-Sidecar des Frontends. Insilo und Relay rufen sie ohne
Authelia-Keks — dafür braucht es voraussichtlich eine `options.policies`-
Regel mit `level: public` für genau diese Pfade. Das lässt sich nur auf
einer echten Box messen.
