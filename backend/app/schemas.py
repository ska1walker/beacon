"""Ein- und Ausgabeformen der API.

Beträge stehen überall in Cent (`amount_cents`). Die Oberfläche formatiert,
die API rechnet — ein Fließkommawert für 9.900 € wäre über zwei, drei
Umrechnungen hinweg nicht mehr exakt.
"""

from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field

LifecycleStage = Literal["lead", "qualified", "opportunity", "customer", "partner", "disqualified"]
DealProduct = Literal["assistent", "analyst", "experte", "service", "sonstiges"]
ActivityKind = Literal["note", "call", "email", "meeting", "task", "stage_change", "ai", "system"]
StageKind = Literal["open", "won", "lost"]


# ── Firmen ──────────────────────────────────────────────────────────────

class CompanyIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    domain: str | None = None
    industry: str | None = None
    employee_count: int | None = Field(default=None, ge=0)
    city: str | None = None
    country: str | None = "DE"
    phone: str | None = None
    website: str | None = None
    lifecycle_stage: LifecycleStage = "lead"
    source: str | None = None
    description: str | None = None
    owner_id: UUID | None = None


class CompanyPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    domain: str | None = None
    industry: str | None = None
    employee_count: int | None = Field(default=None, ge=0)
    city: str | None = None
    country: str | None = None
    phone: str | None = None
    website: str | None = None
    lifecycle_stage: LifecycleStage | None = None
    source: str | None = None
    description: str | None = None
    owner_id: UUID | None = None


class Company(CompanyIn):
    id: UUID
    ai_summary: str | None = None
    ai_summary_at: datetime | None = None
    created_at: datetime
    updated_at: datetime
    # Aus Sicht der Liste zählt, wie viel offenes Geschäft an einer Firma
    # hängt — nicht, wie viele Datensätze es gibt.
    contact_count: int = 0
    open_deal_count: int = 0
    open_amount_cents: int = 0


# ── Kontakte ────────────────────────────────────────────────────────────

class ContactIn(BaseModel):
    first_name: str | None = None
    last_name: str | None = None
    email: EmailStr | None = None
    phone: str | None = None
    mobile: str | None = None
    job_title: str | None = None
    buying_role: str | None = None
    linkedin_url: str | None = None
    company_id: UUID | None = None
    lifecycle_stage: LifecycleStage = "lead"
    source: str | None = None
    notes: str | None = None
    owner_id: UUID | None = None


class ContactPatch(BaseModel):
    first_name: str | None = None
    last_name: str | None = None
    email: EmailStr | None = None
    phone: str | None = None
    mobile: str | None = None
    job_title: str | None = None
    buying_role: str | None = None
    linkedin_url: str | None = None
    company_id: UUID | None = None
    lifecycle_stage: LifecycleStage | None = None
    source: str | None = None
    notes: str | None = None
    owner_id: UUID | None = None


class Contact(ContactIn):
    id: UUID
    company_name: str | None = None
    ai_summary: str | None = None
    created_at: datetime
    updated_at: datetime


# ── Pipeline ────────────────────────────────────────────────────────────

class Stage(BaseModel):
    id: UUID
    name: str
    kind: StageKind
    probability: float
    position: int


class Pipeline(BaseModel):
    id: UUID
    name: str
    is_default: bool
    stages: list[Stage] = []


# ── Deals ───────────────────────────────────────────────────────────────

class DealIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    company_id: UUID | None = None
    pipeline_id: UUID | None = None
    stage_id: UUID | None = None
    product: DealProduct = "sonstiges"
    amount_cents: int = Field(default=0, ge=0)
    currency: str = "EUR"
    service_days: int | None = Field(default=None, ge=0)
    close_date: date | None = None
    next_step: str | None = None
    owner_id: UUID | None = None


class DealPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    company_id: UUID | None = None
    stage_id: UUID | None = None
    product: DealProduct | None = None
    amount_cents: int | None = Field(default=None, ge=0)
    service_days: int | None = Field(default=None, ge=0)
    close_date: date | None = None
    next_step: str | None = None
    lost_reason: str | None = None
    owner_id: UUID | None = None


class Deal(BaseModel):
    id: UUID
    name: str
    company_id: UUID | None = None
    company_name: str | None = None
    pipeline_id: UUID
    stage_id: UUID
    stage_name: str | None = None
    stage_kind: StageKind | None = None
    probability: float | None = None
    product: DealProduct
    amount_cents: int
    currency: str
    service_days: int | None = None
    close_date: date | None = None
    closed_at: datetime | None = None
    lost_reason: str | None = None
    next_step: str | None = None
    ai_summary: str | None = None
    owner_id: UUID | None = None
    created_at: datetime
    updated_at: datetime


class BoardColumn(BaseModel):
    stage: Stage
    deals: list[Deal]
    # Gewichtet mit der Stufenwahrscheinlichkeit — die Spaltensumme ist
    # sonst eine Zahl, die niemand benutzen kann.
    sum_amount_cents: int
    weighted_amount_cents: int


class Board(BaseModel):
    pipeline: Pipeline
    columns: list[BoardColumn]


class StageMove(BaseModel):
    stage_id: UUID
    lost_reason: str | None = None


# ── Aktivitäten und Aufgaben ────────────────────────────────────────────

class ActivityIn(BaseModel):
    kind: ActivityKind = "note"
    subject: str | None = None
    body: str | None = None
    occurred_at: datetime | None = None
    company_id: UUID | None = None
    contact_id: UUID | None = None
    deal_id: UUID | None = None
    payload: dict = {}


class Activity(ActivityIn):
    id: UUID
    created_by: UUID | None = None
    created_by_name: str | None = None
    created_at: datetime


class TaskIn(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    body: str | None = None
    due_at: datetime | None = None
    company_id: UUID | None = None
    contact_id: UUID | None = None
    deal_id: UUID | None = None
    assigned_to: UUID | None = None


class TaskPatch(BaseModel):
    title: str | None = None
    body: str | None = None
    status: Literal["open", "done", "cancelled"] | None = None
    due_at: datetime | None = None
    assigned_to: UUID | None = None


class Task(TaskIn):
    id: UUID
    status: Literal["open", "done", "cancelled"]
    completed_at: datetime | None = None
    created_at: datetime


# ── Einstellungen ───────────────────────────────────────────────────────

class OrgSettingsIn(BaseModel):
    llm_base_url: str | None = None
    llm_model: str | None = None
    llm_api_key: str | None = None
    default_currency: str | None = None
    locale: str | None = None


class OrgSettings(BaseModel):
    llm_base_url: str = ""
    llm_model: str = ""
    # Der Schlüssel geht nie zurück an die Oberfläche. Sie erfährt nur,
    # ob einer hinterlegt ist.
    llm_api_key_set: bool = False
    llm_ready: bool = False
    default_currency: str = "EUR"
    locale: str = "de"
