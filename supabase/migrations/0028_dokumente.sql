-- ========================================================================
-- 0028_dokumente.sql
-- Dateien am Datensatz — Angebot als PDF, Lageplan, unterschriebener
-- Vertrag, das Foto vom Zählerstand.
--
-- Bisher konnte ein Mensch alles in Beacon schreiben, aber nichts
-- hineinlegen. Wer einem Kontakt ein Dokument zuordnen wollte, hängte es
-- an eine Mail und hoffte, dass der Faden es festhält.
--
-- **Die Datei liegt nicht in der Datenbank.** Sie steht unter
-- `/app/data/dokumente/<org>/<id><endung>` — demselben Pfad wie die
-- Podcast-Folgen, und dem einzigen, den Olares als dauerhaft zusichert.
-- Eine Deinstallation nimmt die Datenbank mit, nicht diesen Ordner; die
-- Zeile hier kommt über den Abzug zurück und findet ihre Datei wieder,
-- weil der Pfad mitgespeichert ist.
--
-- Warum nicht als `bytea` in der Datenbank: Ein Abzug wäre dann nicht
-- mehr 130 Kilobyte, sondern Hunderte Megabyte, jede Stunde neu, und
-- eine Zeile ließe sich nicht mehr streamen — der ganze Inhalt müsste
-- durch den Arbeitsspeicher.
--
-- `pruefsumme` ist nicht Zierde: Sie sagt, ob die Datei auf der Platte
-- noch die ist, die einmal hochgeladen wurde, und erkennt dasselbe
-- Dokument, das jemand zweimal ablegt.
-- ========================================================================

create table if not exists public.dokumente (
  id            uuid primary key default uuid_generate_v4(),
  org_id        uuid not null references public.orgs(id) on delete cascade,

  -- Woran es hängt. Genau eines, wie bei `activities` — ein Dokument
  -- gehört an eine Stelle, sonst weiß niemand, wo es zu suchen ist.
  company_id    uuid references public.companies(id) on delete cascade,
  contact_id    uuid references public.contacts(id) on delete cascade,
  deal_id       uuid references public.deals(id) on delete cascade,
  ticket_id     uuid references public.tickets(id) on delete cascade,

  -- Der Name, den der Mensch kennt. Der Pfad auf der Platte trägt ihn
  -- **nicht**: Ein Dateiname aus dem Internet gehört nie in einen Pfad.
  name          text not null,
  pfad          text not null,
  groesse       bigint not null,
  typ           text,
  pruefsumme    text,
  notiz         text,

  hochgeladen_von uuid references public.users(id),
  created_at    timestamptz not null default now(),
  deleted_at    timestamptz,

  constraint dokumente_hat_bezug check (
    company_id is not null or contact_id is not null
    or deal_id is not null or ticket_id is not null
  )
);

create index if not exists dokumente_company_idx on public.dokumente (company_id, created_at desc);
create index if not exists dokumente_contact_idx on public.dokumente (contact_id, created_at desc);
create index if not exists dokumente_deal_idx    on public.dokumente (deal_id, created_at desc);
create index if not exists dokumente_ticket_idx  on public.dokumente (ticket_id, created_at desc);
create index if not exists dokumente_org_idx     on public.dokumente (org_id, created_at desc);

alter table public.dokumente enable row level security;
alter table public.dokumente force row level security;

create policy dokumente_org on public.dokumente
  for all using (org_id in (select public.current_user_orgs()))
  with check (org_id in (select public.current_user_orgs()));
