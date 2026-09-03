-- ========================================================================
-- 0005_qualifizierung.sql
-- Qualifizierung eines Geschäfts und geordnete Verlustgründe.
--
-- Bis hierher stand am Deal ein Betrag und eine Stufe. Warum er dort
-- steht, stand nirgends — und warum ein verlorener verloren ging, stand
-- als Freitext da und war damit nicht auswertbar. Beides ist die Grundlage
-- jeder Prognose, die mehr sein soll als eine Summe.
-- ========================================================================

-- ========================================================================
-- VERLUSTGRÜNDE
--
-- Als Datensatz, nicht als Aufzählungstyp: Der Vertrieb lernt neue Gründe
-- kennen, und eine Migration je Erkenntnis wäre der falsche Preis. Der
-- Freitext am Deal bleibt daneben bestehen — der Grund ist die Kategorie,
-- die Geschichte steht im Text.
-- ========================================================================

create table public.loss_reasons (
  id          uuid primary key default uuid_generate_v4(),
  org_id      uuid not null references public.orgs(id) on delete cascade,
  name        text not null,
  position    integer not null default 0,
  is_active   boolean not null default true,
  created_at  timestamptz not null default now()
);

create unique index loss_reasons_org_name_uniq on public.loss_reasons (org_id, name);
create index loss_reasons_org_idx on public.loss_reasons (org_id, position) where is_active;

alter table public.deals
  add column if not exists lost_reason_id uuid references public.loss_reasons(id) on delete set null;

create index deals_lost_reason_idx on public.deals (lost_reason_id) where deleted_at is null;

-- ========================================================================
-- QUALIFIZIERUNG
--
-- Sechs Felder, nicht sechzig. Was ein Zwei-Mann-Vertrieb tatsächlich
-- unterscheidet: Wofür, warum jetzt, wer entscheidet, ist Geld da, bis
-- wann, und passt die Hardware ins Haus. Der letzte Punkt ist bei einem
-- Gerät im Serverraum kein Detail, sondern der häufigste späte Stolperstein.
-- ========================================================================

alter table public.deals
  add column if not exists bedarf              text,
  add column if not exists ausloeser           text,
  add column if not exists entscheider         text,
  add column if not exists budget_geklaert     boolean not null default false,
  add column if not exists zeitrahmen          text,
  add column if not exists standort_geklaert   boolean not null default false,
  -- 0 bis 100. Errechnet aus den Feldern oben, nicht frei gesetzt: Eine
  -- Zahl, die jemand von Hand vergibt, sagt über den Vergebenden mehr aus
  -- als über das Geschäft.
  add column if not exists qualifikation_punkte smallint,
  add column if not exists qualifikation_am    timestamptz;

-- ========================================================================
-- Zeilensicherheit
-- ========================================================================

alter table public.loss_reasons enable row level security;
alter table public.loss_reasons force row level security;

create policy loss_reasons_org on public.loss_reasons
  for all using (org_id in (select public.current_user_orgs()))
  with check (org_id in (select public.current_user_orgs()));
