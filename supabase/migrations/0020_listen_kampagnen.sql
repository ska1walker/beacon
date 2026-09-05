-- ========================================================================
-- 0020_listen_kampagnen.sql
-- Listen, Vorlagen, Kampagnen — Marketing-Post an viele, mit Buch.
--
-- ## Listen, wie HubSpot sie führt
--
-- Eine **statische** Liste ist eine Menge von Hand: Wer drinsteht, steht
-- drin, bis ihn jemand herausnimmt. Eine **aktive** Liste ist eine Frage
-- an den Bestand (derselbe Filter wie bei den Ansichten): Wer die
-- Bedingungen erfüllt, ist drin — heute diese, morgen andere. Beide
-- tragen eine Kampagne; der Unterschied ist, wann sich die Menge ändert.
--
-- ## Warum die Einwilligung nicht in der Liste steht
--
-- Die Liste sagt, wen man *meint*. Ob man ihm schreiben *darf*, sagt der
-- Kontakt (0018). Die Kampagne prüft das beim Start und zählt, wen sie
-- übergangen hat — die Liste bleibt, wie sie ist, und niemand pflegt
-- Einwilligungen an zwei Stellen.
--
-- ## Klicks
--
-- Ein Klick ist ein öffentlicher Link (0018) mit Kampagnenbezug. Gezählt
-- wird am Link, nicht an der Kampagne: Zahlen entstehen beim Lesen aus
-- den Zeilen, damit es keinen Zähler gibt, der falsch werden kann.
-- ========================================================================

create type public.listen_art as enum ('statisch', 'aktiv');

create table public.listen (
  id            uuid primary key default uuid_generate_v4(),
  org_id        uuid not null references public.orgs(id) on delete cascade,
  name          text not null,
  beschreibung  text,
  art           public.listen_art not null default 'statisch',
  -- Nur bei `aktiv`: Bedingungen im Format der Ansichten (0012).
  filter        jsonb not null default '[]'::jsonb,
  verknuepfung  text not null default 'und',
  created_by    uuid references public.users(id),
  created_at    timestamptz not null default now(),
  updated_at    timestamptz not null default now(),
  deleted_at    timestamptz
);

create index if not exists listen_org_idx on public.listen (org_id) where deleted_at is null;

create table public.listen_mitglieder (
  liste_id        uuid not null references public.listen(id) on delete cascade,
  contact_id      uuid not null references public.contacts(id) on delete cascade,
  hinzugefuegt_am timestamptz not null default now(),
  hinzugefuegt_von uuid references public.users(id),
  primary key (liste_id, contact_id)
);

create index if not exists listen_mitglieder_contact_idx on public.listen_mitglieder (contact_id);

create table public.vorlagen (
  id            uuid primary key default uuid_generate_v4(),
  org_id        uuid not null references public.orgs(id) on delete cascade,
  name          text not null,
  betreff       text not null,
  text          text not null,
  created_by    uuid references public.users(id),
  created_at    timestamptz not null default now(),
  updated_at    timestamptz not null default now(),
  deleted_at    timestamptz
);

create index if not exists vorlagen_org_idx on public.vorlagen (org_id) where deleted_at is null;

-- `entwurf` → `laeuft` (Zeilen sind im Buch) → fertig ist, was keine
-- wartende Zeile mehr hat; das wird beim Lesen gerechnet, nicht gespeichert.
create type public.kampagnen_status as enum ('entwurf', 'laeuft', 'abgebrochen');

create table public.kampagnen (
  id            uuid primary key default uuid_generate_v4(),
  org_id        uuid not null references public.orgs(id) on delete cascade,
  name          text not null,
  betreff       text not null default '',
  text          text not null default '',
  liste_id      uuid references public.listen(id) on delete set null,
  status        public.kampagnen_status not null default 'entwurf',
  gestartet_am  timestamptz,
  gestartet_von uuid references public.users(id),
  -- Beim Start festgehalten: wie viele die Liste hatte, wie viele ohne
  -- Einwilligung oder Adresse übergangen wurden.
  empfaenger    integer not null default 0,
  uebergangen   integer not null default 0,
  created_by    uuid references public.users(id),
  created_at    timestamptz not null default now(),
  updated_at    timestamptz not null default now(),
  deleted_at    timestamptz
);

create index if not exists kampagnen_org_idx on public.kampagnen (org_id) where deleted_at is null;

alter table public.mails
  add column if not exists kampagne_id uuid references public.kampagnen(id) on delete set null;
create index if not exists mails_kampagne_idx on public.mails (kampagne_id) where kampagne_id is not null;

alter table public.oeffentliche_links
  add column if not exists kampagne_id uuid references public.kampagnen(id) on delete set null;
create index if not exists oeffentliche_links_kampagne_idx
  on public.oeffentliche_links (kampagne_id) where kampagne_id is not null;

alter table public.listen enable row level security;
alter table public.listen force row level security;
alter table public.listen_mitglieder enable row level security;
alter table public.listen_mitglieder force row level security;
alter table public.vorlagen enable row level security;
alter table public.vorlagen force row level security;
alter table public.kampagnen enable row level security;
alter table public.kampagnen force row level security;

create policy listen_org on public.listen
  for all using (org_id in (select public.current_user_orgs()))
  with check (org_id in (select public.current_user_orgs()));
-- Mitglieder hängen an der Liste — die Liste trägt die Organisation.
create policy listen_mitglieder_org on public.listen_mitglieder
  for all using (liste_id in (select id from public.listen where org_id in (select public.current_user_orgs())))
  with check (liste_id in (select id from public.listen where org_id in (select public.current_user_orgs())));
create policy vorlagen_org on public.vorlagen
  for all using (org_id in (select public.current_user_orgs()))
  with check (org_id in (select public.current_user_orgs()));
create policy kampagnen_org on public.kampagnen
  for all using (org_id in (select public.current_user_orgs()))
  with check (org_id in (select public.current_user_orgs()));
