// Die Formen, die die API liefert. Sie spiegeln backend/app/schemas.py —
// wer dort etwas ändert, ändert es hier mit. Ein Generator dafür wäre bei
// dieser Größe mehr Maschinerie als Nutzen.

export type LifecycleStage =
  | "lead"
  | "qualified"
  | "opportunity"
  | "customer"
  | "partner"
  | "disqualified";

export type DealProduct = "assistent" | "analyst" | "experte" | "service" | "sonstiges";

export type ActivityKind =
  | "note"
  | "call"
  | "email"
  | "meeting"
  | "task"
  | "stage_change"
  | "quote"
  | "ai"
  | "system";

export type StageKind = "open" | "won" | "lost";

export interface Company {
  id: string;
  custom: Eigenschaftswerte;
  name: string;
  domain: string | null;
  industry: string | null;
  employee_count: number | null;
  street: string | null;
  postal_code: string | null;
  city: string | null;
  country: string | null;
  phone: string | null;
  website: string | null;
  linkedin_url: string | null;
  lifecycle_stage: LifecycleStage;
  source: string | null;
  description: string | null;
  ai_summary: string | null;
  ai_summary_at: string | null;
  owner_id: string | null;
  created_at: string;
  updated_at: string;
  contact_count: number;
  open_deal_count: number;
  open_amount_cents: number;
}

export type Einwilligung = "keine" | "angefragt" | "bestaetigt" | "bestandskunde" | "abgemeldet";

export interface Contact {
  id: string;
  custom: Eigenschaftswerte;
  first_name: string | null;
  last_name: string | null;
  email: string | null;
  phone: string | null;
  mobile: string | null;
  job_title: string | null;
  buying_role: string | null;
  linkedin_url: string | null;
  company_id: string | null;
  company_name: string | null;
  lifecycle_stage: LifecycleStage;
  source: string | null;
  /** Marketing-Einwilligung mit Beleg (0018). `keine` heißt: keine
   *  Marketing-Post. `bestandskunde` ist die Ausnahme aus §7 Abs. 3 UWG
   *  und wird bewusst gesetzt, nie abgeleitet. */
  marketing_einwilligung: Einwilligung;
  einwilligung_am: string | null;
  einwilligung_quelle: string | null;
  einwilligung_nachweis: Record<string, string | null> | null;
  abgemeldet_am: string | null;
  notes: string | null;
  ai_summary: string | null;
  created_at: string;
  updated_at: string;
}

export interface Stage {
  id: string;
  name: string;
  kind: StageKind;
  probability: number;
  position: number;
}

export interface Pipeline {
  id: string;
  name: string;
  is_default: boolean;
  stages: Stage[];
}

export interface Deal {
  id: string;
  custom: Eigenschaftswerte;
  name: string;
  company_id: string | null;
  company_name: string | null;
  pipeline_id: string;
  stage_id: string;
  stage_name: string | null;
  stage_kind: StageKind | null;
  probability: number | null;
  product: DealProduct;
  amount_cents: number;
  currency: string;
  service_days: number | null;
  close_date: string | null;
  closed_at: string | null;
  lost_reason: string | null;
  next_step: string | null;
  ai_summary: string | null;
  owner_id: string | null;
  /** Wie viele Ansprechpartner am Lead hängen. */
  kontakt_anzahl: number;
  created_at: string;
  updated_at: string;
}

/** Ein Ansprechpartner an einem Lead, samt seiner Rolle darin. */
export interface Beteiligter {
  contact_id: string;
  name: string;
  email: string | null;
  phone: string | null;
  job_title: string | null;
  company_id: string | null;
  company_name: string | null;
  role: string | null;
}

export interface BoardColumn {
  stage: Stage;
  deals: Deal[];
  sum_amount_cents: number;
  weighted_amount_cents: number;
}

export interface Board {
  pipeline: Pipeline;
  columns: BoardColumn[];
}

