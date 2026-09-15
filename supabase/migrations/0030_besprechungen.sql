-- ========================================================================
-- 0030_besprechungen.sql
-- Besprechungen aus Insilo als eigener Bereich — nicht mehr im Eingang.
--
-- Der Eingang ist eine Warteschlange, die leer werden soll. Besprechungen
-- sind ein Archiv, das man durchsucht und nach Datum liest; im Eingang
-- verschwand ein Gespräch nach dem Zuordnen, und wer eines suchte, fand es
-- nur noch in der Zeitleiste irgendeines Kunden. Zuordnung ist hier eine
-- Eigenschaft der Besprechung, kein Zustand einer Warteschlange.
--
-- Zwei Entscheidungen (Kai und Marc, 15.9.2026):
--
-- * **Protokoll ja, Wortlaut nein.** `protokoll` ist Insilos Markdown ohne
--   den Abschnitt „## Volltranskript". Der Wortlaut bleibt in Insilo; die
--   Oberfläche verlinkt dorthin. Die rohe Nutzlast wird deshalb nicht
--   abgelegt — sie enthielte ihn.
-- * **Nie automatisch zugeordnet.** `vorschlag` ist ein Vorschlag, bis ein
--   Mensch bestätigt. Zwei Kontakte heißen Meyer.
-- ========================================================================

create type public.besprechung_status as enum ('offen', 'zugeordnet', 'verworfen');

create table if not exists public.besprechungen (
  id               uuid primary key default uuid_generate_v4(),
  org_id           uuid not null references public.orgs(id) on delete cascade,
  source_id        uuid references public.webhook_sources(id) on delete set null,
  -- Die Kennung der Besprechung bei Insilo; über sie laufen Wiederholungen,
  -- neu erzeugte Zusammenfassungen und das Löschen.
  external_id      text not null,
  titel            text,
  recorded_at      timestamptz,
  dauer_sek        integer,
  vorlage          text,
  schlagworte      text[] not null default '{}',
  sprecher         text[] not null default '{}',
  beteiligte       text[] not null default '{}',
  zusammenfassung  jsonb not null default '{}'::jsonb,
  protokoll        text,
  status           public.besprechung_status not null default 'offen',
  company_id       uuid references public.companies(id) on delete set null,
  deal_id          uuid references public.deals(id) on delete set null,
  activity_id      uuid references public.activities(id) on delete set null,
  -- {company_id, contact_ids, deal_id, grund, quelle: 'namen'|'modell',
  --  kandidaten: [...], mehrdeutig: bool}
  vorschlag        jsonb,
  created_at       timestamptz not null default now(),
  updated_at       timestamptz not null default now(),
  deleted_at       timestamptz
);

create unique index if not exists besprechungen_extern_uniq
  on public.besprechungen (org_id, external_id);
create index if not exists besprechungen_datum_idx
  on public.besprechungen (org_id, recorded_at desc) where deleted_at is null;
create index if not exists besprechungen_status_idx
  on public.besprechungen (org_id, status) where deleted_at is null;
-- Volltext über einen Ausdruck, keine erzeugte Spalte: Die Sicherung
-- spielt Zeilen spaltenweise zurück, und in eine erzeugte Spalte lässt
-- sich nichts schreiben.
create index if not exists besprechungen_suche_idx
  on public.besprechungen
  using gin (to_tsvector('german', coalesce(titel, '') || ' ' || coalesce(protokoll, '')));

-- Ein Gespräch hat oft mehrere Beteiligte beim Kunden. Die Aktivität trägt
-- nur einen Kontakt; hierüber steht die Besprechung an allen.
create table if not exists public.besprechung_kontakte (
  besprechung_id  uuid not null references public.besprechungen(id) on delete cascade,
  contact_id      uuid not null references public.contacts(id) on delete cascade,
  org_id          uuid not null references public.orgs(id) on delete cascade,
  primary key (besprechung_id, contact_id)
);

create index if not exists besprechung_kontakte_kontakt_idx
  on public.besprechung_kontakte (contact_id);

-- Wohin „In Insilo öffnen" führt. Insilos Nutzlast trägt keine Adresse.
alter table public.webhook_sources
  add column if not exists oberflaeche_url text;

alter table public.besprechungen enable row level security;
alter table public.besprechungen force row level security;
alter table public.besprechung_kontakte enable row level security;
alter table public.besprechung_kontakte force row level security;

create policy besprechungen_org on public.besprechungen
  for all using (org_id in (select public.current_user_orgs()))
  with check (org_id in (select public.current_user_orgs()));

create policy besprechung_kontakte_org on public.besprechung_kontakte
  for all using (org_id in (select public.current_user_orgs()))
  with check (org_id in (select public.current_user_orgs()));

-- ── Umzug aus dem Eingang ──────────────────────────────────────────────
-- Was bisher als Insilo-Posten im Eingang lag, wird zur Besprechung.
--
-- Die Migration läuft zwar als Eigentümerin der Tabellen, aber FORCE aus
-- 0002 gilt auch für sie: Ohne Nutzerkontext sähe das `select` keine
-- einzige Zeile, und der Umzug täte still nichts. Deshalb wird die
-- Zeilensicherheit für diese vier Tabellen kurz abgeschaltet — dasselbe
-- Vorgehen wie `tresor.nachziehen`. Jede Zeile behält ihre Organisation.
alter table public.eingang disable row level security;
alter table public.webhook_sources disable row level security;
alter table public.activities disable row level security;
alter table public.besprechungen disable row level security;
insert into public.besprechungen
  (org_id, source_id, external_id, titel, recorded_at, dauer_sek, vorlage,
   protokoll, status, company_id, deal_id, activity_id, created_at)
select distinct on (e.org_id, e.external_id)
  e.org_id, e.source_id, e.external_id, e.titel,
  coalesce((e.payload -> 'meeting' ->> 'recorded_at')::timestamptz, e.occurred_at),
  nullif(e.payload -> 'meeting' ->> 'duration_sec', '')::integer,
  e.payload -> 'meeting' ->> 'template_name',
  split_part(coalesce(e.markdown, ''), E'\n## Volltranskript', 1),
  case when e.activity_id is not null then 'zugeordnet'::public.besprechung_status
       else 'offen'::public.besprechung_status end,
  e.company_id, e.deal_id, e.activity_id, e.created_at
from public.eingang e
join public.webhook_sources s on s.id = e.source_id
where s.kind = 'insilo' and e.event = 'meeting.ready' and e.external_id is not null
order by e.org_id, e.external_id, e.created_at desc
on conflict (org_id, external_id) do nothing;

-- Der Wortlaut kommt auch aus den Aktivitäten, die schon angelegt waren —
-- dieselbe Regel für alles, was Beacon von Insilo hat.
update public.activities a
   set body = split_part(a.body, E'\n## Volltranskript', 1),
       payload = coalesce(a.payload, '{}'::jsonb) || jsonb_build_object('besprechung_id', b.id)
  from public.besprechungen b
 where b.activity_id = a.id;

delete from public.eingang e
 using public.webhook_sources s
 where s.id = e.source_id and s.kind = 'insilo'
   and (e.event like 'meeting.%' or e.event = 'test.ping');

alter table public.eingang enable row level security;
alter table public.eingang force row level security;
alter table public.webhook_sources enable row level security;
alter table public.webhook_sources force row level security;
alter table public.activities enable row level security;
alter table public.activities force row level security;
alter table public.besprechungen enable row level security;
alter table public.besprechungen force row level security;
