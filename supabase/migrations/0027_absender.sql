-- ========================================================================
-- 0027_absender.sql
-- Jeder Mensch schickt unter seinem eigenen Namen.
--
-- Bisher gab es genau einen Absender je Organisation
-- (`org_settings.smtp_absender`). Sobald zwei Menschen in einem Bestand
-- arbeiten, ist das falsch: Marcs Angebot ging als Kai hinaus, und die
-- Antwort landete bei Kai. Der Empfänger sah einen Namen, mit dem er nie
-- gesprochen hatte.
--
-- Zwei Wege, und beide werden gebraucht, weil die Wahl beim
-- Mailanbieter liegt und nicht bei uns:
--
--   **Eigene Adresse auf dem Konto der Organisation.** Nur `From` wechselt,
--   angemeldet wird weiter mit dem Konto aus den Einstellungen. Das ist
--   ein Feld und funktioniert bei Anbietern, die eine fremde
--   Absenderadresse derselben Domain durchlassen. Manche tun das nicht —
--   one.com etwa weist eine `From`, die nicht dem angemeldeten Postfach
--   entspricht, je nach Tarif zurück.
--
--   **Eigene Zugangsdaten.** Wer sein eigenes Postfach hat, trägt es
--   hier ein und meldet sich damit selbst an. Das geht immer, kostet aber
--   ein Postfach je Person.
--
-- Die Beschränkung auf dieselbe Domain ist kein Formalismus: Ohne sie
-- könnte jedes Mitglied über das Konto der Organisation als beliebige
-- Adresse schreiben — als der Geschäftsführer eines Kunden zum Beispiel.
-- Wer eigene Zugangsdaten hinterlegt, meldet sich selbst an und darf
-- deshalb auch eine fremde Domain führen.
-- ========================================================================

alter table public.users
  -- Was im `From` steht. Leer heißt: der Absender der Organisation.
  add column if not exists absender_email     text,
  add column if not exists absender_name      text,
  -- Optional das eigene Postfach. Nur vollständig ausgefüllt wirksam.
  add column if not exists smtp_host          text,
  add column if not exists smtp_port          integer,
  add column if not exists smtp_benutzer      text,
  add column if not exists smtp_passwort      text,
  add column if not exists smtp_sicherheit    text;

-- `users` steht bewusst außerhalb der Zeilensicherheit für Fachdaten
-- (siehe 0002): Die Tabelle trägt die Identität und muss vor jedem
-- Nutzerkontext lesbar sein. Der Schutz dieser Spalten liegt deshalb im
-- Anwendungscode — `PUT /api/mitglieder/wer/absender` schreibt
-- ausschließlich die Zeile der handelnden Person, nie eine fremde.
