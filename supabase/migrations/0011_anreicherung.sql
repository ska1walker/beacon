-- ========================================================================
-- 0011_anreicherung.sql
-- Firmen und Kontakte werden aus öffentlichen Quellen angereichert.
-- ========================================================================

-- Kontakte tragen ihre LinkedIn-Adresse seit 0001; Firmen bekommen sie
-- jetzt auch. Die Unternehmensseite ist die verlässlichste Quelle für
-- Branche und Größe.
alter table public.companies
  add column if not exists linkedin_url text;

-- Der Suchdienst. Ohne ihn kennt die Anreicherung nur die Website der
-- Firma; mit ihm findet sie Website, LinkedIn-Seite und Personen über die
-- Treffer einer Suchmaschine. Es gibt keine Vorgabe — wer hier eine
-- Adresse einträgt, entscheidet, dass Firmennamen dorthin gehen.
alter table public.org_settings
  add column if not exists suche_endpoint_url text,
  add column if not exists suche_api_key      text,
  -- Läuft die Anreicherung von selbst, sobald eine Firma oder ein Kontakt
  -- angelegt wird?
  add column if not exists anreicherung_automatisch boolean not null default true,
  -- 'leere_felder': gefundene Werte füllen leere Felder ohne Rückfrage,
  --   abweichende Werte bleiben ein Vorschlag.
  -- 'vorschlag': nichts wird ohne Klick geschrieben.
  add column if not exists anreicherung_uebernahme text not null default 'leere_felder'
    check (anreicherung_uebernahme in ('leere_felder', 'vorschlag'));

-- Jeder Lauf ist ein Datensatz: welche Quellen gelesen wurden, was das
-- Modell daraus vorgeschlagen hat, was davon übernommen wurde. Ohne diese
-- Spur wäre ein angereichertes Feld nicht von einem getippten zu
-- unterscheiden — und genau das muss es sein.
create table public.anreicherungen (
  id          uuid primary key default uuid_generate_v4(),
  org_id      uuid not null references public.orgs(id) on delete cascade,
  entity      text not null check (entity in ('companies', 'contacts')),
  entity_id   uuid not null,
  status      text not null default 'laeuft'
              check (status in ('laeuft', 'vorschlag', 'uebernommen', 'verworfen', 'leer', 'fehler')),
  -- [{url, titel, bytes}] — was gelesen wurde, mit Umfang. Das ist der
  -- gemessene Nachweis, was die Box verlassen hat.
  quellen     jsonb not null default '[]'::jsonb,
  -- {feld: {wert, quelle, belegt, lage}} — lage: 'neu' (Feld war leer)
  -- oder 'abweichend' (Feld hatte einen anderen Wert).
  vorschlag   jsonb not null default '{}'::jsonb,
  -- {feld: wert} — was tatsächlich geschrieben wurde.
  uebernommen jsonb not null default '{}'::jsonb,
  fehler      text,
  modell      text,
  created_by  uuid references public.users(id),
  created_at  timestamptz not null default now(),
  updated_at  timestamptz not null default now()
);

create index anreicherungen_ziel_idx
  on public.anreicherungen (entity, entity_id, created_at desc);

alter table public.anreicherungen enable row level security;
alter table public.anreicherungen force row level security;

create policy anreicherungen_org on public.anreicherungen
  for all using (org_id in (select public.current_user_orgs()))
  with check (org_id in (select public.current_user_orgs()));
