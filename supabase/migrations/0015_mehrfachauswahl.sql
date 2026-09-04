-- ========================================================================
-- 0015_mehrfachauswahl.sql
-- Eine eigene Eigenschaft, die mehrere Werte gleichzeitig trägt —
-- und eine Optionsliste, die sich umbenennen lässt.
--
-- ## Warum eine Liste, kein getrennter Text
--
-- Bisher hielt `select` genau einen Wert. Das reicht für „Region", aber
-- nicht für die Fragen, die im Vertrieb tatsächlich gestellt werden:
-- welche Produkte interessieren, welche Zertifikate liegen vor, an
-- welchen Messen war die Firma. Solche Angaben sind Mengen, und wer sie
-- in ein Textfeld presst („ISO 9001, TISAX"), kann danach nicht mehr
-- filtern, ohne über Kommas zu raten.
--
-- **Der Wert ist eine JSON-Liste.** HubSpots API reiht Mehrfachwerte mit
-- Semikolon aneinander (`a;b;c`) und hat sich damit ein Jahrzehnt Ärger
-- eingehandelt: Ein Text „123;456" wurde beim Speichern in zwei Werte
-- zerlegt, egal ob das Feld mehrwertig war. HubSpot hat das 2024 einzeln
-- nachgebessert; ein Fluchtzeichen für ein Semikolon *im* Wert gibt es
-- bis heute nicht. Eine jsonb-Liste hat das Problem nicht.
--
-- ## Warum die Option zwei Namen hat
--
-- Eine Option war bisher ein Text, der zugleich Anzeige und Speicherwert
-- war. Das macht jede Umbenennung zum Datenverlust: „Nord" in
-- „Region Nord" zu ändern, hieße, jeden Datensatz mit „Nord" zu
-- entwerten. Deshalb trägt eine Option ab hier zwei Felder — `wert`
-- steht fest, `text` ist frei änderbar — und `verborgen` nimmt sie aus
-- der Auswahl, ohne sie aus den Datensätzen zu nehmen.
--
-- Die Umstellung läuft hier mit: Aus "Nord" wird
-- {"wert":"Nord","text":"Nord","verborgen":false}. Der Wert bleibt also,
-- was er war, und alle vorhandenen Datensätze passen weiter.
--
-- Der GIN-Index bedient `?|` und `?&`, mit denen die Listenfilter
-- arbeiten. Ohne ihn wird jede Frage nach „hat eines von" ein
-- vollständiger Durchlauf.
-- ========================================================================

alter type public.property_kind add value if not exists 'multiselect';

create index if not exists companies_custom_gin on public.companies using gin (custom);
create index if not exists contacts_custom_gin  on public.contacts  using gin (custom);
create index if not exists deals_custom_gin     on public.deals     using gin (custom);

-- Alte Optionslisten in die neue Form bringen. Der EXISTS-Vorbehalt macht
-- den Schritt wiederholbar: Beim zweiten Lauf steht dort kein Text mehr.
update public.property_definitions
set options = (
  select coalesce(jsonb_agg(
    case when jsonb_typeof(o) = 'string'
      then jsonb_build_object('wert', o, 'text', o, 'verborgen', false)
      else o
    end order by ord), '[]'::jsonb)
  from jsonb_array_elements(options) with ordinality as t(o, ord)
)
where jsonb_typeof(options) = 'array'
  and exists (
    select 1 from jsonb_array_elements(options) e where jsonb_typeof(e) = 'string'
  );
