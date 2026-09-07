-- ========================================================================
-- 0025_podcasts.sql
-- Gespräch vorbereiten — der Bestand als kurzer Podcast.
--
-- Vor einem Kundengespräch liest niemand dreißig Verlaufseinträge. Ein
-- Gespräch zweier Stimmen über die Firma — wer sie sind, was zuletzt
-- geschah, was offen ist, was Kunden gesagt haben — hört man auf dem Weg.
-- Das Sprachmodell schreibt das Skript aus dem Bestand, die Sprachausgabe
-- auf der Box spricht es. Nichts verlässt die Box.
--
-- `org_settings` bekommt die Sprachausgabe: Adresse, Schlüssel, je Stimme
-- ein Modell (Speaches führt Piper-Stimmen als Modelle) und ob die
-- Vorbereitung vor Terminen von selbst läuft. `podcasts` hält je Folge
-- Skript, Segmente und den Pfad zur Datei unter /app/data — die Datei
-- überlebt eine Deinstallation, die Zeile geht in der Sicherung mit.
-- ========================================================================

alter table public.org_settings
  add column if not exists tts_endpoint_url    text,
  add column if not exists tts_api_key         text,
  add column if not exists tts_modell          text not null default 'speaches-ai/piper-de_DE-thorsten-high',
  add column if not exists tts_stimme          text,
  add column if not exists tts_modell_2        text not null default 'speaches-ai/piper-de_DE-kerstin-low',
  add column if not exists tts_stimme_2        text,
  add column if not exists podcast_automatisch boolean not null default false;

create table if not exists public.podcasts (
  id           uuid primary key default uuid_generate_v4(),
  org_id       uuid not null references public.orgs(id) on delete cascade,
  entity       text not null check (entity in ('companies', 'deals')),
  entity_id    uuid not null,
  -- Der Termin, für den die Folge entstand — von selbst oder von Hand.
  task_id      uuid references public.tasks(id) on delete set null,
  anlass       text,
  titel        text,
  status       text not null default 'laeuft' check (status in ('laeuft', 'fertig', 'fehler')),
  fortschritt  jsonb not null default '{}'::jsonb,
  skript       text,
  segmente     jsonb not null default '[]'::jsonb,
  dauer_s      integer,
  -- Relativ zu app_data, mit der Org-Kennung von damals im Pfad. Nach
  -- einer Wiederherstellung hat die Organisation eine neue Kennung — der
  -- Pfad wird deshalb gespeichert, nie neu abgeleitet.
  datei        text,
  bytes        bigint,
  modell       text,
  stimme       text,
  llm_modell   text,
  fehler       text,
  created_by   uuid references public.users(id),
  created_at   timestamptz not null default now(),
  updated_at   timestamptz not null default now(),
  deleted_at   timestamptz
);

create index if not exists podcasts_entity_idx on public.podcasts (org_id, entity, entity_id, created_at desc);
-- Ein Termin, eine Folge — auch wenn zwei Schleifen gleichzeitig nachsehen.
create unique index if not exists podcasts_task_uniq on public.podcasts (task_id) where task_id is not null and deleted_at is null;

alter table public.podcasts enable row level security;
alter table public.podcasts force row level security;

create policy podcasts_org on public.podcasts
  for all using (org_id in (select public.current_user_orgs()))
  with check (org_id in (select public.current_user_orgs()));
