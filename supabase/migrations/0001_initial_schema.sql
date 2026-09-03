-- ========================================================================
-- 0001_initial_schema.sql
-- Grundschema für aicrm auf Olares.
--
-- Wie bei Insilo: keine eigene auth-Tabelle. Die Identität kommt aus dem
-- Olares-Header X-Bfl-User; wir mappen den Olares-Namen auf eine interne
-- UUID. Alles Weitere hängt an org_id — Mandantentrennung ab Zeile eins.
-- ========================================================================

create extension if not exists "uuid-ossp";
create extension if not exists "pgcrypto";
create extension if not exists "pg_trgm";
-- `vector` fehlt hier mit Absicht. Diese Ausbaustufe rechnet keine
-- Einbettungen; die Erweiterung kommt mit der Ask-Funktion und dann in
-- einer eigenen Migration. Was nicht gebraucht wird, wird nicht angelegt —
-- sonst scheitert die lokale Einrichtung an etwas, das niemand benutzt.

-- ========================================================================
-- IDENTITÄT
-- ========================================================================

create table public.users (
  id              uuid primary key default uuid_generate_v4(),
  olares_username text not null unique,
  email           text,
  display_name    text,
  created_at      timestamptz not null default now(),
  last_seen_at    timestamptz not null default now(),
  deleted_at      timestamptz
);

create index users_olares_idx on public.users (olares_username) where deleted_at is null;

create table public.orgs (
  id              uuid primary key default uuid_generate_v4(),
  name            text not null,
  slug            text unique not null,
  settings        jsonb not null default '{}'::jsonb,
  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now(),
  deleted_at      timestamptz
);

create type public.user_role as enum ('owner', 'admin', 'member', 'viewer');

create table public.user_org_roles (
  user_id         uuid not null references public.users(id) on delete cascade,
  org_id          uuid not null references public.orgs(id) on delete cascade,
  role            public.user_role not null default 'member',
  joined_at       timestamptz not null default now(),
  primary key (user_id, org_id)
);

create index user_org_roles_user_idx on public.user_org_roles (user_id);
create index user_org_roles_org_idx on public.user_org_roles (org_id);

-- ========================================================================
-- FIRMEN
--
-- lifecycle_stage folgt der HubSpot-Leiter, aber gekürzt auf das, was ein
-- Zwei-Mann-Vertrieb wirklich unterscheidet. Wer mehr Stufen einführt,
-- führt sie hier ein — nicht als freien Text in der Oberfläche.
-- ========================================================================

create type public.lifecycle_stage as enum (
  'lead',          -- kennt uns, ungeprüft
  'qualified',     -- Bedarf und Budget plausibel
  'opportunity',   -- offener Deal vorhanden
  'customer',      -- gekauft
  'partner',
  'disqualified'
);

create table public.companies (
  id              uuid primary key default uuid_generate_v4(),
  org_id          uuid not null references public.orgs(id) on delete cascade,
  name            text not null,
  domain          text,
  industry        text,
  employee_count  integer,
  city            text,
  country         text default 'DE',
  phone           text,
  website         text,
  lifecycle_stage public.lifecycle_stage not null default 'lead',
  source          text,                                  -- Messe, Empfehlung, Website …
  description     text,
  -- Was die KI über die Firma zusammengetragen hat. Getrennt von
  -- description, damit von Hand Geschriebenes nie überschrieben wird.
  ai_summary      text,
  ai_summary_at   timestamptz,
  owner_id        uuid references public.users(id),
  created_by      uuid references public.users(id),
  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now(),
  deleted_at      timestamptz
);

create index companies_org_idx on public.companies (org_id) where deleted_at is null;
create index companies_name_trgm on public.companies using gin (name gin_trgm_ops);
create unique index companies_org_domain_uniq on public.companies (org_id, lower(domain))
  where domain is not null and deleted_at is null;

-- ========================================================================
-- KONTAKTE
-- ========================================================================

create table public.contacts (
  id              uuid primary key default uuid_generate_v4(),
  org_id          uuid not null references public.orgs(id) on delete cascade,
  company_id      uuid references public.companies(id) on delete set null,
  first_name      text,
  last_name       text,
  email           text,
  phone           text,
  mobile          text,
  job_title       text,
  -- Entscheider, Anwender, Blockierer: wer im Kaufprozess was tut.
  buying_role     text,
  linkedin_url    text,
  lifecycle_stage public.lifecycle_stage not null default 'lead',
  source          text,
  notes           text,
  ai_summary      text,
  ai_summary_at   timestamptz,
  owner_id        uuid references public.users(id),
  created_by      uuid references public.users(id),
  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now(),
  deleted_at      timestamptz
);

