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

export interface Contact {
  id: string;
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
  created_at: string;
  updated_at: string;
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

export interface Task {
  id: string;
  title: string;
  body: string | null;
  status: "open" | "done" | "cancelled";
  due_at: string | null;
  company_id: string | null;
  contact_id: string | null;
  deal_id: string | null;
  assigned_to: string | null;
  completed_at: string | null;
  created_at: string;
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
  llm_base_url: string;
  llm_model: string;
  llm_api_key_set: boolean;
  llm_ready: boolean;
  default_currency: string;
  locale: string;
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
