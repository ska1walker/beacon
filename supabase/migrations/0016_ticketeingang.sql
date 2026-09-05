-- ========================================================================
-- 0016_ticketeingang.sql
-- Tickets, die von einer Maschine kommen — API, Bot, Formular.
--
-- ## Ein Eingang, viele Kanäle
--
-- Die naheliegende Lösung wäre je Kanal ein eigener Weg, ein Ticket
-- anzulegen. Sie ist falsch: Dublettenerkennung, Spam, der Start der
-- SLA-Uhr und die Frage, wer der Absender ist, sind in jedem Kanal
-- **dasselbe** Problem. Einmal gelöst ist es ein Feature; viermal gelöst
-- sind es vier halbe. Also läuft alles über den signierten Pfad, den
-- 0006 für Insilo gebaut hat, und unterscheidet sich nur in der Quelle.
--
-- ## Warum der Absender doppelt gespeichert wird
--
-- `contact_id` zeigt auf den Kontakt, wenn die E-Mail einen trifft.
-- Trifft sie keinen, bleibt sie trotzdem am Ticket stehen — sonst käme
-- eine Anfrage herein, auf die niemand antworten kann, weil die Adresse
-- nur im Ereignis-JSON steht. Ein Ticket ohne Rückweg ist kein Ticket,
-- sondern eine Notiz.
--
-- ## Warum eine Quelle entscheidet, ob sie durchregieren darf
--
-- Eine Quelle mit Geheimnis ist vertrauenswürdig: Wer signieren kann,
-- darf ein Ticket anlegen. Ein öffentliches Formular kann kein Geheimnis
-- halten — was von dort kommt, wartet im Eingang, bis ein Mensch es
-- ansieht. `tickets_direkt` ist genau diese Unterscheidung, und sie
-- gehört an die Quelle, nicht in den Code.
-- ========================================================================

alter type public.ticket_quelle add value if not exists 'api';
alter type public.ticket_quelle add value if not exists 'bot';

alter table public.tickets
  add column if not exists absender_email text,
  add column if not exists absender_name  text;

-- Für die Zuordnung eingehender Anfragen zu einem vorhandenen Kontakt.
create index if not exists tickets_absender_idx
  on public.tickets (org_id, lower(absender_email))
  where absender_email is not null and deleted_at is null;

alter table public.webhook_sources
  add column if not exists tickets_direkt boolean not null default true;

-- Welches Ticket aus einem Eingangsposten entstanden ist. Ohne diese
-- Spur wäre nach dem Anlegen nicht mehr nachvollziehbar, woher ein
-- Ticket kam — und genau das ist die Frage, die man bei einer
-- Falschmeldung als Erstes stellt.
alter table public.eingang
  add column if not exists ticket_id uuid references public.tickets(id) on delete set null;

create index if not exists eingang_ticket_idx on public.eingang (ticket_id)
  where ticket_id is not null;
