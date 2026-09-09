# Betrieb und Entwicklung

## Seit 0.2.0: Beacon, vorher aicrm

Seit dem Abend des 5. September ist die Box aus dem **Aimighty-Katalog**
installiert (`market_source: market.aimighty`), nicht mehr per Upload —
neue Versionen kommen über Markt → *Updates*. Der Wechsel war eine
Deinstallation plus Installation; der Abzug in `Data/beacon/sicherungen`
hat den Bestand zurückgebracht. „My Olares“ zeigt je Reiter nur die Apps
der jeweiligen Quelle; der Katalog selbst steht im Reiter „AI“ und in der
Suche.

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

## Was unter /app/data liegt

Drei Dinge, und `/app/data` ist der einzige Pfad, den Olares als dauerhaft
zusichert — er überlebt eine Deinstallation, die **Datenbank nicht**.

| | Was |
|---|---|
| `sicherungen/` | Der Abzug als JSON, stündlich neu, die letzten Stände nebeneinander |
| `podcasts/` | Die erzeugten Gesprächsvorbereitungen als MP3 |
| `tresor.key` | Der Schlüssel für die Zugangsdaten, 0600 |

**Der Abzug enthält alles, was ein Mensch in Beacon ändert.** Gemessen am
9. September: 21 Tabellen mit Inhalt (Firmen, Kontakte, Geschäfte,
Aufgaben, Tickets, Angebote, Kampagnen, Mails, Eigenschaftsdefinitionen,
Webhook-Quellen, Protokoll), dazu die 66 Felder der Organisation
(Briefkopf, SMTP, IMAP, Sprachmodell, Suche, Sprachausgabe, Fristen) und
je Person Name, Kennung, Rolle, Favoriten, Passwort-Hash und die
Absendereinstellungen.

**Zwei Wachen halten das fest.** Auf Tabellenebene bricht ein Test ab,
sobald eine neue Tabelle weder im Abzug steht noch ausdrücklich
ausgenommen ist. Auf **Spaltenebene** dasselbe für `users` — und die
zweite gibt es, weil die erste nicht ausreichte: Die Absenderadressen aus
0.6.5 hingen an `users`, und `users` steht ausdrücklich in `AUSGENOMMEN`.
Sie fehlten still im Abzug, bis jemand danach fragte.

**Die Zugangsdaten stehen im Abzug verschlüsselt** (seit 0.6.6). Damit
gehören Abzug und `tresor.key` zusammen: Wer den Ordner sichert, sichert
beides — wer nur die JSON-Dateien mitnimmt, hat die Zugangsdaten nicht.

Nicht im Abzug, mit Absicht: Sitzungen und Anmeldeversuche (eine
zurückgespielte Sitzung wäre ein Wiedereinspielen von Zugängen),
`created_at`, `last_seen_at` und `deleted_at` (entstehen neu) sowie
`gesperrt_bis` (eine Bremse von gestern erbt niemand).

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

**Seit 0.3.2: Sicherung nach jeder Änderung, samt Einstellungen.**
Die Schleife sieht alle fünf Minuten nach (`sicherung_pruefung_minuten`)
und schreibt nur, wenn sich der Fingerabdruck des Abzugs bewegt hat
(`abzug_kennung`, ohne Zeitstempel) — spätestens nach
`sicherung_intervall_stunden`, und einmal beim Herunterfahren. Der Abzug
trägt jetzt auch `listen`, `listen_mitglieder`, `vorlagen`, `kampagnen`
und `audit_log`; ein Test (`test_jede_tabelle_ist_im_abzug_oder_ausdruecklich_nicht`)
bricht, sobald eine neue Tabelle weder in `TABELLEN` noch in
`AUSGENOMMEN` steht. Die Spalten, die auf `users` zeigen, kommen aus den
Fremdschlüsseln der Datenbank (`_nutzerspalten`), nicht mehr aus einer
Liste — die hatte `anreicherungen.created_by` vergessen, und jede
Wiederherstellung mit einem Anreicherungslauf wäre daran gescheitert.

**Die Einstellungen werden zurückgespielt.** Bis 0.3.1 standen sie im
Abzug, kamen aber nie zurück: Sprachmodell, Suchdienst, SMTP, Postfach
waren nach einer Neuinstallation weg. Beim Wiederanlauf (erste Anmeldung
in eine leere Datenbank) gelten sie ganz (`frisch=True`), bei einer
Wiederherstellung von Hand füllen sie nur leere Felder.

**Doppelte Ticket-Pipelines.** Bis 0.3.1 prüfte der Start ohne
Nutzerkontext, ob eine Ticket-Pipeline da ist; unter Zeilensicherheit
sah er nie eine und legte bei jedem Start eine weitere „Anliegen“ an —
auf Kais Box waren es 16. Der Start prüft jetzt mit Kontext und räumt
Dubletten ohne Tickets weg (`_ticketpipelines_bereinigen`), die älteste
bleibt.

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

## Jeder unter seinem eigenen Namen — Absenderadressen

Bis 0.6.4 hatte eine Organisation genau **einen** Absender
(`org_settings.smtp_absender`). Sobald zwei Menschen in einem Bestand
arbeiten, ist das falsch: Marcs Angebot ging als Kai hinaus, und der
Empfänger sah einen Namen, mit dem er nie gesprochen hatte.

Seit 0.6.5 trägt jeder Mensch seine eigene Adresse — unter *Einstellungen ›
E-Mail › Ihre Absenderadresse*. Jeder setzt **nur seine eigene**; der Pfad
`PUT /api/mitglieder/wer/absender` kennt keine Kennung, sondern nur „wer
gerade handelt".

### Zwei Wege, und die Wahl trifft der Mailanbieter

**Eigene Adresse auf dem Konto der Organisation.** Nur `From` wechselt,
angemeldet wird weiter mit dem Konto aus den Einstellungen. Ein Feld, und
es funktioniert bei Anbietern, die eine fremde Absenderadresse derselben
Domain durchlassen. Manche tun das nicht — one.com etwa weist je nach
Tarif eine `From` zurück, die nicht dem angemeldeten Postfach entspricht.
Dann steht der Grund in der Zeile in `mails`, nicht im Verborgenen.

**Eigene Zugangsdaten.** Wer sein eigenes Postfach hat, trägt Server,
Benutzer und Passwort ein und meldet sich selbst an. Das geht immer,
kostet aber ein Postfach je Person.

### Die Domainschranke ist kein Formalismus

Auf dem gemeinsamen Konto ist nur eine Adresse **derselben Domain**
erlaubt. Ohne diese Schranke könnte jedes Mitglied über das Konto der
Organisation als beliebige Adresse schreiben — als der Geschäftsführer
eines Kunden zum Beispiel. Wer eigene Zugangsdaten hinterlegt, meldet sich
selbst an und darf deshalb führen, was sein Anbieter durchlässt. Geprüft
wird beim Speichern **und** beim Versand.

