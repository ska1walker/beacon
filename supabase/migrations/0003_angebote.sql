-- ========================================================================
-- 0003_angebote.sql
-- Produktkatalog und Angebote.
--
-- Bis hierher endete die Kette bei der Pipelinestufe „Angebot", ohne dass
-- es ein Angebot gab. Damit fehlte genau das Stück, um das sich der
-- Vertrieb dreht: Was steht drin, was kostet es, seit wann liegt es beim
-- Kunden und was hat er gesagt.
-- ========================================================================

-- ========================================================================
-- PRODUKTKATALOG
--
-- Die Leiter Assistent / Analyst / Experte steht als Datensatz, nicht als
-- Aufzählungstyp und nicht als Zahl in der Oberfläche: Preise ändern
-- sich, und ein Listenpreis, der an drei Stellen gepflegt wird, läuft
-- auseinander. Der Betrag im Angebot wird beim Anlegen kopiert — ein
-- späterer Listenpreis darf ein liegendes Angebot nicht rückwirkend
-- verändern.
-- ========================================================================

create type public.product_kind as enum (
  'system',        -- die drei Produkte
  'hardware',
  'service',       -- Servicetage, Einführung
  'subscription'   -- Wartung, Support je Jahr
);

create table public.products (
  id                  uuid primary key default uuid_generate_v4(),
  org_id              uuid not null references public.orgs(id) on delete cascade,
  key                 text not null,               -- assistent, analyst, …
  name                text not null,
  description         text,
  kind                public.product_kind not null default 'system',
  list_price_cents    bigint not null default 0,
  default_service_days integer,
  position            integer not null default 0,
  is_active           boolean not null default true,
  created_at          timestamptz not null default now(),
  updated_at          timestamptz not null default now()
);

create unique index products_org_key_uniq on public.products (org_id, key);
create index products_org_idx on public.products (org_id, position) where is_active;

-- ========================================================================
-- ANGEBOTE
-- ========================================================================

create type public.quote_status as enum (
  'draft',      -- in Arbeit, beim Kunden noch nichts
  'sent',       -- raus
  'accepted',
  'rejected',
  'expired'     -- Bindefrist abgelaufen, ohne Antwort
);

create table public.quotes (
  id              uuid primary key default uuid_generate_v4(),
  org_id          uuid not null references public.orgs(id) on delete cascade,
  deal_id         uuid not null references public.deals(id) on delete cascade,
  -- Fortlaufend je Organisation. Die sichtbare Nummer entsteht daraus
  -- (AG-2026-0007); gespeichert wird die Zahl, damit sie sich fortzählen
  -- lässt, ohne einen Text zu zerlegen.
  number_seq      integer not null,
  status          public.quote_status not null default 'draft',
  title           text not null default 'Angebot',
  intro_text      text,
  terms_text      text,
  -- Nachlass auf die Summe, in Cent. Ein Prozentsatz auf der Ebene des
  -- Angebots wäre bei gemischten Positionen nicht mehr nachvollziehbar.
  discount_cents  bigint not null default 0,
  tax_rate        numeric(4,3) not null default 0.190,
  valid_until     date,
  sent_at         timestamptz,
  decided_at      timestamptz,
  decision_note   text,
  created_by      uuid references public.users(id),
  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now(),
  deleted_at      timestamptz
);

create unique index quotes_org_number_uniq on public.quotes (org_id, number_seq);
create index quotes_deal_idx on public.quotes (deal_id) where deleted_at is null;
create index quotes_org_status_idx on public.quotes (org_id, status) where deleted_at is null;

create table public.quote_items (
  id              uuid primary key default uuid_generate_v4(),
  org_id          uuid not null references public.orgs(id) on delete cascade,
  quote_id        uuid not null references public.quotes(id) on delete cascade,
  -- Nur die Herkunft, keine Preisbindung: Der Betrag steht in dieser
  -- Zeile und bleibt, was er beim Schreiben des Angebots war.
  product_id      uuid references public.products(id) on delete set null,
  position        integer not null default 0,
  title           text not null,
  description     text,
  quantity        numeric(10,2) not null default 1,
  unit_price_cents bigint not null default 0,
  discount_percent numeric(5,2) not null default 0,
  created_at      timestamptz not null default now()
);

create index quote_items_quote_idx on public.quote_items (quote_id, position);

create trigger quotes_touch before update on public.quotes
  for each row execute function public.touch_updated_at();
create trigger products_touch before update on public.products
  for each row execute function public.touch_updated_at();

-- ========================================================================
-- Zeilensicherheit — gleiches Muster, gleiche Härte
-- ========================================================================

alter table public.products    enable row level security;
alter table public.quotes      enable row level security;
alter table public.quote_items enable row level security;

alter table public.products    force row level security;
alter table public.quotes      force row level security;
alter table public.quote_items force row level security;

create policy products_org on public.products
  for all using (org_id in (select public.current_user_orgs()))
  with check (org_id in (select public.current_user_orgs()));

create policy quotes_org on public.quotes
  for all using (org_id in (select public.current_user_orgs()))
  with check (org_id in (select public.current_user_orgs()));

create policy quote_items_org on public.quote_items
  for all using (org_id in (select public.current_user_orgs()))
  with check (org_id in (select public.current_user_orgs()));

-- ========================================================================
-- Angebot als Aktivitätsart
--
-- Ein verschicktes Angebot gehört in dieselbe Zeitleiste wie ein Anruf.
-- Ein eigener Verlauf je Art hätte drei Abfragen für eine Ansicht bedeutet.
-- ========================================================================

alter type public.activity_kind add value if not exists 'quote';
