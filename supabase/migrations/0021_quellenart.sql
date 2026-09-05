-- ========================================================================
-- 0021_quellenart.sql
-- Die Art einer Quelle ist Teil des Vertrags, nicht nur eine Beschriftung.
--
-- Bis hier prüften beide Empfangspfade nur Signatur und Freigabe, nicht
-- die Art: Ein Geheimnis für eine Insilo-Quelle funktionierte auch am
-- Post-Endpunkt und umgekehrt. Jetzt sagt die Art, welcher Pfad die
-- Quelle bedienen darf — `relay` für den Postdienst, `email` für das
-- eigene Postfach (nur intern), alles
-- andere für Ereignisse und Tickets. Bestehende Zeilen tragen die
-- Vorgabe `insilo` und funktionieren weiter wie bisher.
-- ========================================================================

-- NOT VALID: gilt für alles, was ab jetzt geschrieben wird. Bestehende
-- Zeilen werden nicht geprüft — die Migration läuft unter FORCE ROW LEVEL
-- SECURITY ohne Nutzerkontext und könnte sie weder lesen noch berichtigen.
-- Die Schnittstelle nimmt ohnehin nur diese fünf Werte an.
alter table public.webhook_sources
  drop constraint if exists webhook_sources_kind_check;
alter table public.webhook_sources
  add constraint webhook_sources_kind_check
  check (kind in ('insilo', 'api', 'bot', 'formular', 'relay', 'email')) not valid;