export interface Activity {
  id: string;
  kind: ActivityKind;
  subject: string | null;
  body: string | null;
  occurred_at: string;
  company_id: string | null;
  contact_id: string | null;
  deal_id: string | null;
  payload: Record<string, unknown>;
  created_by: string | null;
  created_by_name: string | null;
  created_at: string;
}

export type AufgabenArt = "todo" | "anruf" | "email" | "termin";
export type AufgabenPhase = "nicht_gestartet" | "in_arbeit" | "wartet";

export interface Task {
  id: string;
  title: string;
  body: string | null;
  status: "open" | "done" | "cancelled";
  art: AufgabenArt;
  phase: AufgabenPhase;
  prioritaet: Ticketprioritaet;
  due_at: string | null;
  company_id: string | null;
  contact_id: string | null;
  deal_id: string | null;
  ticket_id: string | null;
  assigned_to: string | null;
  completed_at: string | null;
  created_at: string;
  deal_name: string | null;
  company_name: string | null;
  kontakt_name: string | null;
  ticket_betreff: string | null;
  zustaendig_name: string | null;
}

export interface Aufgabenuebersicht {
  offen: number;
  heute: number;
  ueberfaellig: number;
  bevorstehend: number;
  meine: number;
}

export interface Absender {
  absender_name: string | null;
  absender_strasse: string | null;
  absender_plz: string | null;
  absender_ort: string | null;
  absender_land: string | null;
  absender_email: string | null;
  absender_telefon: string | null;
  absender_website: string | null;
  ust_id: string | null;
  vertretung: string | null;
  registergericht: string | null;
  bank_iban: string | null;
  bank_name: string | null;
  standard_bedingungen: string | null;
  bindefrist_tage: number | null;
}

export interface OrgSettings extends Absender {
  mail_endpoint_url: string | null;
  mail_absender: string | null;
  mail_endpoint_secret_set: boolean;
  llm_base_url: string;
  llm_model: string;
  llm_api_key_set: boolean;
  llm_ready: boolean;
  suche_endpoint_url: string | null;
  suche_api_key_set: boolean;
  anreicherung_automatisch: boolean;
  anreicherung_uebernahme: "leere_felder" | "vorschlag";
  /** Das Postfach, aus dem Tickets entstehen. Das Passwort kommt nie
   *  zurück — die Oberfläche erfährt nur, ob eines hinterlegt ist. */
  imap_host: string | null;
  imap_port: number;
  imap_benutzer: string | null;
  imap_passwort_set: boolean;
  imap_ordner: string;
  imap_takt_minuten: number;
  imap_aktiv: boolean;
  imap_zuletzt: string | null;
  imap_letzter_fehler: string | null;
  default_currency: string;
  locale: string;
}

/** Ein Lauf der Anreicherung — was gelesen, vorgeschlagen, geschrieben wurde. */
export interface Anreicherung {
  id: string;
  entity: "companies" | "contacts";
  entity_id: string;
  status: "laeuft" | "vorschlag" | "uebernommen" | "verworfen" | "leer" | "fehler";
  quellen: { url: string; titel: string; bytes: number; art: "seite" | "suche"; anfrage?: string }[];
  vorschlag: Record<string, { wert: string | number; quelle: string; belegt: boolean; lage: "neu" | "abweichend" }>;
  uebernommen: Record<string, string | number>;
  fehler: string | null;
  modell: string | null;
  created_at: string;
  updated_at: string;
}

export interface AnreicherungStatus {
  llm_ready: boolean;
  suche_eingerichtet: boolean;
  suche_art: string;
  automatisch: boolean;
  uebernahme: "leere_felder" | "vorschlag";
  hint: string;
}

export interface KIStatus {
  ready: boolean;
  model: string;
  hint: string;
}

export interface KIErgebnis {
  text: string;
  model: string;
}

export interface Sicherungsstand {
  name: string;
  groesse_bytes: number;
  erstellt_am: string;
}

export interface Sicherungsbilanz {
  datei: string | null;
  zeilen: Record<string, number>;
}

