-- ========================================================================
-- 0018_oeffentliche_links.sql
-- Ein öffentlicher Pfad — schmal, tokenbasiert, ohne Datenzugriff.
--
-- Drei Dinge muss ein Empfänger von außen auslösen können, aus seinem
-- Mailprogramm, ohne Konto: eine Einwilligung bestätigen, sich abmelden,
-- einen Link anklicken. Beacon ist `internal` und hat keine öffentliche
-- Adresse (gemessen, docs/BETRIEB.md). Deshalb bekommt es einen zweiten,
-- öffentlichen Entrance, hinter dem **nur** diese drei Wege liegen —
-- eine eigene Anwendung auf einem eigenen Port, die nichts anderes kann.
-- HubSpot trennt seine Tracking-Domain aus demselben Grund von der App.
--
-- Jeder Link ist eine Zeile hier, angesprochen über ein zufälliges Token.
-- Die Policy unten gibt genau die eine angesprochene Zeile frei, sonst
-- nichts (Muster: webhook_sources_selbstauskunft). Was danach geschrieben
-- wird, läuft im Kontext des Organisationseigentümers — wie im Eingang.
--
-- Einwilligung steht am Kontakt, mit Nachweis. Marketing-Post in
-- Deutschland braucht sie belegbar (§7 UWG, DSGVO); „irgendwann mal
-- angemeldet“ ist kein Beleg. `bestandskunde` ist die Ausnahme aus
-- §7 Abs. 3 UWG und wird bewusst gesetzt, nie abgeleitet.
-- ========================================================================

create type public.link_art as enum ('bestaetigen', 'abmelden', 'klick');

create type public.einwilligung as enum
  ('keine', 'angefragt', 'bestaetigt', 'bestandskunde', 'abgemeldet');

alter table public.contacts
  add column if not exists marketing_einwilligung public.einwilligung not null default 'keine',
  add column if not exists einwilligung_am       timestamptz,
  add column if not exists einwilligung_quelle   text,
  -- Der Beleg: Zeitpunkt, Adresse, Token, Herkunft. Ohne ihn ist eine
  -- Einwilligung eine Behauptung.
  add column if not exists einwilligung_nachweis jsonb,
  add column if not exists abgemeldet_am         timestamptz;

create index if not exists contacts_einwilligung_idx
  on public.contacts (org_id, marketing_einwilligung) where deleted_at is null;

create table public.oeffentliche_links (
  id            uuid primary key default uuid_generate_v4(),
  org_id        uuid not null references public.orgs(id) on delete cascade,
  -- 32 zufällige Bytes, URL-sicher. Erraten ist keine Option.
  token         text not null unique,
  art           public.link_art not null,
  contact_id    uuid references public.contacts(id) on delete cascade,
  -- Nur bei `klick`: wohin es nach dem Zählen geht.
  ziel_url      text,
  -- Ein Bestätigungslink gilt einmal. Ein Abmeldelink gilt immer — er
  -- darf nie „abgelaufen“ sagen, das wäre eine verweigerte Abmeldung.
  einmalig      boolean not null default false,
  gueltig_bis   timestamptz,
  benutzt_am    timestamptz,
  benutzt_anzahl integer not null default 0,
  payload       jsonb not null default '{}'::jsonb,
  created_at    timestamptz not null default now()
);

create index if not exists oeffentliche_links_contact_idx
  on public.oeffentliche_links (contact_id, art);

alter table public.oeffentliche_links enable row level security;
alter table public.oeffentliche_links force row level security;

create policy oeffentliche_links_org on public.oeffentliche_links
  for all using (org_id in (select public.current_user_orgs()))
  with check (org_id in (select public.current_user_orgs()));

-- Der öffentliche Pfad hat keine Identität. Er darf genau die Zeile
-- lesen, deren Token er nennt — und schreiben darf er über sie nichts.
create policy oeffentliche_links_selbstauskunft on public.oeffentliche_links
  for select
  using (token = nullif(current_setting('app.oeffentlicher_link', true), ''));