### Wer schickt, hängt an `mails.created_by`

Nicht daran, wer die Schleife anstößt. Sonst ginge Marcs Angebot als Kai
hinaus, sobald Kai als Nächster etwas versendet. Dieselbe Kennung schreibt
auch die Absenderadresse: bei geteiltem Olares-Zugang der gewählte
Sitzplatz, mit eigener Anmeldung man selbst.

**Marketing bleibt beim Absender der Organisation.** Eine Kampagne kommt
von der Firma, nicht von einem Menschen, und der Abmeldelink hängt an
derselben Adresse.

### Die Antwort soll im Bestand landen

Beacon liest genau **ein** Postfach je Organisation. Schickt jemand unter
eigener Adresse, käme die Antwort dort an, wo niemand sie einliest — der
Faden im CRM bliebe stumm. Deshalb trägt jede Mail `Reply-To` auf das
Postfach der Organisation, **sofern eines eingerichtet ist**. Ist keines
da, sagt die Einstellungsseite genau das, statt etwas zu versprechen.

Tests: `backend/tests/test_versand.py` — Hausadresse ohne Eintrag, nur das
`From` wechselt, fremde Domain abgewiesen, eigene Zugangsdaten führen
alles, kein Hauskonto hilft nicht, `Reply-To` gesetzt und bei gleicher
Adresse weggelassen, und der ganze Weg mit zwei Menschen über ein Konto.

## Suchen oder fragen

Seit 0.2.4 ein Feld für beides, links unter der Marke, ⌘K/Strg+K von
überall. Beim Tippen kommen sofort Treffer über Firmen, Kontakte,
Geschäfte, Tickets, Listen und Kampagnen (`/api/suche`, `ilike`, fünf je
Art, nach Aktualität) — das kostet nichts. Sieht der Text wie eine Frage
aus (Fragezeichen oder vier Wörter), steht darunter „Frage stellen ↵“;
erst dann läuft das Modell über `/api/fragen`, und die Antwort mit
Fundstellen erscheint in der Palette. Die Seite „Fragen“ bleibt als
Verlauf; die Suchfelder in den Listen bleiben, sie sind Filter.

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

**Region.** Seit 0.3.0 geht ein Länderkürzel mit (*Einstellungen → KI
und Programme → Region der Suche*, Vorgabe DE): Brave als `country`,
SearXNG als Sprache `de-DE`. Ohne Region liefert „Baustoffhandel“ Fürth,
wenn man Tecklenburg meint.

**SearXNG ist auf einer Heim-Box nicht verlässlich.** Es fragt Google,
Bing, DuckDuckGo und Startpage ohne Schlüssel — und die sperren einen
Selbstbetreiber mit fester IP nach wenigen Anfragen für Stunden bis
Tage. Gemessen am 6. September 2026 aus Beacons Namespace heraus: JSON
in 0,4 s, aber null Treffer, alle Maschinen `Suspended` oder `CAPTCHA`;
Bing lieferte für drei verschiedene Anfragen dieselben zehn Treffer, also
eine Abwehrseite. Beacon erkennt das seit 0.3.0 am Feld
`unresponsive_engines` und meldet *„Der Suchdienst ist gerade gesperrt“*
statt „nichts gefunden“ (`SucheGestoert` in `anreicherung.py`). Für ein
CRM, das je Anlegen fünf bis zehn Anfragen stellt, ist Brave der
tragfähige Weg; SearXNG bleibt als Wahl erhalten.

## Beschreiben statt tippen — Firma und Kontakt finden

Seit 0.3.0 beginnt der Anlegen-Dialog mit einer Wegwahl: **Beschreiben**
oder **Hineinwerfen** (Signatur, Visitenkarte, wie bisher). Beschreiben
nimmt einen Satz wie „Baustoffhandel im Tecklenburger Land, der
Geschäftsführer heißt vermutlich Sebastian“ und arbeitet in drei
Schritten (`backend/app/finden.py`, Endpunkte unter `/api/finden`):

1. **Kandidaten** (`POST /api/finden/kandidaten`). Die Beschreibung geht
   zweimal an den Suchdienst — pur und mit „Impressum“. Das Modell nennt
   aus den Treffern bis zu vier Firmen mit Website; Verzeichnisse
   (Gelbe Seiten, LinkedIn, Northdata …) sind keine Kandidaten, und eine
   Website, die in keinem Treffer steht, fällt weg. Dazu liest es aus der
   Beschreibung, was über die Person gesagt ist (Vorname, Nachname,
   Rolle). Ein Mensch wählt.
2. **Firma** (`POST /api/finden/firma`). Dieselbe Anreicherung wie am
   Datensatz — Impressum, Kontaktseite, LinkedIn-Treffer — nur ohne
   Datensatz. Name, Website und Domain kommen vom Kandidaten.
3. **Person** (`POST /api/finden/kontakt`). Team-, Impressums- und
   Kontaktseiten der Firma, gefiltert auf den Namen, plus Suchtreffer.
   Gefunden ist eine Person erst, wenn eine gelesene Quelle ihren
   **Nachnamen** nennt; der Vorname bleibt nur mit Beleg. „Vermutlich
   Sebastian“ wird nicht zu einem Kontakt, wenn ihn niemand nennt.
   Passt niemand, kommen unter `alternativen` die Personen zurück, die
   die Quellen bei dieser Firma nennen (Geschäftsführung, Inhaber,
   Ansprechpartner) — als Wahl in der Maske, nicht als Wert. Gemessen am
   6. September 2026 an „Baustoffhandel Tecklenburger Land, Geschäftsführer
   vermutlich Sebastian“: Firma vollständig belegt aus Impressum und
   LinkedIn-Treffer; die Geschäftsführer heißen laut Impressum anders,
   Sebastian Specht ist dort „verantwortlich für den Inhalt“.

4. **Personen bei einer Firma** (`POST /api/finden/personen`, seit 0.3.5).
   Ohne eine bestimmte Person zu meinen: alle, die Team-, Kontakt- und
   Impressumsseite und die Suchtreffer bei dieser Firma nennen, mit Rolle
   und wörtlich belegten Kontaktdaten. Ein Wunsch wie „Einkauf“ lenkt
   Suche und Reihenfolge. Die Maske zeigt sie als Auswahl: Im
   Firmen-Dialog läuft die Suche von selbst an, sobald eine Firma gewählt
   ist, und die gewählten Personen entstehen mit der Firma
   (`Anlegen, mit 2 Kontakten`); auf der Firmenseite unter Kontakte →
   *Finden* legt „als Kontakte anlegen“ sie direkt an, wer schon da ist,
   trägt „schon im Bestand“. Herkunft der so angelegten Kontakte:
   `Recherche`.

Die Antwort hat die Form eines Erfassungsvorschlags (`felder`) plus
`belege` je Feld (Quelle, wörtlich belegt) und `quellen` mit den
Suchanfragen, die den Suchdienst verlassen haben. Die Maske füllt nur
leere Felder und zeigt darunter je Quelle, welche Felder von ihr
stammen. **Gespeichert wird nichts** — Anlegen drückt ein Mensch über
die gewohnten Endpunkte; die Dublettenprüfung aus `erfassen.py` läuft
vorher.

