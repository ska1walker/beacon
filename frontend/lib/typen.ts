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
  | "ai"
  | "system";

export type StageKind = "open" | "won" | "lost";

export interface Company {
  id: string;
  name: string;
  domain: string | null;
  industry: string | null;
  employee_count: number | null;
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

export interface OrgSettings {
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
