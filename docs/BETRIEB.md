# Betrieb und Entwicklung

## Seit 0.2.0: Beacon, vorher aicrm

Am 5. September 2026 wurde das Produkt von **aicrm** in **Beacon**
umbenannt — Repo (`ska1walker/beacon`, GitHub leitet die alte Adresse
um), Abbilder (`ghcr.io/ska1walker/beacon-*`), Olares-Name, Namespace
(`beacon-<nutzer>`), Datenbank und Katalogeintrag. Was bleibt: die
Kopfzeilen `X-Aicrm-*` am Eingang (Alias) und die Lesbarkeit alter
Abzüge `aicrm-*.json`.

**Eine Umbenennung ist auf Olares eine Neuinstallation.** Die Kennung
ist `md5(<appname>)[:8]`, also `41b89d10`; die App heißt jetzt
`https://41b89d100.<nutzer>.<zone>`, der öffentliche Pfad `…101.`. So
lief der Umzug auf Kais Box, in dieser Reihenfolge: frischer Abzug über
`POST /api/sicherung`; Ablage `Data/beacon/sicherungen` von Hand angelegt
(uid 1000) und die Abzüge aus `Data/aicrm/sicherungen` hineinkopiert;
Beacon über den Markt installiert; erste Anmeldung — sie spielt den
neuesten Abzug zurück (`auth._einrichten`); Bestand nachgemessen;
erst dann aicrm deinstalliert.

Beim Nachmessen nicht hereinfallen: `select count(*)` ohne
Nutzerkontext liefert unter `FORCE ROW LEVEL SECURITY` immer 0. Zählen
nur über `acquire_as(<nutzer>)` — und `deleted_at` beachten, der Abzug
trägt auch weich Gelöschtes.

## Lokal aufsetzen

Voraussetzungen: PostgreSQL 16, Python 3.11+, Node 22+.

```bash
# 1. Datenbank
brew services start postgresql@16
psql -d postgres -c "create role beacon login password 'beacon_dev_only';"
psql -d postgres -c "alter role beacon createdb;"   # nur für die Tests
createdb -O beacon beacon
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
PGPASSWORD=beacon_dev_only psql -h localhost -U beacon -d beacon \
  -f supabase/migrations/0001_initial_schema.sql
PGPASSWORD=beacon_dev_only psql -h localhost -U beacon -d beacon \
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

Die Tests legen eine eigene Datenbank `beacon_test` an, spielen die
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
pg_dump -h <box> -U beacon beacon > beacon-$(date +%F).sql
```

## Insilo anschließen

Nach einer Besprechung schickt Insilo ein signiertes Ereignis mit dem
fertigen Protokoll. In Beacon unter *Einstellungen → Eingehende Quellen*
eine Quelle anlegen, Adresse und Geheimnis kopieren und in Insilo unter
*Einstellungen → Webhooks* eintragen. Der Vertrag steht in
`insilo/docs/WEBHOOKS.md` und wird eingehalten, nicht neu erfunden.

Ein Protokoll landet direkt am Geschäft, wenn der Firmenname im Titel
steht und genau ein offenes Geschäft dazu existiert. Alles andere wartet
im Eingang — ein Protokoll am falschen Kunden ist schlimmer als eines,
das eine Minute wartet.