Voraussetzungen: Sprachmodell (409 ohne) und für Schritt 1 ein
Suchdienst (409 ohne, 503 wenn gesperrt). Von der Firmenseite aus steht
die Firma fest; dann sucht der Dialog nur die Person und nimmt die
Beschreibung als Rolle.

Nachbau für die eigene Prüfung ohne Brave-Schlüssel: ein kleiner
HTTP-Server, der `/search` im SearXNG-Format, `/v1/chat/completions`
im OpenAI-Format und drei Seiten einer Firma liefert — beide Adressen
unter Einstellungen eintragen, dann läuft der Dialog gegen bekannte
Antworten. Die Tests in `backend/tests/test_finden.py` tun dasselbe
mit `httpx.MockTransport`.

## Erkenntnisse — aus Gesprächsnotizen lernen

Seit 0.3.6 gibt es die Seite *Erkenntnisse*: Was Kunden in Gesprächen
über die Produkte sagen, gebündelt zu Themen, je Thema mit dem, was das
fürs Produkt heißt. Zwei Schritte (`backend/app/erkenntnisse.py`):

1. **Aussagen ziehen.** Verlaufseinträge der Arten Notiz, Anruf, E-Mail,
   Termin mit mindestens 40 Zeichen Text werden in Stapeln von sechs ans
   Modell gegeben. Je Aussage: Art (Lob, Kritik, Wunsch, Einwand, Frage),
   Produkt, ein neutraler Satz und das **Zitat aus der Notiz** — ohne
   Zitat, das in der Notiz steht, fällt die Aussage weg. Jede Notiz wird
   genau einmal gelesen (`auswertungen`); die Aussagen bleiben
   (`aussagen`).
2. **Themen bilden.** Alle Aussagen des Zeitraums (höchstens 300) gehen
   gebündelt ans Modell; es nennt Themen mit Zuordnung, Bedeutung und
   Vorschlag. Ein Thema ohne zugeordnete Aussage fällt weg, jede Aussage
   zählt nur einmal. Der Lauf liegt in `themenlaeufe` mit Fortschritt
   (`gelesen`/`gesamt`/`schritt`), damit die Seite ihn zeigen kann.

Endpunkte: `GET /api/erkenntnisse?tage=90` (letzter Lauf des Zeitraums,
Aussagen, Zähler je Art, noch nicht gelesene Notizen),
`POST /api/erkenntnisse/auswerten {tage}` startet den Lauf im
Hintergrund (202; 409 ohne Modell oder wenn einer läuft). Auf der Box
dauert ein Lauf mit vierzig Notizen und dem Denkmodell einige Minuten;
die Seite fragt alle drei Sekunden nach. Jedes Thema zeigt die
Gespräche dahinter mit Zitat, Firma und Datum — niemand muss dem Modell
glauben. Die drei Tabellen stehen im Abzug.

## Navigation — kurze Leiste, „Mehr“, Favoriten, Einklappen

Seit 0.5.3 macht es die Leiste wie HubSpot (`frontend/lib/navigation.ts`
trägt die Daten, `components/huelle.tsx` die Symbole): Sie zeigt nur, was
die Person sich gemerkt hat — in der Reihenfolge der Sterne. Solange
niemand einen Stern gesetzt hat, stehen sechs Vorgaben da (Start, Leads,
Aufgaben, Firmen, Kontakte, Eingang, `LEISTE_STANDARD`); der erste Stern
ersetzt sie ganz. Darunter **„Mehr“**: ein Feld rechts neben der Leiste
mit allen vierzehn Bereichen in den vier Gruppen **Verkauf** (Start,
Leads, Angebote, Prognose, Aufgaben), **Bestand** (Firmen, Kontakte,
Listen), **Post** (Eingang, Tickets, Kampagnen), **Wissen** (Fragen,
Erkenntnisse, Einstellungen) nebeneinander, je Eintrag der Stern. Ein
Feld statt HubSpots zwei Stufen: Bei vierzehn Zielen ist alles auf einen
Blick da. Escape, Klick außerhalb oder ein Seitenwechsel schließen es.
Von 0.3.8 bis 0.5.2 standen alle Gruppen mit Überschrift in der Leiste —
mit Favoriten darüber wurden das neunzehn Zeilen.

**Favoriten** hängen an der Person, nicht am Browser: Stern am Eintrag
(in der Leiste bei Hover oder Tastaturfokus, in „Mehr“ immer sichtbar),
gemerkte Einträge bilden die Leiste. Gespeichert in `users.einstellungen` (jsonb, Migration 0024)
über `PATCH /api/mitglieder/wer/einstellungen {"favoriten": [...]}`; `null`
löscht den Schlüssel, unbekannte Schlüssel werden abgewiesen. `user_id` ist
die handelnde Person — Marc am Sitzplatz hat seine eigenen. Die Oberfläche
schaltet sofort um und nimmt sich bei Fehler zurück (`frontend/lib/wer.ts`).
Kein Protokolleintrag: eine Vorliebe ist kein Geschäftsdatum. In der
Sicherung reist `einstellungen` im `nutzer`-Block mit und wird beim
Wiederanlauf nur gefüllt, wo es leer ist.

**Die Kopfecke** braucht 227 px für Wappen, Wortmarke, „Beacon“ und den
Klappschalter; die Leiste war 220 px breit. Die Beschriftung lief deshalb
elf Pixel aus ihrem Kasten und endete zwei Pixel vor dem Knopf, dessen
Fokusring drei braucht — sichtbar als Rahmen über dem letzten Zeichen
(0.5.7). Die Leiste ist jetzt 240 px breit (`--huelle-nav-breite`), und
die Marke darf notfalls kürzen statt überzulaufen. Der Knopf bleibt bei
40 px, der Zielgröße am Zeiger.

**Einklappen** auf Symbole: Knopf in der Kopfecke oder ⌘B / Strg+B. Zustand
je Browser im Cookie `beacon-navigation`, vor dem ersten Anstrich per
Inline-Script als `html[data-navigation="eingeklappt"]` gesetzt
(`components/navigation.tsx`, wie die Darstellung). Eingeklappt zeigt jeder
Eintrag seinen Namen als Tooltip; „Mehr“ öffnet auch dann das volle Feld.

**Der Fuß** trug bis 0.5.5 drei Dinge nebeneinander, die nichts
miteinander zu tun haben: eine Personenkarte mit Rahmen (schwerer als
jeder Eintrag darüber, mit der Unterzeile „angemeldet“ — was man ohnehin
sieht), den Dreifach-Schalter für die Darstellung und den Satz „läuft auf
dieser Box“ in 10-px-Monoschrift. Seit 0.5.6 sind es zwei Zeilen mit
Aussage (`components/konto.tsx`):

