"""Aus einer hingetippten Notiz wird Struktur.

Der Vorgang, der im Vertrieb am meisten Zeit frisst, ist nicht das
Gespräch — es ist das Nacharbeiten danach: Notiz ablegen, Aufgaben
anlegen, nächsten Schritt setzen, die Qualifizierung nachziehen. Vier
Masken für ein Telefonat, das drei Minuten gedauert hat.

Hier gibt es einen Kasten. Was daraus wird, schlägt das Modell vor; was
davon bleibt, entscheidet ein Mensch mit einem Klick.
"""

from datetime import date, datetime, timedelta
from uuid import UUID

import httpx
import orjson
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app import qualifizierung
from app.auth import CurrentUser, get_current_user
from app.db import acquire_as
from app.llm import LLMNichtEingerichtet, chat, json_aus_antwort, load_llm_config
from app.routers.ki import SYSTEM
from app.schemas import ActivityKind, Qualifizierung

router = APIRouter(prefix="/api/notiz", tags=["notiz"])


class Bezug(BaseModel):
    company_id: UUID | None = None
    contact_id: UUID | None = None
    deal_id: UUID | None = None
    ticket_id: UUID | None = None

    def leer(self) -> bool:
        return not (self.company_id or self.contact_id or self.deal_id or self.ticket_id)


class NotizIn(Bezug):
    text: str = Field(min_length=10, max_length=20000)


class Aufgabenvorschlag(BaseModel):
    titel: str
    faellig_am: date | None = None


class Notizvorschlag(BaseModel):
    art: ActivityKind = "note"
    betreff: str
    zusammenfassung: str
    aufgaben: list[Aufgabenvorschlag] = []
    naechster_schritt: str | None = None
    qualifizierung: Qualifizierung | None = None
    qualifikation_punkte: int | None = None
    # Namen, die im Text vorkamen und im CRM nicht zu finden waren. Sie
    # werden nicht angelegt — das wäre geraten. Sie werden genannt.
    unbekannte_personen: list[str] = []
    modell: str


class Uebernahme(Bezug):
    art: ActivityKind = "note"
    betreff: str
    text: str
    aufgaben: list[Aufgabenvorschlag] = []
    naechster_schritt: str | None = None
    qualifizierung: Qualifizierung | None = None


class Uebernahmebilanz(BaseModel):
    aktivitaet_id: UUID
    aufgaben: int
    naechster_schritt_gesetzt: bool
    qualifizierung_gesetzt: bool


# Anreden, die kein Namensteil sind. Ohne sie gilt „Frau Lohse" als
# unbekannt, obwohl Katrin Lohse im CRM steht.
ANREDEN = {"herr", "frau", "dr", "prof", "dipl", "ing", "herrn"}


def _namensteile(name: str) -> set[str]:
    return {
        teil.strip(".,").lower()
        for teil in name.split()
        if teil.strip(".,").lower() not in ANREDEN and len(teil.strip(".,")) > 1
    }


def _ist_bekannt(genannt: str, bekannte: list[str]) -> bool:
    """Ist diese Person im CRM zu finden?

    Verglichen werden Namensteile, nicht ganze Zeichenketten. „Frau Lohse"
    und „Katrin Lohse" sind dieselbe Person; ein Vergleich auf Gleichheit
    hätte sie als unbekannt gemeldet — und der Vertriebler hätte den
    Hinweis nach dem dritten Mal ignoriert.
    """
    teile = _namensteile(genannt)
    if not teile:
        return False
    return any(teile & _namensteile(bekannt) for bekannt in bekannte)


def _relative_frist(hinweis: str | None) -> date | None:
    """Wandelt „morgen", „nächste Woche", „in 3 Tagen" in ein Datum.

    Ein Modell nach einem ISO-Datum zu fragen führt zuverlässig zu
    erfundenen Daten — es kennt das heutige nicht. Also fragen wir nach
    dem, was im Text steht, und rechnen hier.
    """
    if not hinweis:
        return None
    text = hinweis.strip().lower()
    heute = date.today()
    tabelle = {
        "heute": 0,
        "morgen": 1,
        "übermorgen": 2,
        "diese woche": 3,
        "nächste woche": 7,
        "naechste woche": 7,
        "in einer woche": 7,
        "in zwei wochen": 14,
        "nächsten monat": 30,
        "naechsten monat": 30,
    }
    if text in tabelle:
        return heute + timedelta(days=tabelle[text])

    # „in 3 Tagen"
    teile = text.split()
    for i, wort in enumerate(teile):
        if wort.isdigit() and i + 1 < len(teile):
            einheit = teile[i + 1]
            zahl = int(wort)
            if einheit.startswith("tag"):
                return heute + timedelta(days=zahl)
            if einheit.startswith("woche"):
                return heute + timedelta(weeks=zahl)
    # Ein ISO-Datum nehmen wir, wenn es eins ist.
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


