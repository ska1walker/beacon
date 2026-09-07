"""Ein- und Ausgabeformen der API.

Beträge stehen überall in Cent (`amount_cents`). Die Oberfläche formatiert,
die API rechnet — ein Fließkommawert für 9.900 € wäre über zwei, drei
Umrechnungen hinweg nicht mehr exakt.
"""

from datetime import date, datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field, field_validator


def _json_dict(wert: Any) -> dict[str, Any]:
    """asyncpg liefert jsonb als Text — die Oberfläche braucht ein Objekt."""
    import orjson

    if wert is None or wert == "":
        return {}
    if isinstance(wert, str | bytes):
        return orjson.loads(wert)
    return wert


class MitEigenschaften(BaseModel):
    """Eigene Eigenschaften, Schlüssel = key der Definition (siehe 0008)."""

    custom: dict[str, Any] = {}

    @field_validator("custom", mode="before")
    @classmethod
    def _custom_lesen(cls, wert: Any) -> dict[str, Any]:
        return _json_dict(wert)

LifecycleStage = Literal["lead", "qualified", "opportunity", "customer", "partner", "disqualified"]
DealProduct = Literal["assistent", "analyst", "experte", "service", "sonstiges"]
ActivityKind = Literal[
    "note", "call", "email", "meeting", "task", "stage_change", "quote", "ai", "system"
]
StageKind = Literal["open", "won", "lost"]


# ── Firmen ──────────────────────────────────────────────────────────────

class CompanyIn(MitEigenschaften):
    name: str = Field(min_length=1, max_length=200)
    domain: str | None = None
    industry: str | None = None
    employee_count: int | None = Field(default=None, ge=0)
    street: str | None = None
    postal_code: str | None = None
    city: str | None = None
    country: str | None = "DE"
    phone: str | None = None
    website: str | None = None
    linkedin_url: str | None = None
    lifecycle_stage: LifecycleStage = "lead"
    source: str | None = None
    description: str | None = None
    owner_id: UUID | None = None


class CompanyPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    domain: str | None = None
    industry: str | None = None
    employee_count: int | None = Field(default=None, ge=0)
    street: str | None = None
    postal_code: str | None = None
    city: str | None = None
    country: str | None = None
    phone: str | None = None
    website: str | None = None
    linkedin_url: str | None = None
    lifecycle_stage: LifecycleStage | None = None
    source: str | None = None
    description: str | None = None
    owner_id: UUID | None = None
    custom: dict[str, Any] | None = None


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

class ContactIn(MitEigenschaften):
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
    custom: dict[str, Any] | None = None


class Contact(ContactIn):
    id: UUID
    company_name: str | None = None
    ai_summary: str | None = None
    # Marketing-Einwilligung mit Beleg (0018). `keine` ist die Vorgabe und
    # heißt: keine Marketing-Post. `bestandskunde` wird bewusst gesetzt,
    # nie abgeleitet — es ist die Ausnahme aus §7 Abs. 3 UWG.
    marketing_einwilligung: str = "keine"
    einwilligung_am: datetime | None = None
    einwilligung_quelle: str | None = None
    einwilligung_nachweis: dict[str, Any] | None = None
    abgemeldet_am: datetime | None = None
    created_at: datetime
    updated_at: datetime

    @field_validator("einwilligung_nachweis", mode="before")
    @classmethod
    def _nachweis_lesen(cls, wert: Any) -> dict[str, Any] | None:
        return _json_dict(wert) if wert not in (None, "") else None


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

class DealIn(MitEigenschaften):
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
    custom: dict[str, Any] | None = None


class Deal(MitEigenschaften):
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
    # Wie viele Ansprechpartner am Lead hängen. Als Zahl statt als Liste:
    # Das Board zeigt sie an jeder Karte, und dort wäre ein Join je Karte
    # eine Abfrage zu viel.
    kontakt_anzahl: int = 0
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
    ticket_id: UUID | None = None
    payload: dict = {}


class Activity(ActivityIn):
    id: UUID
    created_by: UUID | None = None
    created_by_name: str | None = None
    created_at: datetime


