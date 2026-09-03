-- ========================================================================
-- 0006_eingang.sql
-- Eingehende Ereignisse aus anderen Anwendungen auf derselben Box.
--
-- Zuerst: Insilo. Nach einer Besprechung schickt Insilo ein signiertes
-- Ereignis mit dem fertigen Protokoll. Das gehört an den Deal, zu dem das
-- Gespräch gehörte — und genau das ist der Punkt, an dem die beiden
-- Anwendungen zusammen mehr sind als jede für sich.
--
-- Der Vertrag steht in insilo/docs/WEBHOOKS.md und wird hier eingehalten,
-- nicht neu erfunden.
-- ========================================================================

create table public.webhook_sources (
  id          uuid primary key default uuid_generate_v4(),
  org_id      uuid not null references public.orgs(id) on delete cascade,
  name        text not null,
  kind        text not null default 'insilo',
  -- Das geteilte Geheimnis für die HMAC-Prüfung. Es steht im Klartext,
  -- geschützt durch die Zeilensicherheit — verschlüsseln hieße, den
  -- Schlüssel dafür anderswo abzulegen, und das gewinnt auf der eigenen
  -- Box nichts.
  secret      text not null,
  is_active   boolean not null default true,
  created_at  timestamptz not null default now(),
  last_seen_at timestamptz
);

create index webhook_sources_org_idx on public.webhook_sources (org_id) where is_active;

create type public.eingang_status as enum ('offen', 'zugeordnet', 'verworfen');

create table public.eingang (
  id            uuid primary key default uuid_generate_v4(),
  org_id        uuid not null references public.orgs(id) on delete cascade,
  source_id     uuid not null references public.webhook_sources(id) on delete cascade,
  -- Der Idempotenzschlüssel des Absenders. Über Wiederholungen derselben
  -- Auslieferung bleibt er gleich — genau dafür ist er da.
  delivery_id   text not null,
  event         text not null,
  external_id   text,                       -- die Besprechungs-Kennung bei Insilo
  titel         text,
  markdown      text,
  occurred_at   timestamptz,
  payload       jsonb not null default '{}'::jsonb,
  status        public.eingang_status not null default 'offen',
  company_id    uuid references public.companies(id) on delete set null,
  deal_id       uuid references public.deals(id) on delete set null,
  activity_id   uuid references public.activities(id) on delete set null,
  -- Was die Zuordnung vorgeschlagen hat und warum. Ohne die Begründung
  -- ist eine automatische Zuordnung eine Behauptung.
  zuordnung_grund text,
  created_at    timestamptz not null default now()
);

create unique index eingang_lieferung_uniq on public.eingang (source_id, delivery_id);
create index eingang_offen_idx on public.eingang (org_id, created_at desc) where status = 'offen';
create index eingang_extern_idx on public.eingang (org_id, external_id);

-- Aktivitäten aus fremder Quelle sollen nicht doppelt entstehen, wenn
-- dieselbe Besprechung ein zweites Mal gemeldet wird.
alter table public.activities
  add column if not exists external_source text,
  add column if not exists external_id     text;

create unique index if not exists activities_extern_uniq
  on public.activities (org_id, external_source, external_id)
  where external_source is not null and external_id is not null;

alter table public.webhook_sources enable row level security;
alter table public.eingang         enable row level security;
alter table public.webhook_sources force row level security;
alter table public.eingang         force row level security;

create policy webhook_sources_org on public.webhook_sources
  for all using (org_id in (select public.current_user_orgs()))
  with check (org_id in (select public.current_user_orgs()));

-- Selbstauskunft für den Empfangspfad.
--
-- Ein eingehender Webhook trägt keine Olares-Identität — der Absender ist
-- eine Maschine. Um die Signatur prüfen zu können, muss das Backend aber
-- genau eine Zeile lesen: die der angesprochenen Quelle. Unter FORCE ROW
-- LEVEL SECURITY geht das ohne Nutzerkontext nicht, und den gibt es an
-- dieser Stelle noch nicht — Henne und Ei.
--
-- Statt FORCE für diese Tabelle abzuschalten (dann sähe die Liste unter
-- /api/quellen die Quellen aller Mandanten), gibt diese Policy genau eine
-- Zeile frei: die, deren Kennung das Backend vorher in die Sitzungs-
-- variable geschrieben hat. Mehr als die eine angesprochene Quelle ist
-- damit nicht lesbar, und geschrieben wird über sie gar nichts.
create policy webhook_sources_selbstauskunft on public.webhook_sources
  for select
  using (id::text = nullif(current_setting('app.webhook_source', true), ''));

create policy eingang_org on public.eingang
  for all using (org_id in (select public.current_user_orgs()))
  with check (org_id in (select public.current_user_orgs()));