@router.post("/verarbeiten", response_model=Notizvorschlag)
async def verarbeiten(
    payload: NotizIn,
    user: CurrentUser = Depends(get_current_user),
) -> Notizvorschlag:
    if payload.leer():
        raise HTTPException(400, "Eine Notiz braucht einen Bezug: Firma, Kontakt, Lead oder Ticket.")

    async with acquire_as(user.user_id) as conn:
        cfg = await load_llm_config(conn, user.org_id)
        bekannte = await conn.fetch(
            """
            select first_name, last_name from public.contacts
            where deleted_at is null
              and ($1::uuid is null or company_id = $1)
            limit 50
            """,
            payload.company_id,
        )

    namen = [
        " ".join(t for t in (k["first_name"], k["last_name"]) if t).strip() for k in bekannte
    ]

    frage = (
        "Aus der folgenden Gesprächsnotiz soll Struktur werden.\n\n"
        "Antworte ausschließlich als JSON-Objekt:\n"
        '  "art": eines von note, call, email, meeting,\n'
        '  "betreff": eine Zeile, höchstens 60 Zeichen,\n'
        '  "zusammenfassung": der Inhalt in ganzen Sätzen, ohne Ausschmückung,\n'
        '  "aufgaben": Liste aus {"titel", "wann"} — "wann" wörtlich wie im Text '
        '("morgen", "nächste Woche", "in 3 Tagen") oder null,\n'
        '  "naechster_schritt": ein Satz, oder null,\n'
        '  "qualifizierung": {"bedarf","ausloeser","entscheider","budget_geklaert",'
        '"zeitrahmen","standort_geklaert"} — nur was ausdrücklich im Text steht,\n'
        '  "personen": Namen, die vorkommen.\n\n'
        "Nichts erfinden. Kein Datum ausrechnen — schreibe die Zeitangabe so, wie sie "
        "im Text steht.\n\n"
        f"Im CRM bekannte Personen: {', '.join(namen) or 'keine'}\n\n"
        f"Notiz:\n{payload.text}"
    )

    try:
        antwort = await chat(cfg, SYSTEM, frage, temperature=0.2)
    except LLMNichtEingerichtet as exc:
        raise HTTPException(409, str(exc)) from exc
    except httpx.HTTPStatusError as exc:
        raise HTTPException(502, f"Der Endpunkt hat mit {exc.response.status_code} geantwortet.") from exc
    except httpx.RequestError as exc:
        raise HTTPException(502, f"Der Endpunkt {cfg.base_url} ist nicht erreichbar: {exc}") from exc

    try:
        roh = json_aus_antwort(antwort)
    except ValueError as exc:
        raise HTTPException(502, f"Das Modell hat kein verwertbares Ergebnis geliefert: {exc}") from exc

    arten = {"note", "call", "email", "meeting"}
    art = roh.get("art") if roh.get("art") in arten else "note"

    aufgaben = [
        Aufgabenvorschlag(
            titel=str(a.get("titel") or "").strip(),
            faellig_am=_relative_frist(a.get("wann")),
        )
        for a in (roh.get("aufgaben") or [])
        if str(a.get("titel") or "").strip()
    ]

    qual = None
    punkte = None
    rohqual = roh.get("qualifizierung")
    if isinstance(rohqual, dict):
        def sauber(schluessel: str) -> str | None:
            wert = rohqual.get(schluessel)
            if wert is None:
                return None
            wert = str(wert).strip()
            return None if wert.lower() in ("", "null", "unbekannt", "-") else wert

        qual = Qualifizierung(
            bedarf=sauber("bedarf"),
            ausloeser=sauber("ausloeser"),
            entscheider=sauber("entscheider"),
            budget_geklaert=bool(rohqual.get("budget_geklaert")),
            zeitrahmen=sauber("zeitrahmen"),
            standort_geklaert=bool(rohqual.get("standort_geklaert")),
        )
        punkte = qualifizierung.punkte(qual)

    genannt = [str(p).strip() for p in (roh.get("personen") or []) if str(p).strip()]
    unbekannt = [p for p in genannt if not _ist_bekannt(p, namen)]

    return Notizvorschlag(
        art=art,
        betreff=str(roh.get("betreff") or "Notiz")[:60],
        zusammenfassung=str(roh.get("zusammenfassung") or payload.text),
        aufgaben=aufgaben,
        naechster_schritt=(str(roh.get("naechster_schritt")).strip() or None)
        if roh.get("naechster_schritt")
        else None,
        qualifizierung=qual,
        qualifikation_punkte=punkte,
        unbekannte_personen=unbekannt,
        modell=cfg.model,
    )


