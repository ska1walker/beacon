-- ========================================================================
-- 0022_suche_region.sql
-- Die Suche bekommt ein Land.
--
-- „Baustoffhandel Tecklenburger Land“ ohne Region liefert bei Bing Fürth
-- und bei Brave die USA. Ein Länderkürzel je Organisation geht an beide
-- Dienste mit: Brave als `country`, SearXNG als Sprache (`de-DE`). Leer
-- heißt „keine Vorgabe“. Vorgabe ist DE, weil die Firmen im Bestand
-- dieselbe Vorgabe tragen.
-- ========================================================================

alter table public.org_settings
  add column if not exists suche_region text not null default 'DE'
    check (suche_region = '' or suche_region ~ '^[A-Z]{2}$');