*Die Kontozeile* ist ruhig — Kreis, Name, kein Kasten — und öffnet ein
Menü nach oben mit **Sitzplatz** (nur bei mehr als einer Person) und
**Darstellung**. Das Menü schließt bei Escape, Klick außerhalb und
Seitenwechsel und gibt den Fokus zurück; die alte Personenliste schloss
nur durch Auswahl. Die zweite Zeile unter dem Namen erscheint nur, wenn
ein Sitzplatz gewählt ist — dann sagt sie etwas.

*Die Nachweiszeile* nennt den **gemessenen** Stand und führt auf
*Einstellungen › Daten › Wohin Daten gehen*. `lib/datenwege.ts` prüft
jeden eingetragenen Endpunkt (Sprachmodell, Sprachausgabe, Suchdienst,
SMTP, Postausgang, Brevo). Als **auf dieser Box** gelten Kubernetes-
Dienstname, `localhost`, privates Netz — und die **eigene Olares-Zone**,
abgeleitet aus der Adresse der öffentlichen Links
(`41b89d101.kaivostudio.olares.de` → `kaivostudio.olares.de`). Alles
andere wird gezählt und im Tooltip beim Namen genannt. Also „Alles auf
dieser Box“ oder „2 Ziele außerhalb“; ohne geladene Einstellungen steht
dort **nichts**.

Die Zonen-Regel ist gemessen, nicht vermutet (8.9.2026, aus dem
Backend-Pod): `llm.kaivostudio.olares.de` löst auf `192.168.1.17` auf —
die Box selbst. Olares führt seine Zone intern auf den eigenen Knoten,
ein Aufruf dorthin verlässt das Haus nicht. Ohne die Regel meldete die
Zeile „2 Ziele außerhalb“, wo nur eines hinausgeht (0.5.8); ein falscher
Alarm zerstört das Vertrauen in den Nachweis so zuverlässig wie eine
falsche Beruhigung.

**Warum die Zonen-Adresse und nicht der Dienstname?** Weil ein Dienst im
eigenen Namensraum von Beacon aus nicht erreichbar ist. Gemessen: der
Aufruf von `litellm-svc.litellm-kaivostudio.svc.cluster.local` aus
`beacon-kaivostudio` läuft in eine Zeitüberschreitung. Im LiteLLM-
Namensraum steht nur `app-np`; Olares riegelt Namensräume gegeneinander
ab (Constraint 4). Nur als **shared** installierte Apps tragen die
Regeln, die andere hereinlassen — Speaches (`speachesv3-shared`) hat
`shared-np`, `shared-entrance-np` und `app-gateway-shared-ingress-np`
und ist deshalb direkt ansprechbar. Für eine App im eigenen Namensraum
ist die Zonen-Adresse also nicht Bequemlichkeit, sondern der einzige
Weg.

Der alte Satz musste weg, weil `docs/DESIGN.md §5` es verlangt: Der
Nachweis trägt „gemessene Werte — oder gar nicht“, denn „eine Zusage ohne
Beleg ist schlechter als keine“. Er war zudem falsch geworden: Mit
eingetragenem Brave-Suchdienst verlässt sehr wohl etwas die Box, und die
Einstellungen sagten das daneben schon ehrlich.

**Mobil** (unter 1024 px) bleibt die Leiste unten: die ersten Favoriten,
aufgefüllt aus Start, Leads, Firmen, Kontakte bis vier, dazu „Mehr“ mit
allen übrigen Bereichen samt Einstellungen. Der Fuß ist dort ausgeblendet.

## Assistent — Aufträge in Worten, Handlungen mit Karte

Seit 0.4.0 sitzt unten rechts ein Knopf mit dem Schild (`components/assistent.tsx`).
Ein Auftrag wie „Leg für Brinkmann eine Aufgabe an: Angebot nachfassen,
Freitag“ geht an `POST /api/assistent` (`backend/app/assistent.py`). Das
Modell bekommt Beacons Funktionen als Werkzeuge im OpenAI-Format
(`llm.chat_werkzeuge`; auf der Box geprüft: `chat` über LiteLLM liefert
saubere Aufrufe samt aufgelöstem Datum, rund zehn Sekunden je Schritt),
plant, und Beacon führt aus — höchstens fünf Schritte je Auftrag.

**Lesen sofort, Schreiben mit Karte.** `suchen`, `aufgaben_offen` und
`seite_oeffnen` laufen direkt (Öffnen navigiert die Oberfläche). Die
schreibenden Werkzeuge — `aufgabe_anlegen`, `notiz_anlegen`,
`kontakt_anlegen`, `lead_verschieben` — schreiben nichts: Sie lösen Namen
im Bestand auf und geben eine **Karte** zurück, in der die Anfrage fertig
steht (`anfrage.methode/pfad/koerper`). Die Oberfläche führt sie erst auf
„Ausführen“ aus, mit den Rechten der Person, über die normalen Endpunkte.
Das Modell schreibt nie selbst, und es erfindet keine Kennungen: Bei
mehreren Treffern bekommt es die Kandidaten als `nachfrage` und fragt
zurück; bei keinem Treffer sagt es das.

Verlauf: die letzten zehn Nachrichten gehen mit, je Sitzung im Browser,
nichts wird gespeichert. Ohne Sprachmodell antwortet der Endpunkt 409.
Tests in `backend/tests/test_assistent.py` fahren die Schleife mit einem
Skript statt Modell: Karte statt Schreibzugriff, Nachfrage bei
Mehrdeutigkeit, Stufenwechsel kennt die Pipeline.

Nächste Stufen, bewusst noch nicht gebaut: Ketten („für jede Firma der
Liste …“) und Versand (Ticket-Antwort, Kampagne) — Versand nie ohne
ausdrückliche Bestätigung.

## Gespräch vorbereiten — der Bestand als Podcast

Seit 0.5.0 gibt es auf jeder Firmen- und Lead-Seite den Block *Gespräch
vorbereiten* (`components/podcast.tsx`, `backend/app/podcast.py`). Ein
Klick auf „Podcast erzeugen“ macht aus allem, was zur Firma im Bestand
steht, ein Gespräch zweier Stimmen von fünf bis acht Minuten: Eine
Moderatorin fragt, ein Kollege aus dem Vertrieb antwortet — wer sie sind,
was zuletzt geschah, was offen ist, was Kunden gesagt haben, und drei
Fragen für den Termin. Zum Anhören auf dem Weg, auch am Handy, nach der
Olares-Anmeldung. Nichts verlässt die Box.

