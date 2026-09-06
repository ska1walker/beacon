-- ========================================================================
-- 0023_erkenntnisse.sql
-- Aus Gesprächsnotizen lernen, was am Produkt zu tun ist.
--
-- Was Kunden in Gesprächen sagen — Lob, Kritik, Wünsche, Einwände — steht
-- verstreut im Verlauf. Drei Tabellen machen daraus etwas, das man lesen
-- kann: `aussagen` sind die einzelnen Sätze, die das Modell aus einer
-- Notiz zieht, mit Art und Produkt; `auswertungen` merkt sich, welche
-- Notiz schon gelesen wurde, damit nichts zweimal zählt; `themenlaeufe`
-- sind die Bündelungen — je Lauf eine Liste von Themen mit den Aussagen
-- dahinter und dem, was das fürs Produkt heißt. Gerechnet wird aus den
-- Aussagen, gespeichert wird der Lauf: Man sieht, was gestern galt.
-- ========================================================================

create table if not exists public.aussagen (
  id           uuid primary key default uuid_generate_v4(),
  org_id       uuid not null references public.orgs(id) on delete cascade,
  activity_id  uuid not null references public.activities(id) on delete cascade,
  company_id   uuid references public.companies(id) on delete set null,
  art          text not null check (art in ('lob', 'kritik', 'wunsch', 'einwand', 'frage')),
  produkt      text,
  text         text not null,
  zitat        text,
  created_at   timestamptz not null default now()
);

create index if not exists aussagen_org_idx on public.aussagen (org_id, created_at desc);
create index if not exists aussagen_activity_idx on public.aussagen (activity_id);

create table if not exists public.auswertungen (
  activity_id     uuid primary key references public.activities(id) on delete cascade,
  org_id          uuid not null references public.orgs(id) on delete cascade,
  ausgewertet_am  timestamptz not null default now(),
  modell          text,
  anzahl          integer not null default 0
);

create table if not exists public.themenlaeufe (
  id               uuid primary key default uuid_generate_v4(),
  org_id           uuid not null references public.orgs(id) on delete cascade,
  zeitraum_tage    integer not null default 90,
  status           text not null default 'laeuft' check (status in ('laeuft', 'fertig', 'fehler')),
  fortschritt      jsonb not null default '{}'::jsonb,
  aussagen_anzahl  integer not null default 0,
  themen           jsonb not null default '[]'::jsonb,
  fehler           text,
  modell           text,
  created_by       uuid references public.users(id),
  created_at       timestamptz not null default now(),
  updated_at       timestamptz not null default now()
);

create index if not exists themenlaeufe_org_idx on public.themenlaeufe (org_id, created_at desc);

alter table public.aussagen enable row level security;
alter table public.aussagen force row level security;
alter table public.auswertungen enable row level security;
alter table public.auswertungen force row level security;
alter table public.themenlaeufe enable row level security;
alter table public.themenlaeufe force row level security;

create policy aussagen_org on public.aussagen
  for all using (org_id in (select public.current_user_orgs()))
  with check (org_id in (select public.current_user_orgs()));
create policy auswertungen_org on public.auswertungen
  for all using (org_id in (select public.current_user_orgs()))
  with check (org_id in (select public.current_user_orgs()));
create policy themenlaeufe_org on public.themenlaeufe
  for all using (org_id in (select public.current_user_orgs()))
  with check (org_id in (select public.current_user_orgs()));
