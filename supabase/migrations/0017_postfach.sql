-- ========================================================================
-- 0017_postfach.sql
-- aicrm holt Post ab — und fasst dabei nichts an.
--
-- ## Warum holen statt geschickt bekommen
--
-- Gemessen am 5. September 2026: Eine Olares-App mit `authLevel: internal`
-- hat **keine öffentliche Adresse** (siehe docs/BETRIEB.md). Ein Webhook
-- von außen kann sie nicht erreichen, und keine Richtlinie ändert daran
-- etwas. Ausgehend ist der Weg dagegen offen — auch auf 993. Also holt
-- die Anwendung selbst, und niemand muss dafür eine Tür öffnen.
--
-- ## Warum eine UID und kein „ungelesen"
--
-- Auf demselben Postfach sitzt Relay, und dort liest ein Mensch. Würde
-- aicrm nach UNSEEN suchen und das Gelesene markieren, verschwände in
-- Relay der Fettdruck von Post, die niemand geöffnet hat. Ein zweiter
-- Klient hat sich still zu verhalten: Er merkt sich, bis wohin er
-- gekommen ist, und fasst keine Markierung an.
--
-- `imap_uid_gueltigkeit` gehört dazu, weil eine UID nur innerhalb einer
-- UIDVALIDITY etwas bedeutet. Ändert der Server sie — nach einem Umzug
-- etwa —, fangen die Zähler von vorn an, und ein gemerkter Stand zeigte
-- sonst auf fremde Post.
--
-- Das Passwort steht hier wie der LLM-Schlüssel: in der Zeile, nie in
-- einer Antwort. Die Schnittstelle meldet nur, *ob* eines hinterlegt ist.
-- ========================================================================

alter table public.org_settings
  add column if not exists imap_host             text,
  add column if not exists imap_port             integer not null default 993,
  add column if not exists imap_benutzer         text,
  add column if not exists imap_passwort         text,
  add column if not exists imap_ordner           text not null default 'INBOX',
  add column if not exists imap_takt_minuten     integer not null default 5,
  add column if not exists imap_aktiv            boolean not null default false,
  -- Bis wohin gelesen wurde, und in welchem Gültigkeitsraum.
  add column if not exists imap_letzte_uid       bigint,
  add column if not exists imap_uid_gueltigkeit  bigint,
  add column if not exists imap_zuletzt          timestamptz,
  -- Der letzte Fehler im Klartext. Ein Postfach, das seit drei Tagen
  -- nicht antwortet, muss das sagen können — sonst wartet jemand auf
  -- Tickets, die nie kommen, und niemand weiß warum.
  add column if not exists imap_letzter_fehler   text;