export interface Wiederherstellung {
  datei: string | null;
  geschrieben: Record<string, number>;
  uebersprungen: Record<string, number>;
}

export type ProductKind = "system" | "hardware" | "service" | "subscription";
export type QuoteStatus = "draft" | "sent" | "accepted" | "rejected" | "expired";

export interface Product {
  id: string;
  key: string;
  name: string;
  description: string | null;
  kind: ProductKind;
  list_price_cents: number;
  default_service_days: number | null;
  position: number;
  is_active: boolean;
}

export interface QuoteItem {
  id: string;
  product_id: string | null;
  title: string;
  description: string | null;
  quantity: number;
  unit_price_cents: number;
  discount_percent: number;
  position: number;
  line_total_cents: number;
}

export interface QuoteItemIn {
  product_id?: string | null;
  title: string;
  description?: string | null;
  quantity: number;
  unit_price_cents: number;
  discount_percent?: number;
  position?: number;
}

export interface Empfaenger {
  name: string | null;
  street: string | null;
  postal_code: string | null;
  city: string | null;
  country: string | null;
  ansprechpartner: string | null;
}

export interface Quote {
  id: string;
  deal_id: string;
  deal_name: string | null;
  company_name: string | null;
  empfaenger: Empfaenger | null;
  number: string;
  number_seq: number;
  status: QuoteStatus;
  title: string;
  intro_text: string | null;
  terms_text: string | null;
  discount_cents: number;
  tax_rate: number;
  valid_until: string | null;
  sent_at: string | null;
  decided_at: string | null;
  decision_note: string | null;
  items: QuoteItem[];
  net_cents: number;
  discount_total_cents: number;
  taxable_cents: number;
  tax_cents: number;
  gross_cents: number;
  created_at: string;
  updated_at: string;
}

export interface Angebotsposition {
  produkt_key: string | null;
  titel: string;
  beschreibung: string | null;
  menge: number;
  einzelpreis_cents: number;
}

export interface Angebotsvorschlag {
  begruendung: string;
  anschreiben: string;
  positionen: Angebotsposition[];
  offene_punkte: string[];
  modell: string;
}

export interface Qualifizierung {
  bedarf: string | null;
  ausloeser: string | null;
  entscheider: string | null;
  budget_geklaert: boolean;
  zeitrahmen: string | null;
  standort_geklaert: boolean;
}

export interface QualifizierungAntwort extends Qualifizierung {
  punkte: number;
  qualifikation_am: string | null;
  offen: string[];
}

export interface Qualifizierungsvorschlag extends Qualifizierung {
  punkte: number;
  offen: string[];
  belege: Record<string, string>;
  modell: string;
}

export interface Verlustgrund {
  id: string;
  name: string;
  position: number;
  is_active: boolean;
}

export interface Monatswert {
  monat: string;
  offen_cents: number;
  gewichtet_cents: number;
  anzahl: number;
}

export interface Verlustanteil {
  grund: string;
  anzahl: number;
  summe_cents: number;
}

export interface Produktanteil {
  produkt: string;
  gewonnen: number;
  verloren: number;
  gewonnen_cents: number;
}

export interface Prognose {
  offen_cents: number;
  gewichtet_cents: number;
  anzahl_offen: number;
  gewonnen_cents: number;
  anzahl_gewonnen: number;
  verloren_cents: number;
  anzahl_verloren: number;
  trefferquote: number | null;
  durchschnittsdauer_tage: number | null;
  durchschnittswert_cents: number | null;
  monate: Monatswert[];
  verlustgruende: Verlustanteil[];
  produkte: Produktanteil[];
  ueberfaellig_anzahl: number;
  ueberfaellig_cents: number;
}

export interface Aufgabenvorschlag {
  titel: string;
  faellig_am: string | null;
}

