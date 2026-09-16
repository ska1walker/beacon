-- ========================================================================
-- 0032_ablage_lesefassung.sql
-- Mit welcher Fassung der Leseregeln eine Datei zuletzt gelesen wurde.
--
-- Anlass (0.12.1): Beacon liest eine Datei aus Insilos Ordner nicht neu,
-- solange ihr Stand (Änderungszeit:Größe) gleich ist. Mit 0.12.0 kam eine
-- neue Regel dazu — nur, was Insilo als Kundengespräch markiert
-- (`crm: true`). Auf Kais Box am 16.9.2026: Insilo 0.1.102 schrieb die
-- Dateien mit der Markierung neu, das **noch laufende Beacon 0.11.0** las
-- sie Minuten später, kannte die Markierung nicht, übernahm sie und
-- speicherte den neuen Stand. Beacon 0.12.0 hielt sie danach für
-- „unverändert" und prüfte die Markierung nie. Genau die empfohlene
-- Reihenfolge — erst Insilo, dann Beacon — führte hinein.
--
-- „Unverändert" heißt deshalb seit 0.12.1: gleicher Stand **und** mit der
-- jetzigen Fassung gelesen (`insilo_ablage.LESEFASSUNG`). Eine Zeile ohne
-- Fassung stammt von einem älteren Beacon und wird einmal neu gelesen.
-- Ändern sich die Leseregeln wieder, hebt man die Zahl im Code — eine
-- neue Migration braucht es dafür nicht.
--
-- Nur `add column if not exists`: Der Migrationslauf auf der Box führt
-- jede Datei bei jedem Start aus.
-- ========================================================================

alter table public.besprechungen
  add column if not exists ablage_fassung smallint;
