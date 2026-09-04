-- ========================================================================
-- 0014_aufgaben.sql
-- Aufgaben bekommen Art, Dringlichkeit und eine Phase.
-- ========================================================================
--
-- Bisher war eine Aufgabe ein Titel mit Frist und drei Zuständen. Für
-- eine Liste, nach der man den Tag plant, fehlten drei Angaben:
--
--   **Art** — ein Anruf wird anders erledigt als eine E-Mail. Wer seinen
--   Tag ordnet, will die Anrufe am Stück machen.
--   **Dringlichkeit** — sonst steht alles gleich wichtig da, und das
--   heißt: nichts ist wichtig.
--   **Phase** — „angefangen“ ist weder offen noch erledigt. Ohne diesen
--   Zwischenstand steht eine halbfertige Aufgabe jeden Morgen wieder da,
--   als hätte niemand sie angefasst.
--
-- `status` bleibt, was es war, und trägt weiter die Entscheidung
-- offen/erledigt/verworfen. Die Phase ist die feinere Auskunft
-- **innerhalb** von „offen"; beide werden beim Abhaken zusammen gesetzt.

create type public.aufgaben_art as enum ('todo', 'anruf', 'email', 'termin');
create type public.aufgaben_phase as enum ('nicht_gestartet', 'in_arbeit', 'wartet');

alter table public.tasks
  add column if not exists art public.aufgaben_art not null default 'todo',
  add column if not exists phase public.aufgaben_phase not null default 'nicht_gestartet',
  add column if not exists prioritaet public.ticket_prioritaet not null default 'mittel',
  -- Erledigte Aufgaben brauchen keine Phase mehr; für die offenen ist sie
  -- die zweite Sortierung nach der Frist.
  add column if not exists updated_by uuid references public.users(id);

create index tasks_phase_idx on public.tasks (org_id, phase) where status = 'open';
create index tasks_art_idx on public.tasks (org_id, art) where status = 'open';

-- Ansichten gelten jetzt auch für Aufgaben.
alter table public.ansichten drop constraint if exists ansichten_entity_check;
alter table public.ansichten add constraint ansichten_entity_check
  check (entity in ('companies', 'contacts', 'tickets', 'tasks'));