@router.post("/uebernehmen", response_model=Uebernahmebilanz)
async def uebernehmen(
    payload: Uebernahme,
    user: CurrentUser = Depends(get_current_user),
) -> Uebernahmebilanz:
    """Schreibt, was der Mensch stehen gelassen hat — alles in einem Zug.

    In einer Transaktion, damit nicht die Notiz steht und die Aufgaben
    fehlen. Ein halb übernommener Vorschlag wäre schlimmer als keiner:
    Man sähe die Notiz und hielte die Nacharbeit für erledigt.
    """
    if payload.leer():
        raise HTTPException(400, "Eine Notiz braucht einen Bezug: Firma, Kontakt, Lead oder Ticket.")

    async with acquire_as(user.user_id) as conn:
        aktivitaet = await conn.fetchval(
            """
            insert into public.activities
              (org_id, kind, subject, body, company_id, contact_id, deal_id, ticket_id,
               payload, created_by)
            values ($1, $2::public.activity_kind, $3, $4, $5, $6, $7, $8, $9::jsonb, $10)
            returning id
            """,
            user.org_id,
            payload.art,
            payload.betreff,
            payload.text,
            payload.company_id,
            payload.contact_id,
            payload.deal_id,
            payload.ticket_id,
            orjson.dumps({"quelle": "notiz"}).decode(),
            user.user_id,
        )

        for aufgabe in payload.aufgaben:
            await conn.execute(
                """
                insert into public.tasks
                  (org_id, title, due_at, company_id, contact_id, deal_id, ticket_id,
                   assigned_to, created_by)
                values ($1,$2,$3,$4,$5,$6,$7,$8,$8)
                """,
                user.org_id,
                aufgabe.titel,
                datetime.combine(aufgabe.faellig_am, datetime.min.time().replace(hour=9))
                if aufgabe.faellig_am
                else None,
                payload.company_id,
                payload.contact_id,
                payload.deal_id,
                payload.ticket_id,
                user.user_id,
            )

        schritt_gesetzt = False
        qual_gesetzt = False
        if payload.deal_id:
            if payload.naechster_schritt:
                await conn.execute(
                    "update public.deals set next_step = $1 where id = $2",
                    payload.naechster_schritt,
                    payload.deal_id,
                )
                schritt_gesetzt = True

            if payload.qualifizierung:
                q = payload.qualifizierung
                # coalesce: Was schon dasteht, bleibt. Eine Notiz ergänzt
                # die Qualifizierung, sie ersetzt sie nicht — sonst löschte
                # ein Telefonat, in dem das Budget nicht vorkam, die
                # Budgetangabe aus dem Gespräch davor.
                await conn.execute(
                    """
                    update public.deals
                       set bedarf = coalesce($1, bedarf),
                           ausloeser = coalesce($2, ausloeser),
                           entscheider = coalesce($3, entscheider),
                           budget_geklaert = budget_geklaert or $4,
                           zeitrahmen = coalesce($5, zeitrahmen),
                           standort_geklaert = standort_geklaert or $6,
                           qualifikation_am = now()
                     where id = $7
                    """,
                    q.bedarf,
                    q.ausloeser,
                    q.entscheider,
                    q.budget_geklaert,
                    q.zeitrahmen,
                    q.standort_geklaert,
                    payload.deal_id,
                )
                # Die Punktzahl danach neu rechnen, aus dem, was jetzt
                # wirklich in der Zeile steht — nicht aus dem Vorschlag.
                zeile = await conn.fetchrow(
                    "select bedarf, ausloeser, entscheider, budget_geklaert, zeitrahmen, "
                    "standort_geklaert from public.deals where id = $1",
                    payload.deal_id,
                )
                await conn.execute(
                    "update public.deals set qualifikation_punkte = $1 where id = $2",
                    qualifizierung.punkte(Qualifizierung(**dict(zeile))),
                    payload.deal_id,
                )
                qual_gesetzt = True

    return Uebernahmebilanz(
        aktivitaet_id=aktivitaet,
        aufgaben=len(payload.aufgaben),
        naechster_schritt_gesetzt=schritt_gesetzt,
        qualifizierung_gesetzt=qual_gesetzt,
    )
