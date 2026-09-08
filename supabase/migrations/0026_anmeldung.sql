-- ========================================================================
-- 0026_anmeldung.sql
-- Eine eigene Anmeldung — weil Olares' Konten das nicht leisten können.
--
-- Bisher liefert der Envoy-Sidecar die Identität im Kopf `X-Bfl-User`,
-- und Beacon glaubt ihm. Das trägt genau so weit, wie der Entrance
-- `internal` ist: Vor dem Pod steht Authelia, ungeprüft kommt niemand
-- herein. Soll das CRM aber von außen von einem **Team** genutzt werden,
-- endet dieser Weg. Eine Olares-App wird je Nutzer installiert
-- (Namensraum `beacon-<nutzer>`); ein zweites Olares-Konto bekäme ein
-- eigenes, leeres Beacon mit eigener Datenbank. Der einzige geteilte
-- Modus, die *shared app*, hat laut Olares ausdrücklich keinen Entrance
-- und keine URL. Für mehrere Menschen in **einem** Bestand führt kein
-- Weg an einer eigenen Anmeldung vorbei.
--
-- Vier Tabellen, jede mit einem Grund:
--
--   `users` bekommt den Passwort-Hash. Nur den Hash — argon2id, nie das
--   Passwort, und `totp_geheimnis` steht schon bereit, damit der zweite
--   Faktor später keine Migration mehr braucht.
--
--   `sitzungen` hält, wer gerade angemeldet ist. Gespeichert wird **nur
--   der SHA-256 des Tokens**: Wer die Datenbank liest, kann sich damit
--   nicht anmelden. Serverseitig, damit ein Abmelden wirklich abmeldet —
--   ein selbstsigniertes Token im Keks wäre bis zum Ablauf gültig, auch
--   nach dem Klick auf „Abmelden".
--
--   `einladungen` ist der einzige Weg, wie ein Mensch dazukommt. Es gibt
--   keine Registrierung: Wer nicht eingeladen wurde, hat kein Konto.
--
--   `anmeldeversuche` ist die Bremse. Ohne sie probiert ein Skript
--   Passwörter, so schnell die Leitung trägt.
-- ========================================================================

alter table public.users
  add column if not exists passwort_hash   text,
  add column if not exists passwort_am     timestamptz,
  add column if not exists totp_geheimnis  text,
  add column if not exists gesperrt_bis    timestamptz;

create table if not exists public.sitzungen (
  id          uuid primary key default uuid_generate_v4(),
  -- Der SHA-256 des Tokens, nie das Token selbst.
  token_hash  text not null unique,
  user_id     uuid not null references public.users(id) on delete cascade,
  org_id      uuid not null references public.orgs(id) on delete cascade,
  erstellt_am timestamptz not null default now(),
  zuletzt_am  timestamptz not null default now(),
  laeuft_ab   timestamptz not null,
  agent       text,
  beendet_am  timestamptz
);

create index if not exists sitzungen_user_idx on public.sitzungen (user_id, erstellt_am desc);
-- Nach dem Ablauf ist eine Zeile nur noch Ballast; die Schleife räumt sie weg.
create index if not exists sitzungen_ablauf_idx on public.sitzungen (laeuft_ab);

create table if not exists public.einladungen (
  id           uuid primary key default uuid_generate_v4(),
  token_hash   text not null unique,
  user_id      uuid not null references public.users(id) on delete cascade,
  org_id       uuid not null references public.orgs(id) on delete cascade,
  erstellt_von uuid references public.users(id),
  erstellt_am  timestamptz not null default now(),
  laeuft_ab    timestamptz not null,
  benutzt_am   timestamptz
);

create index if not exists einladungen_org_idx on public.einladungen (org_id, erstellt_am desc);

-- Die Bremse. Bewusst ohne Bezug zur Organisation: Sie zählt Versuche zu
-- Kennungen, die es vielleicht gar nicht gibt, und muss gelesen werden
-- können, **bevor** jemand angemeldet ist.
create table if not exists public.anmeldeversuche (
  id       bigserial primary key,
  kennung  text not null,
  am       timestamptz not null default now()
);

create index if not exists anmeldeversuche_idx on public.anmeldeversuche (kennung, am desc);

alter table public.sitzungen enable row level security;
alter table public.sitzungen force row level security;
alter table public.einladungen enable row level security;
alter table public.einladungen force row level security;

-- Die Anmeldung läuft, bevor es einen Nutzerkontext gibt: Wer sich
-- anmeldet, ist noch niemand. Eine Policy über `current_user_id()` würde
-- dort alles abweisen. Deshalb dasselbe Muster wie beim öffentlichen Link
-- (0018): Die Verbindung **nennt den Hash**, um den es geht, und bekommt
-- genau diese eine Zeile frei. Ein vergessener Filter im Anwendungscode
-- kann damit trotzdem keine fremde Sitzung sehen.
create policy sitzungen_selbst on public.sitzungen
  for all using (user_id = public.current_user_id())
  with check (user_id = public.current_user_id());

create policy sitzungen_token on public.sitzungen
  for all
  using (token_hash = nullif(current_setting('app.anmelde_token', true), ''))
  with check (token_hash = nullif(current_setting('app.anmelde_token', true), ''));

-- Die Aufräumschleife hat weder Nutzer noch Token. Sie darf genau das
-- löschen, was sie ohnehin löschen wollte — die Policy ist ihr Prädikat.
create policy sitzungen_verfallen on public.sitzungen
  for delete using (laeuft_ab < now() - interval '7 days');

-- Postgres wendet auf ein DELETE mit WHERE-Bedingung zusätzlich die
-- SELECT-Policies an. Ohne diese Zeile fände die Schleife die Zeile gar
-- nicht erst und löschte still nichts. Sichtbar wird nur, was seit über
-- einer Woche keinen Zugang mehr gibt.
create policy sitzungen_verfallen_sehen on public.sitzungen
  for select using (laeuft_ab < now() - interval '7 days');

create policy einladungen_org on public.einladungen
  for all using (org_id in (select public.current_user_orgs()))
  with check (org_id in (select public.current_user_orgs()));

-- Wer den Link hat, ist noch nicht angemeldet — sonst bräuchte er ihn nicht.
create policy einladungen_token on public.einladungen
  for all
  using (token_hash = nullif(current_setting('app.anmelde_token', true), ''))
  with check (token_hash = nullif(current_setting('app.anmelde_token', true), ''));

-- `anmeldeversuche` bleibt ohne Zeilensicherheit: Die Tabelle enthält
-- keine Geschäftsdaten, wird nur ohne Nutzerkontext beschrieben und
-- gelesen, und eine Policy über `current_user_id()` wäre dort wirkungslos.
