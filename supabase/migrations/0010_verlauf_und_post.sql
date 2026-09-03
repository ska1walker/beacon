-- ========================================================================
-- 0010_verlauf_und_post.sql
-- Verlaufseinträge lassen sich zurücknehmen; ein Postausgang bekommt Adresse.
-- ========================================================================

-- Eine Notiz, die falsch am Kunden hängt, muss weg können — weich, wie
-- alles andere. Systemeinträge (Stufenwechsel, KI) bleiben unantastbar.
alter table public.activities
  add column if not exists deleted_at timestamptz,
  add column if not exists updated_at timestamptz;

-- Der Postausgang. Marcs Relay (oder jeder andere Dienst) bekommt einen
-- signierten POST je Nachricht; die Adresse steht hier, nie im Code.
alter table public.org_settings
  add column if not exists mail_endpoint_url    text,
  add column if not exists mail_endpoint_secret text,
  add column if not exists mail_absender        text;
