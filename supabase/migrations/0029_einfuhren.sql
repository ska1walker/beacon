-- ========================================================================
-- 0029_einfuhren.sql
-- Was eine CSV-Einfuhr getan hat — und vor allem, was sie **nicht** getan
-- hat.
--
-- Für jeden angelegten Datensatz gibt es einen Eintrag im `audit_log`.
-- Übersprungene Zeilen haben aber keinen Datensatz, also auch keinen
-- Eintrag. Genau nach ihnen wird gefragt: „Ich habe 1.200 Kontakte
-- hochgeladen, warum sind es 1.166 geworden?" Nur diese Tabelle kann das
-- beantworten.
--
-- `details` ist mit Absicht gedeckelt (die Anwendung schreibt höchstens
-- 500 Einträge). Eine Datei mit zwanzigtausend Dubletten erzeugte sonst
-- eine Zeile von zwei Megabyte, die in jedem Abzug mitreist. Die volle
-- Zählung steht in `gruende`, die Beispiele in `details`.
--
-- `zuordnung` hält fest, welche Dateispalte auf welches Feld gelegt wurde.
-- Ohne sie ließe sich ein Import mit falscher Zuordnung später nicht mehr
-- erklären — die Datei selbst bewahrt Beacon nicht auf.
-- ========================================================================

create table if not exists public.einfuhren (
  id              uuid primary key default uuid_generate_v4(),
  org_id          uuid not null references public.orgs(id) on delete cascade,

  entity          text not null check (entity in ('contacts', 'companies')),
  dateiname       text not null,
  -- Womit gelesen wurde. Steht auch in der Vorschau: Ein Umlautfehler
  -- ohne Absender ist schwer zu finden.
  kodierung       text not null,
  trenner         text not null,

  zeilen          integer not null default 0,
  angelegt        integer not null default 0,
  -- Bei einer Kontaktdatei: die Firmen, die nebenbei entstanden sind.
  firmen_angelegt integer not null default 0,
  uebersprungen   integer not null default 0,

  gruende         jsonb not null default '{}'::jsonb,
  details         jsonb not null default '[]'::jsonb,
  zuordnung       jsonb not null default '[]'::jsonb,

  status          text not null default 'fertig' check (status in ('fertig', 'fehlgeschlagen')),
  fehler          text,

  created_by      uuid references public.users(id),
  created_at      timestamptz not null default now()
);

create index if not exists einfuhren_org_idx on public.einfuhren (org_id, created_at desc);

alter table public.einfuhren enable row level security;
alter table public.einfuhren force row level security;

create policy einfuhren_org on public.einfuhren
  for all using (org_id in (select public.current_user_orgs()))
  with check (org_id in (select public.current_user_orgs()));