create index contacts_org_idx on public.contacts (org_id) where deleted_at is null;
create index contacts_company_idx on public.contacts (company_id) where deleted_at is null;
create unique index contacts_org_email_uniq on public.contacts (org_id, lower(email))
  where email is not null and deleted_at is null;
create index contacts_name_trgm on public.contacts
  using gin ((coalesce(first_name,'') || ' ' || coalesce(last_name,'')) gin_trgm_ops);

-- ========================================================================
-- PIPELINES
--
-- Stufen sind Datensätze, keine Enum-Werte: der Vertrieb ändert seinen
-- Ablauf öfter, als wir migrieren wollen. Die Wahrscheinlichkeit hängt an
-- der Stufe, damit die Prognose ohne Zutun rechnet.
-- ========================================================================

create table public.pipelines (
  id              uuid primary key default uuid_generate_v4(),
  org_id          uuid not null references public.orgs(id) on delete cascade,
  name            text not null,
  is_default      boolean not null default false,
  position        integer not null default 0,
  created_at      timestamptz not null default now(),
  deleted_at      timestamptz
);

create index pipelines_org_idx on public.pipelines (org_id) where deleted_at is null;

create type public.stage_kind as enum ('open', 'won', 'lost');

create table public.pipeline_stages (
  id              uuid primary key default uuid_generate_v4(),
  org_id          uuid not null references public.orgs(id) on delete cascade,
  pipeline_id     uuid not null references public.pipelines(id) on delete cascade,
  name            text not null,
  kind            public.stage_kind not null default 'open',
  probability     numeric(4,3) not null default 0.100,   -- 0,000 … 1,000
  position        integer not null default 0,
  created_at      timestamptz not null default now()
);

create index pipeline_stages_pipeline_idx on public.pipeline_stages (pipeline_id, position);

-- ========================================================================
-- DEALS
-- ========================================================================

create type public.deal_product as enum (
  'assistent',
  'analyst',
  'experte',
  'service',
  'sonstiges'
);

create table public.deals (
  id              uuid primary key default uuid_generate_v4(),
  org_id          uuid not null references public.orgs(id) on delete cascade,
  company_id      uuid references public.companies(id) on delete set null,
  pipeline_id     uuid not null references public.pipelines(id),
  stage_id        uuid not null references public.pipeline_stages(id),
  name            text not null,
  product         public.deal_product not null default 'sonstiges',
  -- Netto in Cent. Kein float: 9.900 € sind 990000, und das bleibt exakt.
  amount_cents    bigint not null default 0,
  currency        char(3) not null default 'EUR',
  service_days    integer,
  close_date      date,
  -- Gefüllt, sobald der Deal auf einer Stufe der Art won/lost landet.
  closed_at       timestamptz,
  lost_reason     text,
  next_step       text,
  ai_summary      text,
  ai_summary_at   timestamptz,
  owner_id        uuid references public.users(id),
  created_by      uuid references public.users(id),
  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now(),
  deleted_at      timestamptz
);

create index deals_org_idx on public.deals (org_id) where deleted_at is null;
create index deals_stage_idx on public.deals (stage_id) where deleted_at is null;
create index deals_company_idx on public.deals (company_id) where deleted_at is null;
create index deals_close_date_idx on public.deals (org_id, close_date) where deleted_at is null;

-- Ein Deal hat mehrere Beteiligte. Die Rolle steht hier und nicht am
-- Kontakt: dieselbe Person kann im einen Geschäft entscheiden und im
-- nächsten nur mitreden.
create table public.deal_contacts (
  deal_id         uuid not null references public.deals(id) on delete cascade,
  contact_id      uuid not null references public.contacts(id) on delete cascade,
  role            text,
  primary key (deal_id, contact_id)
);

-- ========================================================================
-- AKTIVITÄTEN — der Verlauf
--
-- Eine Tabelle für alles, was am Datensatz passiert ist: Notiz, Anruf,
-- E-Mail, Termin, Stufenwechsel, KI-Ergebnis. Getrennte Tabellen je Art
-- hätten drei Abfragen für eine Zeitleiste bedeutet.
-- ========================================================================

create type public.activity_kind as enum (
  'note',
  'call',
  'email',
  'meeting',
  'task',
  'stage_change',
  'ai',            -- von der KI erzeugt, immer als solches gekennzeichnet
  'system'
);