AufgabenArt = Literal["todo", "anruf", "email", "termin"]
# „Nicht gestartet“ ist weder offen noch erledigt — ohne diesen
# Zwischenstand steht eine halbfertige Aufgabe jeden Morgen wieder da,
# als hätte niemand sie angefasst.
AufgabenPhase = Literal["nicht_gestartet", "in_arbeit", "wartet"]
Prioritaet = Literal["niedrig", "mittel", "hoch", "dringend"]


class TaskIn(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    body: str | None = None
    due_at: datetime | None = None
    art: AufgabenArt = "todo"
    phase: AufgabenPhase = "nicht_gestartet"
    prioritaet: Prioritaet = "mittel"
    company_id: UUID | None = None
    contact_id: UUID | None = None
    deal_id: UUID | None = None
    ticket_id: UUID | None = None
    assigned_to: UUID | None = None


class TaskPatch(BaseModel):
    title: str | None = None
    body: str | None = None
    status: Literal["open", "done", "cancelled"] | None = None
    art: AufgabenArt | None = None
    phase: AufgabenPhase | None = None
    prioritaet: Prioritaet | None = None
    due_at: datetime | None = None
    assigned_to: UUID | None = None
    company_id: UUID | None = None
    contact_id: UUID | None = None
    deal_id: UUID | None = None
    ticket_id: UUID | None = None


class Task(TaskIn):
    id: UUID
    status: Literal["open", "done", "cancelled"]
    deal_name: str | None = None
    company_name: str | None = None
    kontakt_name: str | None = None
    ticket_betreff: str | None = None
    zustaendig_name: str | None = None
    completed_at: datetime | None = None
    created_at: datetime


# ── Einstellungen ───────────────────────────────────────────────────────

class Absender(BaseModel):
    """Der Briefkopf. Steht unter jedem Angebot, das das Haus verlässt."""

    absender_name: str | None = None
    absender_strasse: str | None = None
    absender_plz: str | None = None
    absender_ort: str | None = None
    absender_land: str | None = None
    absender_email: str | None = None
    absender_telefon: str | None = None
    absender_website: str | None = None
    ust_id: str | None = None
    vertretung: str | None = None
    registergericht: str | None = None
    bank_iban: str | None = None
    bank_name: str | None = None
    standard_bedingungen: str | None = None
    bindefrist_tage: int | None = Field(default=None, ge=1, le=365)


class OrgSettingsIn(Absender):
    mail_endpoint_url: str | None = None
    mail_endpoint_secret: str | None = None
    mail_absender: str | None = None
    llm_base_url: str | None = None
    llm_model: str | None = None
    llm_api_key: str | None = None
    suche_endpoint_url: str | None = None
    suche_api_key: str | None = None
    suche_region: str | None = Field(default=None, pattern=r"^([A-Z]{2})?$")
    anreicherung_automatisch: bool | None = None
    anreicherung_uebernahme: Literal["leere_felder", "vorschlag"] | None = None
    # Das Postfach, aus dem Tickets entstehen. Das Passwort geht nur
    # hinein, nie zurück — wie der LLM-Schlüssel.
    imap_host: str | None = None
    imap_port: int | None = Field(default=None, ge=1, le=65535)
    imap_benutzer: str | None = None
    imap_passwort: str | None = None
    imap_ordner: str | None = None
    imap_takt_minuten: int | None = Field(default=None, ge=1, le=1440)
    imap_aktiv: bool | None = None
    # Versand (0019). Passwort und Schlüssel gehen nur hinein.
    smtp_host: str | None = None
    smtp_port: int | None = Field(default=None, ge=1, le=65535)
    smtp_benutzer: str | None = None
    smtp_passwort: str | None = None
    smtp_sicherheit: Literal["starttls", "ssl", "keine"] | None = None
    smtp_absender: str | None = None
    smtp_absender_name: str | None = None
    marketing_versand: Literal["smtp", "brevo"] | None = None
    brevo_api_key: str | None = None
    marketing_absender: str | None = None
    marketing_absender_name: str | None = None
    links_basis_url: str | None = None
    doi_betreff: str | None = None
    doi_text: str | None = None
    # Sprachausgabe (0025). Der Schlüssel geht nur hinein.
    tts_endpoint_url: str | None = None
    tts_api_key: str | None = None
    tts_modell: str | None = None
    tts_stimme: str | None = None
    tts_modell_2: str | None = None
    tts_stimme_2: str | None = None
    podcast_automatisch: bool | None = None
    default_currency: str | None = None
    locale: str | None = None


class OrgSettings(Absender):
    mail_endpoint_url: str | None = None
    mail_absender: str | None = None
    mail_endpoint_secret_set: bool = False
    llm_base_url: str = ""
    llm_model: str = ""
    # Der Schlüssel geht nie zurück an die Oberfläche. Sie erfährt nur,
    # ob einer hinterlegt ist.
    llm_api_key_set: bool = False
    llm_ready: bool = False
    # Der Suchdienst für die Anreicherung — gleiches Muster: Adresse
    # sichtbar, Schlüssel nur als „hinterlegt".
    suche_endpoint_url: str | None = None
    suche_api_key_set: bool = False
    suche_region: str = "DE"
    anreicherung_automatisch: bool = True
    anreicherung_uebernahme: str = "leere_felder"
    # Das Postfach. Adresse und Benutzer sichtbar, das Passwort nur als
    # „hinterlegt" — dasselbe Muster wie beim LLM-Schlüssel.
    imap_host: str | None = None
    imap_port: int = 993
    imap_benutzer: str | None = None
    imap_passwort_set: bool = False
    imap_ordner: str = "INBOX"
    imap_takt_minuten: int = 5
    imap_aktiv: bool = False
    imap_zuletzt: datetime | None = None
    imap_letzter_fehler: str | None = None
    # Versand. Dasselbe Muster: Konto sichtbar, Passwort nur als „hinterlegt".
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_benutzer: str | None = None
    smtp_passwort_set: bool = False
    smtp_sicherheit: str = "starttls"
    smtp_absender: str | None = None
    smtp_absender_name: str | None = None
    smtp_zuletzt: datetime | None = None
    smtp_letzter_fehler: str | None = None
    smtp_ready: bool = False
    marketing_versand: str = "smtp"
    brevo_api_key_set: bool = False
    marketing_absender: str | None = None
    marketing_absender_name: str | None = None
    links_basis_url: str | None = None
    # Was tatsächlich gilt: der eigene Wert oder die abgeleitete Adresse.
    links_basis_wirksam: str | None = None
    doi_betreff: str | None = None
    doi_text: str | None = None
    # Sprachausgabe — dasselbe Muster: Adresse sichtbar, Schlüssel nur als
    # „hinterlegt".
    tts_endpoint_url: str | None = None
    tts_api_key_set: bool = False
    tts_modell: str = ""
    tts_stimme: str | None = None
    tts_modell_2: str = ""
    tts_stimme_2: str | None = None
    tts_ready: bool = False
    podcast_automatisch: bool = False
    default_currency: str = "EUR"
    locale: str = "de"


# ── Produkte ────────────────────────────────────────────────────────────

ProductKind = Literal["system", "hardware", "service", "subscription"]
QuoteStatus = Literal["draft", "sent", "accepted", "rejected", "expired"]


class Product(BaseModel):
    id: UUID
    key: str
    name: str
    description: str | None = None
    kind: ProductKind
    list_price_cents: int
    default_service_days: int | None = None
    position: int
    is_active: bool


class ProductIn(BaseModel):
    key: str = Field(min_length=1, max_length=50)
    name: str = Field(min_length=1, max_length=200)
    description: str | None = None
    kind: ProductKind = "system"
    list_price_cents: int = Field(default=0, ge=0)
    default_service_days: int | None = Field(default=None, ge=0)
    position: int = 0


class ProductPatch(BaseModel):
    name: str | None = None
    description: str | None = None
    kind: ProductKind | None = None
    list_price_cents: int | None = Field(default=None, ge=0)
    default_service_days: int | None = Field(default=None, ge=0)
    position: int | None = None
    is_active: bool | None = None


# ── Angebote ────────────────────────────────────────────────────────────

class QuoteItemIn(BaseModel):
    product_id: UUID | None = None
    title: str = Field(min_length=1, max_length=300)
    description: str | None = None
    quantity: float = Field(default=1, gt=0)
    unit_price_cents: int = Field(default=0, ge=0)
    discount_percent: float = Field(default=0, ge=0, le=100)
    position: int = 0


class QuoteItem(QuoteItemIn):
    id: UUID
    # Gerechnet, nie gespeichert: Ein abgelegter Zeilenbetrag und die
    # Faktoren daneben laufen beim ersten Tippfehler auseinander.
    line_total_cents: int


class QuoteIn(BaseModel):
    deal_id: UUID
    title: str = "Angebot"
    intro_text: str | None = None
    terms_text: str | None = None
    discount_cents: int = Field(default=0, ge=0)
    tax_rate: float = Field(default=0.19, ge=0, le=1)
    valid_until: date | None = None
    items: list[QuoteItemIn] = []


class QuotePatch(BaseModel):
    title: str | None = None
    intro_text: str | None = None
    terms_text: str | None = None
    discount_cents: int | None = Field(default=None, ge=0)
    tax_rate: float | None = Field(default=None, ge=0, le=1)
    valid_until: date | None = None
    decision_note: str | None = None


class Empfaenger(BaseModel):
    """Die Anschrift, die im Angebot oben steht."""

    name: str | None = None
    street: str | None = None
    postal_code: str | None = None
    city: str | None = None
    country: str | None = None
    ansprechpartner: str | None = None


class Quote(BaseModel):
    id: UUID
    deal_id: UUID
    deal_name: str | None = None
    company_name: str | None = None
    empfaenger: Empfaenger | None = None
    number: str
    number_seq: int
    status: QuoteStatus
    title: str
    intro_text: str | None = None
    terms_text: str | None = None
    discount_cents: int
    tax_rate: float
    valid_until: date | None = None
    sent_at: datetime | None = None
    decided_at: datetime | None = None
    decision_note: str | None = None
    items: list[QuoteItem] = []
    # Summen, alle gerechnet
    net_cents: int = 0
    discount_total_cents: int = 0
    taxable_cents: int = 0
    tax_cents: int = 0
    gross_cents: int = 0
    created_at: datetime
    updated_at: datetime


class QuoteStatusIn(BaseModel):
    status: QuoteStatus
    decision_note: str | None = None


# ── Qualifizierung ──────────────────────────────────────────────────────

class Qualifizierung(BaseModel):
    """Die sechs Fragen, die ein Geschäft tragen.

    Nicht sechzig. Was ein Zwei-Mann-Vertrieb tatsächlich unterscheidet:
    wofür, warum jetzt, wer entscheidet, ist Geld da, bis wann — und ob
    die Hardware ins Haus passt. Der letzte Punkt ist bei einem Gerät im
    Serverraum kein Detail, sondern der häufigste späte Stolperstein.
    """

    bedarf: str | None = None
    ausloeser: str | None = None
    entscheider: str | None = None
    budget_geklaert: bool = False
    zeitrahmen: str | None = None
    standort_geklaert: bool = False


class QualifizierungAntwort(Qualifizierung):
    punkte: int
    qualifikation_am: datetime | None = None
    # Was noch fehlt, im Klartext. Eine Punktzahl allein sagt niemandem,
    # was als Nächstes zu fragen ist.
    offen: list[str] = []


class Verlustgrund(BaseModel):
    id: UUID
    name: str
    position: int
    is_active: bool


class DealVerloren(BaseModel):
    lost_reason_id: UUID | None = None
    lost_reason: str | None = None


# ── Prognose ────────────────────────────────────────────────────────────

class Monatswert(BaseModel):
    monat: str           # 2026-09
    offen_cents: int
    gewichtet_cents: int
    anzahl: int


class Verlustanteil(BaseModel):
    grund: str
    anzahl: int
    summe_cents: int


class Produktanteil(BaseModel):
    produkt: str
    gewonnen: int
    verloren: int
    gewonnen_cents: int


class Prognose(BaseModel):
    offen_cents: int
    gewichtet_cents: int
    anzahl_offen: int
    gewonnen_cents: int
    anzahl_gewonnen: int
    verloren_cents: int
    anzahl_verloren: int
    # None statt 0, wenn es noch nichts Entschiedenes gibt: Eine
    # Trefferquote von 0 % und „noch kein Abschluss" sind zwei sehr
    # verschiedene Nachrichten.
    trefferquote: float | None = None
    durchschnittsdauer_tage: float | None = None
    durchschnittswert_cents: int | None = None
    monate: list[Monatswert] = []
    verlustgruende: list[Verlustanteil] = []
    produkte: list[Produktanteil] = []
    ueberfaellig_anzahl: int = 0
    ueberfaellig_cents: int = 0