export interface Notizvorschlag {
  art: ActivityKind;
  betreff: string;
  zusammenfassung: string;
  aufgaben: Aufgabenvorschlag[];
  naechster_schritt: string | null;
  qualifizierung: Qualifizierung | null;
  qualifikation_punkte: number | null;
  unbekannte_personen: string[];
  modell: string;
}

export interface Uebernahmebilanz {
  aktivitaet_id: string;
  aufgaben: number;
  naechster_schritt_gesetzt: boolean;
  qualifizierung_gesetzt: boolean;
}

export interface Posten {
  art: string;
  titel: string;
  hinweis: string | null;
  deal_id: string | null;
  company_id: string | null;
  betrag_cents: number | null;
  tage: number | null;
}

export interface Briefing {
  stand: string;
  faellige_aufgaben: Posten[];
  ueberfaellige_geschaefte: Posten[];
  verstummte_geschaefte: Posten[];
  ablaufende_angebote: Posten[];
  ohne_naechsten_schritt: Posten[];
  offener_eingang: Posten[];
  gesamt: number;
}

export interface Fundstelle {
  art: string;
  id: string | null;
  titel: string;
  text: string;
}

export interface Frageantwort {
  antwort: string;
  fundstellen: Fundstelle[];
  modell: string;
  hinweis: string | null;
}

/** Was eine eingehende Quelle ist — und ob sie durchregieren darf. */
export type Quellenart = "insilo" | "api" | "bot" | "formular";

export interface Quelle {
  id: string;
  name: string;
  kind: string;
  /** Ob diese Quelle Tickets unmittelbar anlegt oder im Eingang wartet. */
  tickets_direkt: boolean;
  is_active: boolean;
  created_at: string;
  last_seen_at: string | null;
  pfad: string;
}

export interface QuelleNeu extends Quelle {
  secret: string;
}

export interface Eingangsposten {
  id: string;
  event: string;
  titel: string | null;
  external_id: string | null;
  occurred_at: string | null;
  status: string;
  company_id: string | null;
  company_name: string | null;
  deal_id: string | null;
  deal_name: string | null;
  zuordnung_grund: string | null;
  markdown_laenge: number;
  created_at: string;
}

export interface Mitglied {
  id: string;
  display_name: string | null;
  email: string | null;
  olares_username: string;
  zugang: "olares" | "sitzplatz";
  role: string;
  created_at: string;
  last_seen_at: string | null;
}

export interface Wer {
  user_id: string;
  display_name: string | null;
  org_id: string;
  login_username: string;
  sitzplatz_gewaehlt: boolean;
}

export type PropertyKind = "text" | "number" | "date" | "bool" | "select" | "multiselect";
export type PropertyEntity = "companies" | "contacts" | "deals";

/**
 * Eine wählbare Option einer Auswahl oder Mehrfachauswahl.
 *
 * `wert` steht in den Datensätzen und ändert sich nie; `text` ist die
 * Beschriftung und darf sich jederzeit ändern. Wer beides gleichsetzt,
 * kann eine Beschriftung nie wieder korrigieren, ohne die vorhandenen
 * Werte zu entwerten. `verborgen` heißt archiviert: nicht mehr wählbar,
 * in den Datensätzen weiter gültig.
 */
export interface Eigenschaftsoption {
  wert: string;
  text: string;
  verborgen: boolean;
}

export interface PropertyDefinition {
  id: string;
  entity: PropertyEntity;
  key: string;
  label: string;
  kind: PropertyKind;
  options: Eigenschaftsoption[];
  description: string | null;
  position: number;
  is_active: boolean;
  created_at: string;
}

/** Werte eigener Eigenschaften — Schlüssel = key der Definition.
 *  Eine Mehrfachauswahl steht als Liste; alles andere als ein Wert. */
export type Eigenschaftswert = string | number | boolean | string[] | null;
export type Eigenschaftswerte = Record<string, Eigenschaftswert>;

// ── Erfassung aus Hingeworfenem ──────────────────────────────────────

/** Was das Modell aus Text oder Bild gelesen hat. Noch nichts davon ist
 *  gespeichert — es füllt die Maske, ein Mensch drückt auf Anlegen. */