> **Geprüft am 5. September 2026, zweimal — die erste Messung war
> falsch, und zwar am Hostnamen.** Olares adressiert einen Entrance nicht
> unter seinem Namen, sondern als `<appid><index>.<nutzer>.<zone>`:
> `appid` ist `md5(<appname>)[:8]` (für Beacon `4d3bf559`, auf jeder Box
> gleich), `index` die Position im Manifest, null-basiert. Systemapps wie
> `files.` oder `market.` tragen Namen — Nutzerapps nicht. Alles, was
> vorher unter `beacon.kaivostudio.olares.de` gemessen wurde, traf einen
> Hostnamen, den es nie gab; das 421 war die Antwort des Gateways auf
> einen unbekannten Host, keine Aussage über `authLevel`.
>
> Gemessen von außen, ohne Anmeldung, `GET /health`:
>
> | Entrance | authLevel | Adresse | Antwort |
> |---|---|---|---|
> | `beacon` (Index 0) | `internal` | `4d3bf5590.kaivostudio.olares.de` | **302** zur Anmeldung |
> | `beaconlinks` (Index 1) | `public` | `4d3bf5591.kaivostudio.olares.de` | **200** `{"status":"ok","teil":"oeffentlich"}` |
> | litellm `litellmapi` | `public` | `6aead52a1.…` und `llm.…` (eigener Name) | 401 von LiteLLM — durchgereicht |
>
> Über den öffentlichen Entrance: unbekanntes Token → 404, `/api/contacts`
> → 404. Der Container auf 8001 kennt die interne API nicht.
>
> Ein `internal`-Entrance hat also eine öffentliche Adresse; wer ohne
> Sitzung kommt, wird zur Anmeldung geschickt. Ob eine `policies`-Regel
> einen Pfad darunter für anonyme POSTs öffnet, ist damit **nicht
> gemessen** — die frühere Gegenprobe lief auf dem falschen Host. Der
> Insilo-Anschluss scheiterte an genau dieser Umleitung, nicht an einer
> fehlenden Tür.
>
> **Der zweite Entrance verschiebt die Adresse der App.** Mit nur einem
> Entrance hieß Beacon `4d3bf559.kaivostudio.olares.de` (ohne Index — so
> stand es auch in den eingefrorenen Helm-Werten der Erstinstallation).
> Seit dem zweiten Entrance heißt der erste `4d3bf5590.…`, und die alte
> Adresse antwortet 421 (gemessen 5.9.2026). Ein Lesezeichen auf die
> alte Adresse ist damit tot; der Weg über den Olares-Desktop stimmt.
> Wer noch einen Entrance hinzufügt, verschiebt nichts mehr — der Index
> bleibt.
>
> **Ein Entrance am Backend-Pod legt die App lahm.** Der Sidecar, den
> ein Entrance mitbringt, prüft *jeden* eingehenden Aufruf gegen Authelia
> — auch die des Frontends an `beacon-backend:8000/api`. Mit 0.1.10 hing
> `beaconlinks` am Backend-Pod; nach dem Markt-Upgrade antwortete jede
> API-Anfrage 401 (`ext_authz_denied` im Sidecar-Log), die Oberfläche
> zeigte „Anfrage fehlgeschlagen (401)“. Seit 0.1.12 hat der öffentliche
> Pfad sein eigenes Deployment `beacon-links`; das Backend bleibt ohne
> Entrance und ohne Sidecar. Regel: **Ein Entrance zeigt nur auf Pods, die
> sonst niemand aus dem Cluster aufruft.**
>
> **Was ein neuer Entrance bei einem Upgrade braucht.** `helm upgrade`
> tauscht die Workloads, liest aber das Manifest nicht neu ein: Nach dem
> Ausrollen von 0.1.10 per Helm fehlte `beaconlinks` in `spec.entrances`,
> und der Backend-Pod hatte keinen Envoy-Sidecar. Erst das Upgrade über
> den Markt (Upload-Quelle) trug den Entrance ins Application-Objekt, in
> `spec.settings.policy` und injizierte den Sidecar in den nächsten Pod.
> Ein neuer Entrance kommt deshalb **nur über den Markt** auf eine Box;
> `scripts/box-abgleich.py` zeigt Manifest und Objekt nebeneinander und
> nennt die echten Adressen.
>
> Ein Rest bleibt, und der liegt bei Olares: `status.entranceStatuses`
> wird nur beim ersten Anlegen aus dem Manifest gefüllt
> (`application_controller.go`, `createApplication`); `updateApplication`
> überschreibt `spec.entrances`, fasst den Status aber nicht an, und der
> `EntranceStatusManagerController` aktualisiert nur Einträge, die schon
> da sind. Nach einem Upgrade fehlt der neue Entrance im Status — für
> die Erreichbarkeit ist das **ohne Belang** (gemessen: Eintrag entfernt,
> 200; Eintrag gesetzt, 200), er fehlt nur in der Statusanzeige des
> Markts. Auf Kais Box wurde der Eintrag von Hand nachgetragen, so wie
> eine Neuinstallation ihn schreiben würde.

