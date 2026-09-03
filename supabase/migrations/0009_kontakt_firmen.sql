-- ========================================================================
-- 0009_kontakt_firmen.sql
-- Ein Kontakt, mehrere Firmen.
--
-- Ein Steuerberater sitzt in zwei Kanzleien, ein IT-Leiter betreut die
-- Holding und zwei Töchter. `contacts.company_id` bleibt die Hauptfirma —
-- die, die in Listen steht und im Angebot oben. Alles Weitere liegt hier.
-- ========================================================================

create table public.contact_companies (
  contact_id  uuid not null references public.contacts(id) on delete cascade,
  company_id  uuid not null references public.companies(id) on delete cascade,
  org_id      uuid not null references public.orgs(id) on delete cascade,
  role        text,                       -- was die Person dort tut
  created_at  timestamptz not null default now(),
  primary key (contact_id, company_id)
);

create index contact_companies_company_idx on public.contact_companies (company_id);

alter table public.contact_companies enable row level security;
alter table public.contact_companies force row level security;

create policy contact_companies_org on public.contact_companies
  for all using (org_id in (select public.current_user_orgs()))
  with check (org_id in (select public.current_user_orgs()));