**Drei Schritte, alle auf der Box.** Der Kontext ist dieselbe
Zusammenstellung wie für die KI-Zusammenfassung (`routers/ki._kontext_firma`),
dazu offene Tickets, Aussagen aus den Erkenntnissen (mit Zitat), offene
Aufgaben und Angebote. Das Sprachmodell schreibt daraus ein Skript in
acht bis vierzehn Segmenten mit Sprecherwechsel — als JSON, mit dem
Auftrag, nichts zu erfinden und Fehlendes als Frage zu benennen. Dann
spricht die Sprachausgabe jedes Segment mit der Stimme seines Sprechers,
und Beacon fügt die MP3-Teile zu einer Datei zusammen (ID3-Kopf und
Xing-Rahmen nur einmal). Die Folge liegt unter
`/app/data/podcasts/<org>/<id>.mp3` mit Rechten 0600, die Zeile in
`podcasts` (0025) geht in der Sicherung mit — der Pfad steht in der
Zeile und wird nie neu abgeleitet, weil die Organisation nach einer
Wiederherstellung eine neue Kennung trägt.

**Die Sprachausgabe** steht unter *Einstellungen › KI und Programme ›
Sprachausgabe*: ein OpenAI-kompatibler Dienst (`POST /v1/audio/speech`),
auf der Box **Speaches**. Die Adresse ist je Installation anders —
`kubectl get svc -A | grep speaches` nennt sie, auf Kais Box
`http://speaches.speachesv3-shared.svc.cluster.local:8000`. Deutsche
Stimmen sind Piper-Modelle; Vorgabe ist Thorsten (high) für den Kollegen
und Kerstin (low) für die Moderatorin. Speaches bringt sie nicht mit:
„Stimme einrichten“ ruft `POST /v1/models/{id}` — der Dienst lädt das
Modell einmalig von Hugging Face, ohne Kundendaten, das dauert je nach
Leitung einige Minuten, und die Seite fragt alle drei Sekunden nach.
„Kollegen hören“ und „Moderatorin hören“ (`POST /api/podcasts/probe`)
beweisen die Einrichtung, bevor jemand eine Folge wartet. Ehrlich gesagt:
Thorsten klingt gut, die weiblichen Piper-Stimmen hörbar einfacher.

Die Stimme (`voice`) je Modell muss man nicht eintragen: Beacon fragt
`GET /v1/audio/speech/voices`, sonst probiert es die Kennung aus dem
Modellnamen und merkt sich, was der Dienst annahm (`STIMMEN_ERMITTELT`).
Ein eingetragener Wert (`tts_stimme`, `tts_stimme_2`) geht vor.

**Automatik.** Mit dem Häkchen „Gespräche mit Termin automatisch
vorbereiten“ sieht `_podcastschleife` in `main.py` stündlich nach:
Für jede offene Aufgabe der Art *Termin* mit Firma oder Lead und Frist in
den nächsten 24 Stunden entsteht eine Folge — genau eine je Termin
(eindeutiger Teilindex auf `task_id`), im Namen dessen, dem der Termin
zugewiesen ist. Die Startseite zeigt sie unter *Heute vorbereitet*.

Endpunkte: `GET /api/podcasts/status`, `POST /api/podcasts {entity, entity_id, anlass?}`
(202, läuft im Hintergrund; 409 ohne Modell oder Sprachausgabe oder solange
eine Folge entsteht), `GET /api/podcasts?entity&entity_id`, `GET /api/podcasts/heute`,
`GET /api/podcasts/{id}`, `GET /api/podcasts/{id}/audio` (audio/mpeg, mit
Range — der Player kann springen), `DELETE /api/podcasts/{id}` (nimmt die
Datei mit), `GET /api/podcasts/stimmen`, `POST /api/podcasts/stimmen/einrichten`,
`POST /api/podcasts/probe`. Die Dauer ist eine Schätzung aus der Wortzahl
(„ca. 6 Min“), keine Messung.

Tests in `backend/tests/test_podcast.py` fahren den Lauf mit Skript statt
Modell und einem Speaches-Nachbau (`httpx.MockTransport`): Bestand im
Prompt, Sprecherwechsel, je Stimme ihr Modell, Verkettung ohne doppelte
Köpfe, 0600, Range, Löschen, Automatik einmal je Termin, fremde
Organisation sieht nichts.

## Anmeldung — warum Beacon das doch selbst macht

Die Hausregel lautet „keine eigene Authentifizierung, das macht Olares".
Sie gilt weiter für den Normalfall, und der Bruch hier hat einen
gemessenen Grund.

**Olares kann es für ein Team nicht.** Eine Olares-App wird je Nutzer
installiert — auf der Box liegt Beacon im Namensraum `beacon-kaivostudio`
mit `owner: kaivostudio`. Ein zweites Olares-Konto bekäme ein eigenes,
leeres Beacon mit eigener Datenbank; Marc sähe Kais Bestand nicht. Der
einzige geteilte Modus ist die *shared app*, und die hat laut Olares'
Plattformdokumentation ausdrücklich **keinen Entrance und keine URL** —
sie ist für Hintergrunddienste wie Speaches gedacht. Für mehrere Menschen
in **einem** Bestand gibt es also keinen Olares-Weg.

Die Sitzplätze waren die bisherige Antwort auf genau diese Lücke. Sie
schreiben Arbeit einer Person zu, sind aber **keine Anmeldung**: Wer den
geteilten Zugang hat, kann jeden Platz einnehmen.

### Stand: offen seit dem 8. September 2026

Der Entrance `beacon` steht auf `public`, der Modus auf `eigen`. Von außen
ohne jede Box-Sitzung gemessen: Startseite 200, Anmeldemaske 200, und mit
gefälschtem `X-Bfl-User` überall 401 — Firmen, Einstellungen, Mitglieder,
Sicherung anlegen, Sicherung zurückspielen, Einstellungen ändern, Person
anlegen. Falscher Name und falsches Passwort antworten wortgleich. Elf
Fehlversuche ergeben 429 mit `Retry-After: 900`.

### Die Reihenfolge ist die Sicherheit

**Erst `ANMELDUNG_MODUS=eigen`, dann den Entrance öffnen. Nie umgekehrt.**

Ein offener Entrance bei `olares` ist die vollständige Preisgabe: Der Kopf
`X-Bfl-User` kommt ungeprüft durch den Next-Proxy bis ins Backend, und ein
`curl -H 'X-Bfl-User: kaivostudio'` aus dem Internet ist der Eigentümer —
mit Lesezugriff auf den ganzen Bestand und offener Sicherung daneben.

Der `authLevel` lässt sich **auch in den Olares-Einstellungen** umstellen
(Settings › Applications › beacon › Authentication level), nicht nur über
das Manifest. Das ist ein Klick und wirkt sofort. Wer ihn drückt, bevor
der Modus steht, öffnet genau dieses Fenster. Deshalb steht `eigen` seit
0.6.2 im Deployment, während das Manifest den Entrance noch auf `internal`
lässt: Das kostet einen zusätzlichen Anmeldeschritt und schließt die Lücke.

Prüfen lässt sich der wirksame Stand nur an der Box, nicht am Bildschirm:

```bash
kubectl get applications.app.bytetrade.io beacon-kaivostudio-beacon \
  -o jsonpath='{range .spec.entrances[*]}{.name}{"  "}{.authLevel}{"\n"}{end}'
```

