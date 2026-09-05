-- ========================================================================
-- 0019_versand.sql
-- Mails, die das Haus verlassen — mit Buch darüber.
--
-- ## Zwei Wege, bewusst getrennt
--
-- Transaktionale Post (Ticket-Antwort, Bestätigungsmail) geht über das
-- eigene SMTP-Konto: Sie muss aus der Adresse kommen, die der Empfänger
-- kennt, und sie muss auch dann gehen, wenn kein Dienst eingerichtet ist.
-- Marketing-Post geht später über einen Dienst (Brevo) oder dasselbe
-- SMTP — die Wahl steht in `marketing_versand`. HubSpot trennt beides
-- aus demselben Grund: Ein gesperrtes Marketing-Konto darf keine
-- Rechnung aufhalten.
--
-- ## Warum eine Tabelle und kein Aufruf
--
-- Jede Mail ist zuerst eine Zeile und dann ein Versand. Was scheitert,
-- bleibt mit Grund stehen und wird wieder versucht; was geht, trägt die
-- Message-ID, an der eine Antwort später hängt. Ohne die Zeile gäbe es
-- keinen Faden, keinen Beleg und keine Wiederholung.
--
-- Passwort und Schlüssel stehen in der Zeile und gehen nie zurück — das
-- Muster von LLM-Schlüssel und IMAP-Passwort.
-- ========================================================================

alter table public.org_settings
  -- Das SMTP-Konto für transaktionale Post.
  add column if not exists smtp_host            text,
  add column if not exists smtp_port            integer not null default 587,
  add column if not exists smtp_benutzer        text,
  add column if not exists smtp_passwort        text,
  -- 'starttls' (587), 'ssl' (465) oder 'keine' (nur im Haus).
  add column if not exists smtp_sicherheit      text not null default 'starttls',
  add column if not exists smtp_absender        text,
  add column if not exists smtp_absender_name   text,
  add column if not exists smtp_zuletzt         timestamptz,
  add column if not exists smtp_letzter_fehler  text,
  -- Marketing: 'smtp' oder 'brevo'.
  add column if not exists marketing_versand    text not null default 'smtp',
  add column if not exists brevo_api_key        text,
  add column if not exists marketing_absender   text,
  add column if not exists marketing_absender_name text,
  -- Die Adresse des öffentlichen Entrance, unter der Bestätigen, Abmelden
  -- und Klick erreichbar sind. Leer heißt: aus der Box-Domain abgeleitet
  -- (siehe app/versand.py). Ein eigener Wert gewinnt — für einen eigenen
  -- Domainnamen oder eine Box, die ihre Domain nicht mitteilt.
  add column if not exists links_basis_url      text,
  -- Betreff und Text der Bestätigungsmail. Leer heißt: die Vorgabe aus
  -- dem Code. Platzhalter (vorname, bestaetigungslink …) in doppelten
  -- geschweiften Klammern, siehe app/versand.py — hier nicht ausgeschrieben,
  -- weil Helm die Klammern auswerten würde.
  add column if not exists doi_betreff          text,
  add column if not exists doi_text             text;

create type public.mail_art as enum ('transaktional', 'marketing');
create type public.mail_status as enum ('wartend', 'gesendet', 'fehlgeschlagen');

create table public.mails (
  id             uuid primary key default uuid_generate_v4(),
  org_id         uuid not null references public.orgs(id) on delete cascade,
  art            public.mail_art not null,
  status         public.mail_status not null default 'wartend',
  contact_id     uuid references public.contacts(id) on delete set null,
  ticket_id      uuid references public.tickets(id) on delete set null,
  an             text not null,
  betreff        text not null,
  text           text not null,
  -- Der Faden: unsere Message-ID, und worauf wir geantwortet haben.
  message_id     text,
  in_reply_to    text,
  referenzen     text,
  versuche       integer not null default 0,
  naechster_versuch timestamptz,
  fehler         text,
  gesendet_am    timestamptz,
  payload        jsonb not null default '{}'::jsonb,
  created_by     uuid references public.users(id),
  created_at     timestamptz not null default now()
);

create index if not exists mails_wartend_idx
  on public.mails (org_id, naechster_versuch) where status = 'wartend';
create index if not exists mails_contact_idx on public.mails (contact_id, created_at desc);
create index if not exists mails_ticket_idx on public.mails (ticket_id, created_at desc);

alter table public.mails enable row level security;
alter table public.mails force row level security;

create policy mails_org on public.mails
  for all using (org_id in (select public.current_user_orgs()))
  with check (org_id in (select public.current_user_orgs()));
