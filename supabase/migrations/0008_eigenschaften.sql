-- ========================================================================
-- 0008_eigenschaften.sql
-- Eigene Eigenschaften an Firma, Kontakt und Geschäft.
--
-- Das feste Schema trägt, was jeder Vertrieb braucht. Was nur dieser
-- Vertrieb braucht — „Serverraum vorhanden", „Kammerzugehörigkeit",
-- „Wartungsvertrag bis" — soll niemand als Migration nachreichen müssen.
--
-- Zwei Teile: die Definition (was es gibt, welcher Typ, welche Auswahl)
-- und der Wert (jsonb am Datensatz, Schlüssel = key der Definition).
-- Der Wert liegt bewusst nicht in einer eigenen Wertetabelle: Ein
-- Datensatz mit acht Eigenschaften wäre sonst neun Zeilen, und jede Liste
-- ein Join zu viel. Geprüft wird beim Schreiben im Backend gegen die
-- Definition — die Datenbank sieht nur JSON.
-- ========================================================================

create type public.property_kind as enum ('text', 'number', 'date', 'bool', 'select');

create table public.property_definitions (
  id          uuid primary key default uuid_generate_v4(),
  org_id      uuid not null references public.orgs(id) on delete cascade,
  -- Der Tabellenname des Objekts. Als Text mit CHECK statt als Enum:
  -- Ein neues Objekt soll keine Typänderung brauchen.
  entity      text not null check (entity in ('companies', 'contacts', 'deals')),
  -- Der Schlüssel im JSON. Aus der Beschriftung abgeleitet und danach
  -- fest — eine Umbenennung ändert die Beschriftung, nie den Schlüssel,
  -- sonst hingen alle alten Werte in der Luft.
  key         text not null,
  label       text not null,
  kind        public.property_kind not null default 'text',
  -- Nur bei `select`: die erlaubten Werte, als JSON-Liste von Texten.
  options     jsonb not null default '[]'::jsonb,
  description text,
  position    integer not null default 0,
  -- Abschalten statt löschen: Die Werte bleiben in den Datensätzen und
  -- werden nur nicht mehr angezeigt. Ein Löschen, das Werte mitnimmt,
  -- wäre ein Datenverlust hinter einem harmlosen Knopf.
  is_active   boolean not null default true,
  created_at  timestamptz not null default now(),
  updated_at  timestamptz not null default now()
);

create unique index property_definitions_uniq on public.property_definitions (org_id, entity, key);
create index property_definitions_entity_idx on public.property_definitions (org_id, entity, position)
  where is_active;

create trigger property_definitions_touch before update on public.property_definitions
  for each row execute function public.touch_updated_at();

alter table public.companies add column if not exists custom jsonb not null default '{}'::jsonb;
alter table public.contacts  add column if not exists custom jsonb not null default '{}'::jsonb;
alter table public.deals     add column if not exists custom jsonb not null default '{}'::jsonb;

alter table public.property_definitions enable row level security;
alter table public.property_definitions force row level security;

create policy property_definitions_org on public.property_definitions
  for all using (org_id in (select public.current_user_orgs()))
  with check (org_id in (select public.current_user_orgs()));