### Zwei Modi, und was der Unterschied bedeutet

`ANMELDUNG_MODUS` steht als Literal im Deployment (nicht in `values.yaml`
— ein Upgrade spielt die Werte der Installation zurück, eine Umstellung
käme dort nie an):

| Modus | Wer prüft | `X-Bfl-User` | Entrance |
|---|---|---|---|
| `olares` (heute) | Envoy-Sidecar mit Authelia | gilt, legt beim ersten Aufruf Nutzer und Organisation an | `internal` |
| `eigen` | Beacons Sitzung | **gilt nicht** und legt **nichts** an | `public` möglich |

Der zweite Modus ist die Voraussetzung dafür, den Eingang zu öffnen. Ohne
ihn genügte ein `curl -H 'X-Bfl-User: kaivostudio'`, um Eigentümer zu
sein und den ganzen Bestand zu lesen.

### Die Erstinstallation braucht eine Ausnahme

Aus dem Markt installiert steht `ANMELDUNG_MODUS=eigen` von Anfang an. Eine
frische Datenbank hat aber keinen Nutzer, kein Passwort und keine
Einladung — und ohne Ausnahme auch keinen Weg, das zu ändern. Genau das ist
am 8. September einem zweiten Nutzer passiert, der Beacon auf seiner
eigenen Box installierte: 401 auf alles, Sackgasse, App unbrauchbar.

Deshalb gilt seit 0.6.3: **Solange in dieser Datenbank niemand ein Passwort
hat, zählt der Olares-Kopf weiter.** Mit dem ersten gesetzten Passwort ist
er endgültig tot, auch für den, der eben noch hereinkam. Die Bedingung ist
bewusst nicht „gibt es Nutzer?" — der Kopf legt beim ersten Aufruf ja
selbst einen an, und die Tür fiele zu, bevor jemand ein Passwort setzen
konnte.

Das ist vertretbar, weil eine frische Installation hinter
`authLevel: internal` steht: Es kommt ohnehin nur herein, wer an der Box
angemeldet ist. Die Einstellungsseite sagt es außerdem deutlich, solange
kein Passwort gesetzt ist.

### Wie ein Zugang entsteht

Es gibt **keine Registrierung**. Der Eigentümer legt unter *Einstellungen ›
Firma und Team* eine Person an und drückt in ihrer Zeile auf das
Schlüsselsymbol. Zurück kommt ein Link zum Weitergeben — keine Mail: SMTP
ist auf einer frischen Box nicht eingerichtet, und ein Zugang, der am
Mailversand hängt, wäre genau dann nicht da, wenn man ihn braucht.

Der Link gilt sieben Tage und **genau einmal**. Ein neuer Link entwertet
den alten. Wer ihn öffnet, setzt sein Passwort (mindestens zwölf Zeichen)
und ist danach angemeldet.

**Der Eigentümer macht das für sich selbst genauso** — und zwar *bevor*
der Eingang öffnet. Das Schlüsselsymbol steht auch in seiner eigenen
Zeile. Wer den Schalter auf `eigen` legt, ohne vorher ein Passwort gesetzt
zu haben, sperrt sich aus: Der Olares-Kopf zählt dann nicht mehr, und es
gibt kein Konto, das durch die Maske käme. Zurück hilft dann nur, den
Modus im Deployment vorübergehend wieder auf `olares` zu setzen.

### Die Einladungsseite nennt Kennung und Box

Am 8. September schickte ein zweiter Nutzer von **seiner** Box eine
Einladung. Auf dem Handy stand groß „Willkommen, Kai", darunter klein die
Kennung `marc-bayer`, und die Adresszeile war abgeschnitten. Drei Dinge
gingen dabei schief, und alle drei lagen an der Seite, nicht am Menschen:

- **Der Anzeigename führte.** Er ist nur ein Etikett und kann auf jemand
  anderen zeigen. Entscheidend ist die Kennung; sie steht jetzt oben, in
  der Schrift, in der sich `l` und `1` unterscheiden.
- **Die Seite sagte nicht, zu welchem Beacon der Link gehört.** Jetzt nennt
  sie den Ursprung im Text, nicht nur in der Adresszeile.
- **Eine Einladung auf ein Konto mit Passwort sah aus wie eine Erstanlage.**
  Sie ist aber ein **Zurücksetzen**: Der bisherige Inhaber ist danach
  ausgesperrt. Für einen Eigentümer ist das der Rettungsweg, für einen
  falsch zugestellten Link ein Unfall. Die Seite heißt in diesem Fall
  „Zugang zurücksetzen", der Knopf „Passwort ersetzen", und die
  Einstellungsseite warnt schon beim Erzeugen.

Der Endpunkt `GET /api/einladung/{token}` liefert dafür `uebernahme`.
Verraten wird dadurch nichts, was der Linkinhaber nicht ohnehin erführe.

### Was gespeichert wird — und was nicht

- Vom Passwort bleibt ein **argon2id-Hash**, nie das Passwort.
- Vom Sitzungstoken bleibt ein **SHA-256**. Wer die Datenbank liest, kann
  sich damit nicht anmelden.
- Die Sitzung lebt auf dem Server. Ein selbstsigniertes Token im Keks wäre
  nach „Abmelden" weiter gültig, bis es abläuft; eine Zeile in `sitzungen`
  lässt sich wirklich beenden.
- Der Keks `beacon_sitzung` trägt `HttpOnly` (kein JavaScript sieht ihn),
  `SameSite=Lax` und `Secure`, sobald die Verbindung über TLS kam.
- Absolut 30 Tage, im Leerlauf 7. Eine Schleife räumt Abgelaufenes weg.

### Was die Anmeldemaske nicht verrät

Falsches Passwort und unbekannter Name antworten **wortgleich** und
rechnen gleich lang — auch ein Konto ohne hinterlegtes Passwort. Sonst
wäre die Maske eine Auskunft darüber, wer im Haus arbeitet.

Zehn Fehlversuche je Name in einer Viertelstunde ergeben 429 mit
`Retry-After`. Je Adresse liegt die Grenze bei fünfzig: Hinter einer
Adresse sitzt oft ein ganzes Büro, und der Tippfehler des Kollegen darf
niemanden sonst aussperren. Beide Grenzen zählen **getrennt** —
zusammengezählt spränge die Bremse schon nach fünf Versuchen.

### Rollen gelten jetzt wirklich

`owner` und `admin` ändern Einstellungen, spielen Sicherungen zurück und
laden ein. `member` und `viewer` arbeiten im Bestand und bekommen dort
403. Solange der Eingang `internal` war, durfte jedes Mitglied alles; mit
offenem Eingang ist das nicht mehr tragbar. Die Einstellungsseite sagt es
vorher, statt es den Server abweisen zu lassen.