create table public.activities (
  id              uuid primary key default uuid_generate_v4(),
  org_id          uuid not null references public.orgs(id) on delete cascade,
  kind            public.activity_kind not null,
  subject         text,
  body            text,
  occurred_at     timestamptz not null default now(),
  -- Bezug: mindestens eines gesetzt, erzwungen per CHECK.
  company_id      uuid references public.companies(id) on delete cascade,
  contact_id      uuid references public.contacts(id) on delete cascade,
  deal_id         uuid references public.deals(id) on delete cascade,
  -- Struktur je Art: Dauer eines Anrufs, alte und neue Stufe, Modellname.
  payload         jsonb not null default '{}'::jsonb,
  created_by      uuid references public.users(id),
  created_at      timestamptz not null default now(),
  constraint activities_has_target check (
    company_id is not null or contact_id is not null or deal_id is not null
  )
);

create index activities_company_idx on public.activities (company_id, occurred_at desc);
create index activities_contact_idx on public.activities (contact_id, occurred_at desc);
create index activities_deal_idx on public.activities (deal_id, occurred_at desc);
create index activities_org_idx on public.activities (org_id, occurred_at desc);

-- ========================================================================
-- AUFGABEN
-- ========================================================================

create type public.task_status as enum ('open', 'done', 'cancelled');

create table public.tasks (
  id              uuid primary key default uuid_generate_v4(),
  org_id          uuid not null references public.orgs(id) on delete cascade,
  title           text not null,
  body            text,
  status          public.task_status not null default 'open',
  due_at          timestamptz,
  company_id      uuid references public.companies(id) on delete cascade,
  contact_id      uuid references public.contacts(id) on delete cascade,
  deal_id         uuid references public.deals(id) on delete cascade,
  assigned_to     uuid references public.users(id),
  created_by      uuid references public.users(id),
  completed_at    timestamptz,
  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now()
);

create index tasks_org_open_idx on public.tasks (org_id, due_at) where status = 'open';
create index tasks_assigned_idx on public.tasks (assigned_to, due_at) where status = 'open';

-- ========================================================================
-- EINSTELLUNGEN JE ORGANISATION
--
-- Es gibt bewusst keinen Vorgabewert für die LLM-Adresse — genau wie bei
-- Insilo seit v0.1.72. Wer kein Modell einträgt, bekommt ein CRM ohne KI,
-- aber kein CRM, das heimlich irgendwohin spricht.
-- ========================================================================

create table public.org_settings (
  org_id          uuid primary key references public.orgs(id) on delete cascade,
  llm_base_url    text,
  llm_model       text,
  -- Im Klartext, geschützt durch RLS — wie bei Insilo. Eine Verschlüsselung
  -- in der Spalte bräuchte einen Schlüssel, der irgendwo liegen muss; auf
  -- der eigenen Box gewinnt das nichts und verliert die Lesbarkeit.
  llm_api_key     text,
  default_currency char(3) not null default 'EUR',
  locale          text not null default 'de',
  updated_at      timestamptz not null default now(),
  updated_by      uuid references public.users(id)
);

-- ========================================================================
-- AUDIT
-- ========================================================================

create table public.audit_log (
  id              bigserial primary key,
  org_id          uuid not null references public.orgs(id) on delete cascade,
  actor_id        uuid references public.users(id),
  action          text not null,                         -- create | update | delete
  entity          text not null,                         -- companies | contacts | deals …
  entity_id       uuid,
  diff            jsonb not null default '{}'::jsonb,
  created_at      timestamptz not null default now()
);

create index audit_log_org_idx on public.audit_log (org_id, created_at desc);
create index audit_log_entity_idx on public.audit_log (entity, entity_id);

-- ========================================================================
-- updated_at automatisch fortschreiben
-- ========================================================================

create or replace function public.touch_updated_at()
returns trigger
language plpgsql
as $$
begin
  new.updated_at = now();
  return new;
end;
$$;

create trigger companies_touch before update on public.companies
  for each row execute function public.touch_updated_at();
create trigger contacts_touch before update on public.contacts
  for each row execute function public.touch_updated_at();
create trigger deals_touch before update on public.deals
  for each row execute function public.touch_updated_at();
create trigger tasks_touch before update on public.tasks
  for each row execute function public.touch_updated_at();
create trigger orgs_touch before update on public.orgs
  for each row execute function public.touch_updated_at();
