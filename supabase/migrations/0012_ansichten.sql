-- ========================================================================
-- 0012_ansichten.sql
-- Gespeicherte Ansichten: eine Frage an den Bestand, die man wiederfindet.
-- ========================================================================

-- Eine Ansicht ist ein Segment plus die Art, es anzusehen: welche
-- Bedingungen gelten, welche Spalten die Tabelle zeigt, wonach sortiert
-- wird. In HubSpot ist das der Kern der Arbeit mit Listen — ohne sie ist
-- jede Suche nach dem Schließen des Reiters wieder weg.
create table public.ansichten (
  id          uuid primary key default uuid_generate_v4(),
  org_id      uuid not null references public.orgs(id) on delete cascade,
  entity      text not null check (entity in ('companies', 'contacts', 'tickets')),
  name        text not null,
  -- [{feld, operator, wert}] — geprüft in app/segmente.py, nie roh in SQL.
  filter      jsonb not null default '[]'::jsonb,
  -- 'und' | 'oder'
  verknuepfung text not null default 'und' check (verknuepfung in ('und', 'oder')),
  -- Reihenfolge der Spalten, als Liste von Feldschlüsseln.
  spalten     jsonb not null default '[]'::jsonb,
  sort_feld   text,
  sort_richtung text not null default 'desc' check (sort_richtung in ('asc', 'desc')),
  -- Wem die Ansicht gehört. NULL heißt „für alle" — im geteilten Zugang
  -- der Normalfall, aber wer sich eine eigene Arbeitsliste baut, soll sie
  -- nicht jedem in die Leiste hängen.
  owner_id    uuid references public.users(id) on delete set null,
  position    integer not null default 0,
  created_by  uuid references public.users(id),
  created_at  timestamptz not null default now(),
  updated_at  timestamptz not null default now(),
  deleted_at  timestamptz
);

create index ansichten_org_idx on public.ansichten (org_id, entity, position)
  where deleted_at is null;

-- Zwei Ansichten desselben Objekts dürfen nicht gleich heißen — sonst
-- steht dieselbe Beschriftung zweimal in der Leiste und niemand weiß,
-- welche gemeint ist.
create unique index ansichten_name_uniq
  on public.ansichten (org_id, entity, lower(name))
  where deleted_at is null;

alter table public.ansichten enable row level security;
alter table public.ansichten force row level security;

create policy ansichten_org on public.ansichten
  for all using (org_id in (select public.current_user_orgs()))
  with check (org_id in (select public.current_user_orgs()));