**Der Sitzplatz greift bei eigener Anmeldung nicht mehr.** Er existierte
für **einen** geteilten Olares-Zugang. Wer sich selbst anmeldet, ist
bereits er selbst — und mit Sitzplatz nähme ein `member` den Platz des
Eigentümers ein und erbte dessen Rechte.

Und dort, wo er weiter greift, hängen die Rechte an der **angemeldeten**
Person, nicht am gewählten Platz. Sonst verlöre der Eigentümer den Zugriff
auf die Einstellungen, sobald er den Platz eines Mitglieds einnimmt.

### Drei Dinge, die nur der Browser zeigte

Alle drei standen in keinem Test und hätten in Betrieb wehgetan:

- **Die Herkunftsprüfung wies jede echte Anmeldung ab.** Der Browser
  spricht mit dem Frontend, das Frontend leitet ans Backend weiter — im
  `Host` steht der interne Dienst, nicht die Adresse aus der Adresszeile.
  Was der Browser sah, steht in `X-Forwarded-Host`.
- **`Secure` hing am Modus statt an der Verbindung.** So trüge der Keks im
  Betrieb `olares` auf der Box kein `Secure`, obwohl dort alles über TLS
  läuft. Jetzt entscheidet `X-Forwarded-Proto`.
- **Der Einladungsschlüssel war für den Eigentümer unsichtbar** (behoben in
  0.6.1). Auf der Box gemessen: Die Mitgliedertabelle war 744 px breit, ihr
  Rahmen 638. Der Knopf der ersten Zeile stand bei 697 bis 748 und damit
  vollständig außerhalb; bei den übrigen Zeilen schob ihn das zusätzliche
  „Entfernen" weit genug nach links, um sichtbar zu bleiben. Ausgerechnet
  die Person, die als erste ein Passwort setzen muss, kam nicht an ihren
  Knopf. Die Tabelle rechnet jetzt mit festen Spalten und kann nicht mehr
  überlaufen; Name und Kennung stehen in einer Spalte übereinander, beide
  Handlungen sind Zeichen mit Beschriftung für Vorleseprogramme.

### Nach einer Neuinstallation

Der Abzug nimmt die Passwort-Hashes mit — ohne sie wäre eine
Neuinstallation im Modus `eigen` eine Aussperrung: Der Olares-Kopf zählt
dort nicht mehr, und ohne Hash käme niemand mehr an der Maske vorbei,
auch der Eigentümer nicht. Offene Einladungen kommen ebenfalls zurück.
`sitzungen` und `anmeldeversuche` bewusst nicht: Eine zurückgespielte
Sitzung wäre ein Wiedereinspielen von Zugängen, eine zurückgespielte
Bremse sperrte Menschen für Tippfehler aus, die lange her sind.

### Zugangsdaten liegen im Tresor

Seit 0.6.6 stehen SMTP- und IMAP-Passwörter, die API-Schlüssel für
Sprachmodell, Suche, Sprachausgabe und Brevo, das Webhook-Geheimnis und
das Relay-Geheimnis **verschlüsselt** in der Datenbank (AES-GCM,
`app/tresor.py`). Sie müssen im Original wieder herauskommen — ein Dienst
meldet sich damit an —, ein Hash wie beim Anmeldepasswort ginge also
nicht.

**Der Schlüssel liegt nicht in der Datenbank**, sondern als Datei
`tresor.key` unter `/app/data` mit Rechten 0600, erzeugt beim ersten
Bedarf. Damit schützt der Tresor genau eine, aber wirkliche Sache: einen
Abzug der Datenbank. Ein Postgres-Dump, ein kopiertes Laufwerk, eine
Sicherung, die irgendwo landet — daraus ist nichts mehr zu benutzen.

**Wogegen er nicht schützt, und das gehört dazugesagt:** Wer im Pod ist,
liest die Schlüsseldatei genauso wie die Datenbank. Ein Tresor, dessen
Schlüssel danebenliegt, trennt zwei Dinge, die sonst zusammen wegkommen —
mehr verspricht er nicht.

`tresor.SPALTEN` ist der Vertrag: Wer eine Spalte mit einem Geheimnis
ergänzt und sie dort vergisst, speichert weiter im Klartext, und niemand
merkt es. Ein Test hält die Liste fest.

Zwei Eigenschaften machen die Umstellung ausfallfrei. `entschluesseln`
gibt zurück, was es nicht kennt — eine Datenbank aus der Zeit davor
funktioniert weiter. Und ein Lauf beim Start holt vorhandenen Klartext
einmal nach; scheitert er, startet die Anwendung trotzdem.

**Geht `tresor.key` verloren**, sind die Zugangsdaten unlesbar und müssen
neu eingetragen werden. Der Abzug enthält sie ohnehin nicht.

### Wo bin ich überall angemeldet

*Einstellungen › Firma und Team › Ihre Geräte* listet die eigenen offenen
Sitzungen mit Gerät und Zeitpunkt und beendet einzelne davon — oder alle
außer dem gerade benutzten. Ohne diese Liste stünde ein vergessener
Browser dreißig Tage offen, ohne dass es jemand sehen könnte.

Beendet wird **serverseitig**: Der Keks auf dem anderen Gerät ist danach
wertlos, nicht bloß versteckt. Sichtbar sind ausschließlich die eigenen
Sitzungen; dafür sorgt die Policy `sitzungen_selbst`, und die Abfrage
prüft zusätzlich auf `user_id` — eine zweite Wand, falls die Policy einmal
gelockert wird. Angezeigt werden weder Token noch Adresse, nur die
Browserkennung, aus der die Oberfläche „Chrome auf Mac" macht.

### Wenn niemand mehr hereinkommt

Das Passwort gehört **nicht** in die Olares-Umgebungsvariablen. Dort stünde
es im Klartext, sichtbar für jeden, der den Einstellungsbildschirm öffnet,
und es sind laut Beschriftung „shared settings for your apps" — also für
jede App auf der Box lesbar. Der ganze Aufbau speichert bewusst nur einen
argon2id-Hash, damit selbst ein Datenbankleser sich nicht anmelden kann;
ein Klartextpasswort daneben hebt das auf. Ein Konto, das aus einer
Variablen käme, wäre außerdem eine dauerhafte Hintertür — genau das, was
ein offener Eingang nicht haben darf.

Der Rettungsweg hängt stattdessen am **Zugang zur Box**, und das ist die
richtige Hürde: Wer an der Box sitzt, kommt ohnehin an alles heran.

```bash
ssh olares@192.168.1.17
export KUBECONFIG=/etc/rancher/k3s/k3s.yaml
POD=$(kubectl get pods -n beacon-kaivostudio --no-headers | grep beacon-backend | awk '{print $1}')
kubectl exec -it -n beacon-kaivostudio $POD -c backend -- python3 -c "
import asyncio, getpass, os, asyncpg
from app.anmeldung import hash_passwort, passwort_pruefen
neu = getpass.getpass('Neues Passwort: ')
passwort_pruefen(neu)
async def m():
    c = await asyncpg.connect(host=os.environ['DB_HOST'], port=int(os.environ['DB_PORT']),
        user=os.environ['DB_USER'], password=os.environ['DB_PASSWORD'], database=os.environ['DB_NAME'])
    await c.execute('update public.users set passwort_hash = \$1, passwort_am = now(), gesperrt_bis = null where olares_username = \$2', hash_passwort(neu), 'kaivostudio')
    await c.execute('delete from public.anmeldeversuche')
    print('gesetzt')
    await c.close()
asyncio.run(m())
"
```

