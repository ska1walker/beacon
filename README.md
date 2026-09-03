# aicrm

Schlankes CRM für den Vertrieb von [AImighty](https://aimighty.de) —
läuft vollständig auf der eigenen Olares-Box.

Firmen, Kontakte, Geschäfte auf einem Pipeline-Board mit Ziehen und
Ablegen, ein Verlauf an jedem Datensatz, Aufgaben. Dazu ein KI-Teil, der
den Stand eines Kunden zusammenfasst, den nächsten Schritt an einem
Geschäft vorschlägt und Anschreiben entwirft.

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

Ausbaustufe 1 steht und ist geprüft: Schema, API, Oberfläche und der
KI-Pfad laufen lokal, 13 Tests sind grün. Das Olares-Chart lintet und
rendert, ist aber **noch nie auf einer echten Box installiert worden**.

Das erste offene Stück ist die **Ausfuhr**: Eine Deinstallation löscht die
Datenbank, und ohne Sicherung wären damit alle Vertriebsdaten weg.
