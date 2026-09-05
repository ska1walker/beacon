-- ========================================================================
-- 0007_sitzplaetze.sql
-- Zwei Menschen, ein Olares-Zugang.
--
-- Olares installiert Apps pro Nutzer und kennt an einem Entrance nur die
-- Stufen private, public und internal — es gibt keinen Weg, einen zweiten
-- Nutzer zusätzlich hereinzulassen. Wer zu zweit dasselbe CRM benutzt,
-- teilt also einen Olares-Zugang, und `X-Bfl-User` trägt für beide
-- denselben Namen.
--
-- Deshalb unterscheidet Beacon die Personen selbst. Ein Sitzplatz sagt,
-- wer gerade arbeitet: Besitz, Zuordnung und Protokoll hängen daran.
--
-- **Das ist Zuschreibung, keine Anmeldung.** Wer den geteilten Zugang
-- hat, kann jeden Sitzplatz wählen. Die Grenze, die trägt, ist die
-- Organisation: ein Sitzplatz muss Mitglied derselben Organisation sein
-- wie der angemeldete Olares-Nutzer, sonst greift er nicht. Damit lässt
-- sich über einen Sitzplatz kein fremder Mandant erreichen.
-- ========================================================================

create type public.zugang_art as enum (
  -- Meldet sich selbst über Olares an; der Name kommt aus X-Bfl-User.
  'olares',
  -- Eine Person ohne eigenen Olares-Zugang. Sie existiert, damit ihr
  -- Arbeit zugeschrieben werden kann.
  'sitzplatz'
);

alter table public.users
  add column if not exists zugang public.zugang_art not null default 'olares';

-- Wer unter einem Sitzplatz gehandelt hat, soll nachvollziehbar bleiben:
-- Das Protokoll hält beides fest — die Person und den Zugang, über den
-- sie hereinkam. Ohne die zweite Angabe sähe es aus, als hätte Marc sich
-- selbst angemeldet.
alter table public.audit_log
  add column if not exists actor_login text;

comment on column public.users.zugang is
  'olares = meldet sich selbst an; sitzplatz = Person ohne eigenen Zugang, '
  'gewählt über X-Beacon-Sitzplatz. Ein Sitzplatz ist Zuschreibung, keine Anmeldung.';