`getpass` liest das Passwort, ohne es in die Befehlszeile oder in die
Shell-Historie zu schreiben. Die Bremse wird gleich mit geleert, sonst
sperrt die eigene Rateserie den frisch gesetzten Zugang aus.

**Zwei billigere Vorkehrungen**, die den Rettungsweg meist überflüssig machen:

- **Ein zweiter Mensch mit `admin`.** Ein vergessenes Passwort ist dann
  kein Notfall, sondern ein Einladungslink von der anderen Person. Neue
  Personen bekommen `member`; die Rolle lässt sich in der Datenbank auf
  `admin` heben (`user_org_roles.role`).
- **Der Abzug trägt die Hashes.** Eine Neuinstallation sperrt niemanden
  aus, siehe oben.

Notfalls hilft auch der Rückweg: `ANMELDUNG_MODUS` im Deployment
vorübergehend wieder auf `olares`, dann zählt der Olares-Zugang erneut.
Das braucht eine neue Version über den Markt und öffnet währenddessen
nichts, solange der Entrance dabei zurück auf `internal` geht.

### Noch offen

Zweiter Faktor (`users.totp_geheimnis` steht bereit, die Migration dafür
ist getan), Passwort zurücksetzen per Mail (braucht SMTP), „alle Geräte
abmelden" als Knopf, und die Anmeldungen im Audit-Log.

Tests: `backend/tests/test_anmeldung.py` — 29 Fälle, darunter der
entscheidende, dass ein gefälschter `X-Bfl-User` im Modus `eigen` weder
Zugang bringt noch einen Nutzer anlegt.

## Dokumente am Datensatz

Seit 0.6.8 kann an Firma, Kontakt, Geschäft und Ticket eine Datei liegen —
das Angebot als PDF, der unterschriebene Vertrag, das Foto vom
Zählerstand. Der Block steht rechts, unter allem anderen: Man sucht ihn
selten, und wenn man ihn sucht, weiß man wo.

**Die Datei liegt nicht in der Datenbank.** Sie steht unter
`/app/data/dokumente/<org>/<kennung><endung>`, dem einzigen Pfad, den
Olares als dauerhaft zusichert. Als `bytea` in der Datenbank wäre der
stündliche Abzug nicht mehr 130 Kilobyte, sondern Hunderte Megabyte, und
jede Auslieferung müsste vollständig durch den Arbeitsspeicher.

**Der Dateiname kommt nie in einen Pfad.** Auf der Platte heißt die Datei
nach ihrer Kennung; der Name, den ein Mensch sieht, steht in der
Datenbank. `../../../../etc/passwort.txt` ist damit ein hässlicher
Anzeigename und kein Angriff — `test_dokumente.py` lädt genau den hoch
und prüft, wo die Datei landet.

**Ausgeliefert wird als Anhang, nicht als Seite.** Nur Bild und PDF darf
der Browser im Fenster zeigen. **SVG gehört ausdrücklich nicht dazu**: Es
ist ein Dokument mit Skriptfähigkeit, und im Ursprung von Beacon
angezeigt liefe fremdes Skript mit allen Rechten des Angemeldeten. Dazu
kommen an jeder Auslieferung `X-Content-Type-Options: nosniff` (sonst
könnte eine als PNG deklarierte HTML-Datei doch als Seite laufen) und
`Content-Security-Policy: default-src 'none'; sandbox`.

**Grenze 25 MB.** Darüber wird es ein Dateiserver, und dafür gibt es
Drive auf der Box. Die Zahl steht in `backend/app/dokumente.py`, damit
Test und Fehlermeldung dieselbe nennen.

**Löschen löscht wirklich.** Anders als bei Kontakten gibt es keine
dreißig Tage: Eintrag und Datei verschwinden zusammen. Bei einem Dokument
ist „gelöscht, aber noch da" die Zusage, die man am wenigsten brechen
will.

**Im Abzug steht die Zeile, nicht der Inhalt.** `dokumente` ist Teil der
Sicherung, mitsamt dem Pfad. Der Pfad wird beim Zurückspielen **nicht**
umgeschrieben, obwohl er die alte Org-Kennung trägt: `/app/data`
überlebt eine Neuinstallation, der alte Ordner steht also noch da, und
ein umgeschriebener Pfad zeigte ins Leere.

Tests: `backend/tests/test_dokumente.py` — 16 Fälle, darunter der
Pfadausbruch, die SVG-Auslieferung, die Größengrenze und die fremde
Organisation, die weder sieht noch holt noch löscht.

## Oberflächenfehler stehen im Pod-Log

Zerbricht die Oberfläche („Application error: a client-side exception“),
zeigt Beacon seit 0.5.0 eine deutsche Fehlerseite (`app/error.tsx`) mit
„Neu laden“ — und schickt Meldung, Stack, Pfad und Browser an
`POST /api/fehler` (`routers/fehler.py`). Der Endpunkt schreibt sie ins
Protokoll des Backend-Pods, nichts sonst:

```bash
ssh olares@192.168.1.17 "KUBECONFIG=/etc/rancher/k3s/k3s.yaml kubectl logs -n beacon-kaivostudio deploy/beacon-backend -c backend --since=24h | grep -A12 Oberflächenfehler"
```

`components/fehlermelder.tsx` hört außerdem auf `error` und
`unhandledrejection` des Fensters, höchstens fünf Meldungen je Seite,
per `fetch` mit `keepalive` — nie über `api.post`, der Fehlerpfad darf
selbst nicht werfen.

Der erste Fund auf diesem Weg kam noch vor dem Release: Das Schild des
Assistenten würfelte seinen Blinzel-Versatz beim Rendern, auf dem Server
anders als im Browser — ein Hydrierungsfehler auf jeder Seite (0.4.1).
Seit 0.5.0 wird erst nach dem Einhängen gewürfelt.

Der zweite Fund war der Absturz selbst (0.5.2): `TypeError: u is not a
function` in Reacts Effekt-Aufräumen. Der Assistent hatte
`useEffect(() => ende.current?.scrollIntoView(…), [verlauf])` ohne
Klammern — und **Chrome 152 gibt aus `scrollIntoView` ein Promise
zurück** (in Kais Browser gemessen). React 19 ruft den Rückgabewert eines
Effekts als Aufräumfunktion auf; ein Promise ist keine. Regel seitdem:
kein Effekt ohne Block, damit nie etwas zurückkommt, das keine Funktion
ist.

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
