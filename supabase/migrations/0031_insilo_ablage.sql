-- ========================================================================
-- 0031_insilo_ablage.sql
-- Besprechungen aus Insilos gemeinsamem Ordner — der Weg, den Relay geht.
--
-- Auf derselben Box legt Insilo jede fertige Zusammenfassung als Datei in
-- den geteilten Olares-Ordner (appCommon). Beacon liest dort mit, ohne
-- Webhook und ohne Geheimnis (backend/app/insilo_ablage.py).
--
-- Nur `add column if not exists`: Der Migrationslauf auf der Box führt
-- jede Datei bei jedem Start aus.
-- ========================================================================

-- Aus welcher Datei die Besprechung zuletzt gelesen wurde, und in welchem
-- Stand (Änderungszeit:Größe). Ist die Datei weg, hat Insilo die
-- Besprechung gelöscht; ist der Stand gleich, wird nichts neu gelesen.
alter table public.besprechungen
  add column if not exists ablage_datei text,
  add column if not exists ablage_stand text;

create index if not exists besprechungen_ablage_idx
  on public.besprechungen (org_id, ablage_datei) where ablage_datei is not null;

-- Liest diese Organisation den Ordner? `null` heißt: nicht eingestellt —
-- dann liest ihn die einzige Organisation einer Box, sonst keine.
alter table public.org_settings
  add column if not exists insilo_ablage boolean;

-- Wohin „In Insilo öffnen" führt, wenn die Besprechung ohne Quelle kam.
alter table public.org_settings
  add column if not exists insilo_adresse text;