> **Ohne die Box zu öffnen bleiben zwei Wege**, und beide sind
> tragfähiger, als sie klingen: der Service-Provider-Weg für Apps auf
> derselben Box (Olares' eigener Mechanismus, Constraint 4), und —
> naheliegender — **Beacon holt selbst**. Ausgehend sind 443 und 80 offen;
> ein Postfach per IMAP abzufragen oder eine Formular-API zu pollen
> braucht keine einzige offene Tür nach innen.


## Versand — SMTP, Einwilligung, öffentliche Links

Seit 0.1.11 schickt Beacon selbst: über ein gewöhnliches SMTP-Konto
(*Einstellungen → Versand*). Daraus kommen Ticket-Antworten, die
Bestätigungsmail (Double-Opt-In) und die Ansprache aus dem Kontakt.
Marketing-Post ist davon getrennt (*Marketing-Versand*: dasselbe Konto
oder Brevo) — HubSpot trennt beides aus demselben Grund: Ein gesperrtes
Marketing-Konto darf keine Antwort an einen Kunden aufhalten.

**Der Knopf „Testmail an mich“ ist der Beweis.** Zugangsdaten, die erst
bei der ersten Antwort scheitern, sind keine Einrichtung. Was scheitert,
steht als *Letzter Versuch* im Block und in `mails.fehler`.

**Jede Mail ist zuerst eine Zeile in `mails`, dann ein Versand.** Ein
abgelehnter Versand bleibt mit Grund stehen und wird dreimal mit
wachsendem Abstand wiederholt (`app/versand.py`, Schleife in `main.py`,
alle 30 s). Erst dann `fehlgeschlagen`. Ticket-Uhr und Verlauf werden
erst geschrieben, wenn die Mail wirklich draußen ist — eine Antwort, die
nicht ankam, ist keine.

**Der Faden.** Kam ein Ticket per Mail (Postfach oder Eingang), trägt die
Antwort `In-Reply-To`/`References` mit der Message-ID der Anfrage, und
die Kennung `[T-2026-0042]` steht im Betreff. Danach: erste Antwort
festgehalten, Ticket in „wartet auf Kontakt“.

**Einwilligung.** Marketing-Post geht nur an `bestaetigt` oder
`bestandskunde`. `bestaetigt` entsteht ausschließlich über den Link in
der Bestätigungsmail (sieben Tage gültig, einmalig); es gibt bewusst
keinen Knopf dafür. `bestandskunde` (§7 Abs. 3 UWG) setzt ein Mensch am
Kontakt, mit Namen im Beleg. Jede Marketing-Mail trägt den Abmeldelink
in `List-Unsubscribe` und im Text; der Link funktioniert immer.

**Die Adresse der öffentlichen Links** (Bestätigen, Abmelden, Klick) ist
`https://<appid>1.<nutzer>.<zone>` — der zweite Entrance. Das Chart reicht
`.Values.domain.beacon` als `APP_DOMAIN` ins Backend, das Backend leitet
daraus ab; *Einstellungen → Marketing-Versand* zeigt, was gilt, und
erlaubt einen eigenen Wert (eigene Domain, oder eine Box, die ihre
Domain nicht mitteilt). Ohne Adresse geht keine Bestätigungsmail hinaus,
und der Block sagt das.

## Listen und Kampagnen

Seit 0.2.1. Eine **Liste** sagt, wen man meint — statisch (von Hand
gefüllt, auch per Stapel aus der Kontaktliste) oder aktiv (ein Filter im
Format der Ansichten; wer passt, ist drin). Ob man jemandem schreiben
darf, sagt der **Kontakt** (`marketing_einwilligung`, jetzt auch als
Filterfeld). Eine **Kampagne** ist Betreff, Text und Liste; beim Start
schreibt sie jedem berechtigten Empfänger eine Zeile ins Buch (`mails`,
`art = marketing`), die Schleife schickt. Wer keine Einwilligung oder
Adresse hat, wird übergangen und gezählt — die Liste bleibt unangetastet.

Jeder Link im Text wird je Empfänger zu einem Klick-Link
(`oeffentliche_links`, `art = klick`, mit `kampagne_id`), der Abmeldelink
hängt ebenfalls an der Kampagne. Kennzahlen (gesendet, wartend,
fehlgeschlagen, Klicks, Klicker, abgemeldet) entstehen beim Lesen aus
den Zeilen; `abgeschlossen` ist `laeuft` ohne wartende Zeile. Marketing-
Post geht über das SMTP-Konto oder — wenn gewählt und eingerichtet —
über Brevo (`app/versand.py`, `marketing_konto`). Vorlagen sind Betreff
und Text mit Platzhaltern, mehr nicht.

Die Einstellungen sind seit 0.2.1 in fünf Unterpunkte gegliedert (Firma
und Team, Vertrieb, E-Mail, KI und Programme, Daten); jeder Block sagt in
einem Satz, wozu er da ist, und hält das Kleingedruckte hinter dem
Symbol (`components/erklaerung.tsx`).

## Post anschließen — Relay oder ein anderer Dienst

> **Seit 0.2.2 ist die Art einer Quelle Teil des Vertrags.** Eine Quelle
> der Art `relay` öffnet nur `/api/post/eingang/<id>`; `insilo`, `api`,
> `bot`, `formular` öffnen nur `/api/eingang/<id>`; `email` ist das eigene
> Postfach und öffnet nichts. Passt die Art nicht, antwortet der Pfad 401
> — dieselbe Antwort wie bei falscher Signatur. Bestehende Quellen tragen
> die Vorgabe `insilo` und laufen weiter; die Prüfung steht als
> `CHECK … NOT VALID`, weil die Migration unter FORCE RLS alte Zeilen
> weder lesen noch berichtigen kann.
>
> **Ausgehende Post trägt `X-Post-Delivery-ID`** (aus `delivery_id` im
> Auftrag, sonst vom Server vergeben) und wird bei Ausfall oder 5xx bis
> zu dreimal mit Pausen von 1 s und 3 s wiederholt — stets mit derselben
> Kennung. Ein zweiter Auftrag mit derselben Kennung schickt nichts mehr,
> sondern liefert den vorhandenen Verlaufseintrag (`wiederholung: true`).
> Die `message_id` aus der Antwort des Dienstes steht am Verlaufseintrag
> (`payload.message_id`) — die Grundlage für jedes spätere `in_reply_to`.

E-Mails gehen nicht aus Beacon selbst hinaus und kommen nicht direkt
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

**Hinaus** — Beacon schickt an die unter *Einstellungen → Postausgang*
eingetragene Adresse einen signierten POST mit
`{"to","from","subject","text","in_reply_to","sent_at"}` und der
Kopfzeile `X-Post-Signature`. Der Dienst verschickt; Beacon hält die
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
| SearXNG (empfohlen, läuft auf der Box) | `https://<searxng-route>.<user>.olares.com` — Beacon hängt `/search?format=json` an | meist keiner; sonst als `Authorization: Bearer` |
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
Dockerfile setzt es auf `http://beacon-backend:8000`; 0.1.1 lief ohne
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

# 2. Tag pushen — release.yml baut ghcr.io/ska1walker/beacon-{frontend,backend}:0.1.1
#    (öffentlich, amd64) und legt dist/beacon-0.1.1.tgz als Artefakt ab
git tag v0.1.1 && git push origin main v0.1.1
gh run watch

# 3. Chart packen und mit dem Olares-Prüfer ansehen — immer das Paket,
#    nie den Ordner (der Prüfer verlangt Ordnername == Chart-Name)
helm package olares -d dist
olares-cli chart lint dist/beacon-0.1.1.tgz --with-rbac --with-security-context

# 4. Auf der eigenen Box installieren, bevor irgendetwas in einen Markt geht
olares-cli profile login --olares-id <id>       # macht Kai selbst (Browser, TOTP)
olares-cli market upload dist/beacon-0.1.1.tgz
olares-cli market install beacon
```

**Erst ausrollen, dann hochladen.** Eine App, die nie `running`
erreicht hat, gehört in keinen Katalog.

**Der Markt** ist die eigene Quelle von aimighty
(`bayerhazard/aimighty-market`, Cloudflare Pages). Ein Eintrag besteht
aus dem Block in `functions/_apps.ts` und dem base64-gepackten Chart
unter dem Schlüssel `beacon-<version>.tgz` in `functions/_lib.ts`. Kai
hat dort nur Leserechte — der Weg ist Fork, Branch, Pull Request an
Marc. Vor dem PR alle vier Endpunkte lokal beweisen
(`npx wrangler pages dev functions --port 8788`): `/api/v1/appstore/info`
listet die App, `/api/v1/applications/beacon/chart` liefert die Bytes
sha256-gleich, `/api/v1/appstore/hash` hat sich bewegt. Insilos
Einreichung (PR #1 dort) ist die Vorlage; die Regeln stehen im Skill
`insilo/.claude/skills/olares-release/SKILL.md`.

**Was auf der Box noch offen ist:** die Empfangspfade
`/api/eingang/…` und `/api/post/eingang/…` liegen hinter dem
Envoy-Sidecar des Frontends. Insilo und Relay rufen sie ohne
Authelia-Keks — dafür braucht es voraussichtlich eine `options.policies`-
Regel mit `level: public` für genau diese Pfade. Das lässt sich nur auf
einer echten Box messen.
