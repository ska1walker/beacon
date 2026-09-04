# aicrm

Schlankes CRM für den Vertrieb von [AImighty](https://aimighty.de) —
läuft vollständig auf der eigenen Olares-Box.

Der Weg vom ersten Kontakt bis zum Abschluss, durchgängig:

- **Pipeline** — Firmen, Kontakte, Geschäfte auf einem Board mit Ziehen
  und Ablegen, ein Verlauf an jedem Datensatz, Aufgaben.
- **Qualifizierung** — sechs Fragen, die ein Geschäft tragen, mit
  gerechneter Punktzahl und der Liste dessen, was noch zu klären ist.
- **Angebote** — Produktkatalog, Positionen, Summen und eine
  Druckfassung mit Briefkopf, die man verschicken kann.
- **Prognose** — gewichtete Pipeline, Trefferquote, Verlustanalyse,
  Zahlen je Produkt.
- **Eingang** — Besprechungsprotokolle aus
  [Insilo](https://github.com/ska1walker/insilo) landen am passenden
  Geschäft.
- **Zu zweit** — Sitzplätze am geteilten Olares-Zugang: Besitz, Filter
  und Protokoll je Person, ohne zweites Konto.
- **Anpassbar** — eigene Eigenschaften je Objekt, mehrere Pipelines mit
  frei geordneten Stufen, Kontakte mit mehreren Firmen.
- **Segmentiert** — Listen sind Fragen an den Bestand: Bedingungen auf
  jedes Feld, gespeichert als Ansicht, mit wählbaren Spalten, Sortierung
  und Aktionen für den ganzen Stapel.
- **Post** — E-Mail hinein und hinaus über Relay, nach einem kleinen
  signierten Vertrag; der Entwurf kommt vom Modell, gesendet wird von Hand.
- **Angereichert** — neue Firmen und Kontakte werden aus der Firmen-Website,
  einem Suchdienst und den LinkedIn-Treffern darin ergänzt. Jeder Wert
  nennt seine Quelle, Kontaktdaten müssen dort wörtlich stehen, und was
  schon eingetragen ist, wird nie überschrieben.

Und die KI liegt nicht obendrauf, sondern an den Stellen, wo sie Arbeit
abnimmt: eine hingetippte Gesprächsnotiz wird zu Notiz, Aufgaben,
nächstem Schritt und Qualifizierung. Ein Tagesbriefing sagt, womit man
anfängt. Fragen an den eigenen Bestand werden aus dem Bestand
beantwortet, mit Fundstellen. Angebotsvorschläge nehmen Preise aus dem
Katalog, nie aus dem Modell.

**Die Bedienung folgt HubSpot, das Aussehen dem AImighty-Designsystem.**

## Wohin Daten gehen

Datenbank, Suche und Oberfläche laufen auf der Box. Schriften liegen im
Repo, nicht auf einem CDN — auch nicht zur Bauzeit. Keine Telemetrie.

Das Sprachmodell ist die eine Ausnahme, und sie ist sichtbar gemacht:
aicrm bringt kein Modell mit, sondern spricht einen OpenAI-kompatiblen
Endpunkt an, den der Betreiber unter `/einstellungen` einträgt. **Es gibt
bewusst keinen Vorgabewert.** Solange nichts eingetragen ist, geht nichts
hinaus, und die Oberfläche sagt das offen, statt in einen
Verbindungsfehler zu laufen. Steht dort eine fremde Adresse, nennt die
Seite „Wohin Daten gehen" sie beim Namen.

Die Anreicherung ist die zweite: Sie liest die Website der Firma (das
verrät nur der Firma selbst, dass sich jemand für sie interessiert) und
fragt einen Suchdienst, **wenn** unter `/einstellungen` einer steht —
eine SearXNG-Instanz auf der Box oder Brave Search. Erst dann verlassen
Firmen- und Personennamen die Box, und auch das steht auf derselben
Seite. LinkedIn selbst wird nie abgerufen: Was Suchmaschinen von
öffentlichen Profilen zeigen, reicht für Profiladresse, Position und
Branche, und es lässt sich vor einem Kunden erklären.

## Aufbau

```
aicrm/
├── CLAUDE.md                # Projekt-Briefing, Constraints, Stand
├── backend/                 # FastAPI + asyncpg
├── frontend/                # Next.js 15, AImighty-Designsystem
├── supabase/migrations/     # Schema und Zeilensicherheit
├── olares/                  # Helm-Chart für Olares
├── scripts/                 # seed-dev, regen-migrations, check-chart
└── docs/BETRIEB.md          # Einrichtung, Tests, offene Punkte
```

## Loslegen

Siehe [docs/BETRIEB.md](docs/BETRIEB.md).

## Stand

Der Vertriebsprozess ist durchgängig abgebildet und lokal geprüft: 184
Backend-Tests, 11 Frontend-Tests, jede Ansicht im Browser gesehen.

Seit dem 3. September 2026 läuft aicrm auf einer echten Olares-Box und
steht im AImighty-Markt. Offen ist nur noch der Weg, auf dem Insilo und
Relay die Empfangspfade hinter dem Envoy-Sidecar erreichen (siehe
[docs/BETRIEB.md](docs/BETRIEB.md)).
