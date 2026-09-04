-- ========================================================================
-- 0013_tickets.sql
-- Tickets: der Anliegen-Strang neben dem Verkaufs-Strang.
-- ========================================================================
--
-- Ein Ticket ist kein Geschäft. Es hat keinen Betrag und keine
-- Wahrscheinlichkeit, dafür eine Dringlichkeit und eine Frist, und es
-- endet nicht „gewonnen" oder „verloren", sondern erledigt. Deshalb
-- eigene Pipelines statt der Deal-Pipelines: Dieselbe Tabelle für beides
-- hätte an jeder zweiten Stelle ein „gilt hier nicht" gebraucht.

create table public.ticket_pipelines (
  id          uuid primary key default uuid_generate_v4(),
  org_id      uuid not null references public.orgs(id) on delete cascade,
  name        text not null,
  is_default  boolean not null default false,
  position    integer not null default 0,
  created_at  timestamptz not null default now(),
  deleted_at  timestamptz
);

create index ticket_pipelines_org_idx on public.ticket_pipelines (org_id, position)
  where deleted_at is null;

-- Die Art einer Stufe sagt, was sie für die Uhr bedeutet:
--   neu               — hereingekommen, noch niemand dran. Die Reaktionszeit läuft.
--   offen             — in Arbeit bei uns. Die Lösungszeit läuft.
--   wartet_auf_kontakt— wir haben geantwortet und warten. Die Uhr pausiert,
--                       denn die Zeit des Kunden ist nicht unsere Frist.
--   abgeschlossen     — erledigt. Die Uhr steht.
create type public.ticket_stufenart as enum ('neu', 'offen', 'wartet_auf_kontakt', 'abgeschlossen');

create table public.ticket_stages (
  id          uuid primary key default uuid_generate_v4(),
  org_id      uuid not null references public.orgs(id) on delete cascade,
  pipeline_id uuid not null references public.ticket_pipelines(id) on delete cascade,
  name        text not null,
  art         public.ticket_stufenart not null default 'offen',
  position    integer not null default 0,
  created_at  timestamptz not null default now()
);

create index ticket_stages_pipeline_idx on public.ticket_stages (pipeline_id, position);

create type public.ticket_prioritaet as enum ('niedrig', 'mittel', 'hoch', 'dringend');

-- Woher das Anliegen kam. Nicht kosmetisch: Ein Ticket aus dem Postfach
-- wird anders beantwortet als eines aus einem Telefonat, und die
-- Auswertung „woher kommt die Last" braucht die Angabe.
create type public.ticket_quelle as enum ('manuell', 'email', 'telefon', 'insilo', 'formular');

create table public.tickets (
  id            uuid primary key default uuid_generate_v4(),
  org_id        uuid not null references public.orgs(id) on delete cascade,
  -- Laufende Nummer je Organisation, wie beim Angebot. Gespeichert wird
  -- die Zahl; die Anzeige (T-2026-0042) entsteht daraus.
  nummer        integer not null,
  betreff       text not null,
  beschreibung  text,
  pipeline_id   uuid not null references public.ticket_pipelines(id),
  stage_id      uuid not null references public.ticket_stages(id),
  prioritaet    public.ticket_prioritaet not null default 'mittel',
  -- Frei, aber aus einer gepflegten Liste (ticket_kategorien).
  kategorie     text,
  quelle        public.ticket_quelle not null default 'manuell',
  -- Wer sich kümmert. NULL heißt „noch niemand" — das ist die Spalte,
  -- nach der die Ansicht „Nicht zugewiesen" fragt.
  owner_id      uuid references public.users(id) on delete set null,
  contact_id    uuid references public.contacts(id) on delete set null,
  company_id    uuid references public.companies(id) on delete set null,
  deal_id       uuid references public.deals(id) on delete set null,
  -- Die drei Zeitpunkte, aus denen sich jede Kennzahl rechnet.
  erste_antwort_am timestamptz,
  geschlossen_am   timestamptz,
  faellig_am       timestamptz,
  custom        jsonb not null default '{}'::jsonb,
  created_by    uuid references public.users(id),
  created_at    timestamptz not null default now(),
  updated_at    timestamptz not null default now(),
  deleted_at    timestamptz
);

