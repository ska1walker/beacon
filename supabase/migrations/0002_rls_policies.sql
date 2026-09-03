-- ========================================================================
-- 0002_rls_policies.sql
-- Row Level Security auf jeder org-gebundenen Tabelle.
--
-- Es gibt kein Supabase-Auth. Das Backend setzt beim Öffnen jeder
-- Verbindung
--   SET LOCAL app.current_user_id = '<uuid>';
-- aus dem X-Bfl-User-Header. Die Policies lesen genau diesen Wert. Wer
-- die Variable nicht setzt, sieht nichts — das ist Absicht.
-- ========================================================================

create or replace function public.current_user_id()
returns uuid
language sql
stable
as $$
  select nullif(current_setting('app.current_user_id', true), '')::uuid;
$$;

create or replace function public.current_user_orgs()
returns setof uuid
language sql
stable
as $$
  select org_id from public.user_org_roles
  where user_id = public.current_user_id();
$$;

create or replace function public.current_user_role_in_org(target_org uuid)
returns public.user_role
language sql
stable
as $$
  select role from public.user_org_roles
  where user_id = public.current_user_id() and org_id = target_org;
$$;

-- ========================================================================
-- Aktivieren
-- ========================================================================

alter table public.orgs            enable row level security;
alter table public.users           enable row level security;
alter table public.user_org_roles  enable row level security;
alter table public.companies       enable row level security;
alter table public.contacts        enable row level security;
alter table public.pipelines       enable row level security;
alter table public.pipeline_stages enable row level security;
alter table public.deals           enable row level security;
alter table public.deal_contacts   enable row level security;
alter table public.activities      enable row level security;
alter table public.tasks           enable row level security;
alter table public.org_settings    enable row level security;
alter table public.audit_log       enable row level security;

-- ========================================================================
-- Identität
-- ========================================================================

create policy users_self on public.users
  for select using (id = public.current_user_id());

create policy users_self_update on public.users
  for update using (id = public.current_user_id());

create policy orgs_member on public.orgs
  for select using (id in (select public.current_user_orgs()));

create policy orgs_admin_write on public.orgs
  for update using (public.current_user_role_in_org(id) in ('owner', 'admin'));

create policy roles_own on public.user_org_roles
  for select using (org_id in (select public.current_user_orgs()));

-- ========================================================================
-- Fachdaten — überall dasselbe Muster: sichtbar und schreibbar innerhalb
-- der eigenen Organisation. Die Feinsteuerung (wem gehört ein Deal) ist
-- Sache der Anwendung, nicht der Zeilensicherheit: ein Zwei-Mann-Vertrieb
-- teilt sich alles, und eine Sichtbarkeitsregel je Besitzer würde nur
-- Fehler erzeugen, die niemand versteht.
-- ========================================================================

create policy companies_org on public.companies
  for all using (org_id in (select public.current_user_orgs()))
  with check (org_id in (select public.current_user_orgs()));

create policy contacts_org on public.contacts
  for all using (org_id in (select public.current_user_orgs()))
  with check (org_id in (select public.current_user_orgs()));

create policy pipelines_org on public.pipelines
  for all using (org_id in (select public.current_user_orgs()))
  with check (org_id in (select public.current_user_orgs()));

create policy pipeline_stages_org on public.pipeline_stages
  for all using (org_id in (select public.current_user_orgs()))
  with check (org_id in (select public.current_user_orgs()));

create policy deals_org on public.deals
  for all using (org_id in (select public.current_user_orgs()))
  with check (org_id in (select public.current_user_orgs()));

create policy activities_org on public.activities
  for all using (org_id in (select public.current_user_orgs()))
  with check (org_id in (select public.current_user_orgs()));

create policy tasks_org on public.tasks
  for all using (org_id in (select public.current_user_orgs()))
  with check (org_id in (select public.current_user_orgs()));

create policy org_settings_org on public.org_settings
  for all using (org_id in (select public.current_user_orgs()))
  with check (org_id in (select public.current_user_orgs()));

-- deal_contacts trägt keine org_id — sie hängt am Deal. Die Prüfung geht
-- deshalb über den Deal, nicht über eine zweite Spalte, die auseinander-
-- laufen könnte.
create policy deal_contacts_org on public.deal_contacts
  for all using (
    exists (
      select 1 from public.deals d
      where d.id = deal_id and d.org_id in (select public.current_user_orgs())
    )
  )
  with check (
    exists (
      select 1 from public.deals d
      where d.id = deal_id and d.org_id in (select public.current_user_orgs())
    )
  );

-- Das Protokoll wird gelesen und angehängt, nie geändert oder gelöscht:
-- dafür gibt es bewusst keine Policy.
create policy audit_log_read on public.audit_log
  for select using (org_id in (select public.current_user_orgs()));

create policy audit_log_append on public.audit_log
  for insert with check (org_id in (select public.current_user_orgs()));

-- ========================================================================
-- FORCE — der Teil, ohne den alles darüber wirkungslos wäre
--
-- Postgres nimmt den Eigentümer einer Tabelle von der Zeilensicherheit
-- aus. Das Backend verbindet sich auf der Box mit den Zugangsdaten, die
-- Olares injiziert, und die gehören sehr wahrscheinlich genau diesem
-- Eigentümer: Ohne FORCE liefen alle Policies oben ins Leere, und zwar
-- lautlos — kein Fehler, nur plötzlich alle Zeilen aller Mandanten.
--
-- Die Identitätstabellen bleiben ausgenommen. Beim ersten Request einer
-- neuen Kennung gibt es den Nutzerkontext noch nicht, den die Policies
-- lesen würden; das Anlegen von Nutzer, Organisation und Rolle muss ohne
-- ihn möglich sein. Danach setzt das Backend den Kontext, und alles
-- Fachliche unterliegt ihm.
--
-- Ein Superuser umgeht auch FORCE. Die Datenbankrolle der Anwendung darf
-- deshalb keiner sein — siehe docs/BETRIEB.md.
-- ========================================================================

alter table public.companies       force row level security;
alter table public.contacts        force row level security;
alter table public.pipelines       force row level security;
alter table public.pipeline_stages force row level security;
alter table public.deals           force row level security;
alter table public.deal_contacts   force row level security;
alter table public.activities      force row level security;
alter table public.tasks           force row level security;
alter table public.org_settings    force row level security;
alter table public.audit_log       force row level security;
