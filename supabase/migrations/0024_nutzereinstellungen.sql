-- ========================================================================
-- 0024_nutzereinstellungen.sql
-- Was eine Person für sich einstellt — am Menschen, nicht am Zugang.
--
-- Favoriten in der Navigation sind eine Vorliebe, kein Geschäftsdatum. Sie
-- gehören zur Person, die gerade handelt: Marc am Sitzplatz hat seine
-- eigenen, auf jedem Gerät dieselben. Ein jsonb-Feld am Nutzer reicht —
-- es wächst mit („dichte" käme später an dieselbe Stelle), braucht keine
-- eigene Tabelle und reist in der Sicherung im Nutzerblock mit.
-- ========================================================================

alter table public.users
  add column if not exists einstellungen jsonb not null default '{}'::jsonb;