create unique index tickets_org_nummer_uniq on public.tickets (org_id, nummer);
create index tickets_org_idx on public.tickets (org_id, updated_at desc) where deleted_at is null;
create index tickets_stage_idx on public.tickets (stage_id) where deleted_at is null;
create index tickets_owner_idx on public.tickets (owner_id) where deleted_at is null;
create index tickets_contact_idx on public.tickets (contact_id) where deleted_at is null;
create index tickets_betreff_trgm on public.tickets using gin (betreff gin_trgm_ops);

-- Kategorien als gepflegte Liste, nicht als Freitext im Ticket: Sonst
-- stehen nach einem Jahr „Rechnung", „rechnung" und „Rechnungsfrage"
-- nebeneinander und jede Auswertung ist wertlos.
create table public.ticket_kategorien (
  id          uuid primary key default uuid_generate_v4(),
  org_id      uuid not null references public.orgs(id) on delete cascade,
  name        text not null,
  position    integer not null default 0,
  is_active   boolean not null default true,
  created_at  timestamptz not null default now()
);

create unique index ticket_kategorien_uniq on public.ticket_kategorien (org_id, lower(name));

-- Verlauf und Aufgaben hängen jetzt auch an Tickets. Damit tragen
-- Zeitleiste, Notizkasten und Aufgabenliste ohne zweite Umsetzung.
alter table public.activities add column if not exists ticket_id uuid
  references public.tickets(id) on delete cascade;
alter table public.tasks add column if not exists ticket_id uuid
  references public.tickets(id) on delete cascade;

create index activities_ticket_idx on public.activities (ticket_id, occurred_at desc);
create index tasks_ticket_idx on public.tasks (ticket_id) where status = 'open';

-- Der CHECK aus 0001 verlangte einen der drei alten Bezüge. Ein Ticket
-- ist ein vierter.
alter table public.activities drop constraint if exists activities_has_target;
alter table public.activities add constraint activities_has_target check (
  company_id is not null or contact_id is not null
  or deal_id is not null or ticket_id is not null
);

-- Die Frist entsteht aus der Dringlichkeit. Die Stunden stehen in den
-- Einstellungen, damit sie je Haus anders sein dürfen — eine Kanzlei
-- misst anders als ein Maschinenbauer.
alter table public.org_settings
  add column if not exists sla_stunden jsonb not null
    default '{"dringend": 4, "hoch": 8, "mittel": 24, "niedrig": 72}'::jsonb;

alter table public.ticket_pipelines  enable row level security;
alter table public.ticket_stages     enable row level security;
alter table public.tickets           enable row level security;
alter table public.ticket_kategorien enable row level security;
alter table public.ticket_pipelines  force row level security;
alter table public.ticket_stages     force row level security;
alter table public.tickets           force row level security;
alter table public.ticket_kategorien force row level security;

create policy ticket_pipelines_org on public.ticket_pipelines
  for all using (org_id in (select public.current_user_orgs()))
  with check (org_id in (select public.current_user_orgs()));

create policy ticket_stages_org on public.ticket_stages
  for all using (org_id in (select public.current_user_orgs()))
  with check (org_id in (select public.current_user_orgs()));

create policy tickets_org on public.tickets
  for all using (org_id in (select public.current_user_orgs()))
  with check (org_id in (select public.current_user_orgs()));

create policy ticket_kategorien_org on public.ticket_kategorien
  for all using (org_id in (select public.current_user_orgs()))
  with check (org_id in (select public.current_user_orgs()));

-- Ansichten gibt es jetzt auch für Tickets. Die Prüfung aus 0012 kannte
-- sie noch nicht.
alter table public.ansichten drop constraint if exists ansichten_entity_check;
alter table public.ansichten add constraint ansichten_entity_check
  check (entity in ('companies', 'contacts', 'tickets'));