export interface Erfassungsvorschlag {
  art: "contact" | "company";
  felder: Record<string, string>;
  /** Was dastand und in kein Feld passte. Wird nicht verschluckt. */
  rest: string | null;
  modell: string;
  /** Ein vorhandener Datensatz, der dasselbe sein könnte. */
  dublette: Record<string, string | null> | null;
}

export interface Firmenverknuepfung {
  company_id: string;
  company_name: string;
  role: string | null;
  ist_haupt: boolean;
}

// ── Segmentierung ────────────────────────────────────────────────────
// Eine Liste ist nie „alle", sondern eine Frage an den Bestand. Wer sie
// einmal gestellt hat, speichert sie als Ansicht.

export type Objektart = "companies" | "contacts" | "tickets" | "tasks";

export type Feldart =
  | "text"
  | "auswahl"
  | "mehrfachauswahl"
  | "zahl"
  | "datum"
  | "jaNein"
  | "person";

export interface Segmentfeld {
  schluessel: string;
  text: string;
  art: Feldart;
  optionen: { wert: string; text: string; verborgen?: boolean }[];
  filterbar: boolean;
  zahl: boolean;
  eigen: boolean;
  operatoren: string[];
}

export interface Bedingung {
  feld: string;
  operator: string;
  wert?: string | number | string[] | null;
}

export interface Ansicht {
  id: string;
  entity: Objektart;
  name: string;
  filter: Bedingung[];
  verknuepfung: "und" | "oder";
  spalten: string[];
  sort_feld: string | null;
  sort_richtung: "asc" | "desc";
  owner_id: string | null;
  position: number;
}

export interface Feldauskunft {
  felder: Segmentfeld[];
  personen: { id: string; name: string }[];
  vorgabe_spalten: string[];
  vorgabe_sortierung: { feld: string; richtung: "asc" | "desc" };
}

// ── Tickets ──────────────────────────────────────────────────────────

export type Ticketprioritaet = "niedrig" | "mittel" | "hoch" | "dringend";
export type Ticketstufenart = "neu" | "offen" | "wartet_auf_kontakt" | "abgeschlossen";
export type Ticketquelle =
  | "manuell"
  | "email"
  | "telefon"
  | "insilo"
  | "formular"
  | "api"
  | "bot";

export interface Ticketstufe {
  id: string;
  name: string;
  art: Ticketstufenart;
  position: number;
}

export interface Ticketpipeline {
  id: string;
  name: string;
  is_default: boolean;
  stufen: Ticketstufe[];
}

export interface Ticketkategorie {
  id: string;
  name: string;
  position: number;
  is_active: boolean;
}

export interface Ticket {
  id: string;
  nummer: number;
  kennung: string;
  betreff: string;
  beschreibung: string | null;
  pipeline_id: string;
  stage_id: string;
  stufe_name: string;
  stufe_art: Ticketstufenart;
  prioritaet: Ticketprioritaet;
  kategorie: string | null;
  quelle: Ticketquelle;
  /** Wer geschrieben hat — bleibt stehen, auch ohne passenden Kontakt. */
  absender_email: string | null;
  absender_name: string | null;
  owner_id: string | null;
  besitzer_name: string | null;
  contact_id: string | null;
  kontakt_name: string | null;
  kontakt_email: string | null;
  company_id: string | null;
  firma_name: string | null;
  deal_id: string | null;
  erste_antwort_am: string | null;
  geschlossen_am: string | null;
  faellig_am: string | null;
  letzte_aktivitaet: string | null;
  custom: Eigenschaftswerte;
  created_at: string;
  updated_at: string;
  offen: boolean;
  ueberfaellig: boolean;
}

export interface Ticketspalte {
  stufe: Ticketstufe;
  tickets: Ticket[];
  anzahl: number;
}

export interface Ticketbrett {
  pipeline: Ticketpipeline;
  spalten: Ticketspalte[];
}
