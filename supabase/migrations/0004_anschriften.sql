-- ========================================================================
-- 0004_anschriften.sql
-- Postanschrift der Firma und Absenderangaben der eigenen Organisation.
--
-- Beides fehlte, und beides braucht das Angebot: Ein Dokument ohne
-- Empfängeranschrift und ohne Absender ist kein Angebot, sondern eine
-- Preisliste. Die Pflichtangaben (Umsatzsteuer-Nummer, Vertretung) hängen
-- an der Organisation, nicht am Code — sie unterscheiden sich je Betreiber.
-- ========================================================================

alter table public.companies
  add column if not exists street       text,
  add column if not exists postal_code  text;

alter table public.org_settings
  add column if not exists absender_name         text,
  add column if not exists absender_strasse      text,
  add column if not exists absender_plz          text,
  add column if not exists absender_ort          text,
  add column if not exists absender_land         text default 'Deutschland',
  add column if not exists absender_email        text,
  add column if not exists absender_telefon      text,
  add column if not exists absender_website      text,
  add column if not exists ust_id                text,
  add column if not exists vertretung            text,
  add column if not exists registergericht       text,
  add column if not exists bank_iban             text,
  add column if not exists bank_name             text,
  -- Steht unter jedem Angebot. Eine Vorgabe wäre eine Rechtsauskunft, die
  -- wir nicht geben — der Betreiber trägt seine eigenen Bedingungen ein.
  add column if not exists standard_bedingungen  text,
  -- Wie lange ein Angebot vorgabemäßig bindet. 30 Tage sind üblich,
  -- verbindlich ist, was im einzelnen Angebot steht.
  add column if not exists bindefrist_tage       integer default 30;
