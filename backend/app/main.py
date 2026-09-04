"""aicrm — FastAPI-Anwendung.

Keine eigene Anmeldung, kein CORS-Rundumschlag, keine Telemetrie: Auf
Olares steht der Envoy-Sidecar davor und hat den Token bereits geprüft.
"""

import asyncio
import contextlib
from contextlib import asynccontextmanager

import asyncpg
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app import anreicherung as anreicherung_kern
from app import sicherung
from app.config import settings
from app.db import acquire, acquire_as, close_pool, init_pool
from app.routers import (
    activities,
    angebote,
    anreicherung,
    ansichten,
    briefing,
    companies,
    contacts,
    deals,
    eigenschaften,
    eingang,
    fragen,
    ki,
    mitglieder,
    notiz,
    pipelines,
    post,
    tasks,
)
from app.routers import qualifizierung as qualifizierung_router
from app.routers import settings as settings_router
from app.routers import sicherung as sicherung_router


async def _stammdaten_nachziehen() -> None:
    """Sät Produktkatalog und Verlustgründe, wo sie fehlen.

    Läuft einmal beim Start. Die Aussaat beim Anlegen einer Organisation
    deckt nur neue ab — eine Box, die vor dieser Ausbaustufe installiert
    wurde, hätte nach dem Upgrade eine leere Produktliste und könnte kein
    Angebot schreiben. Für jede spätere Erweiterung des Katalogs greift
    derselbe Weg.
    """
    from app.auth import _seed_produkte, _seed_verlustgruende

    aufgaben = (
        ("products", _seed_produkte, "Produktkatalog"),
        ("loss_reasons", _seed_verlustgruende, "Verlustgründe"),
    )
    try:
        for tabelle, saeen, bezeichnung in aufgaben:
            async with acquire() as conn:
                orgs = await conn.fetch(
                    f"""
                    select o.id, r.user_id
                    from public.orgs o
                    join public.user_org_roles r on r.org_id = o.id and r.role = 'owner'
                    where o.deleted_at is null
                      and not exists (select 1 from public.{tabelle} t where t.org_id = o.id)
                    """
                )
            for org in orgs:
                async with acquire_as(org["user_id"]) as conn:
                    await saeen(conn, org["id"])
            if orgs:
                print(f"{bezeichnung} für {len(orgs)} Organisation(en) nachgezogen.", flush=True)
    except Exception as exc:
        # Fehlende Stammdaten sind ärgerlich, aber kein Grund, die
        # Anwendung nicht zu starten.
        print(f"Stammdaten konnten nicht nachgezogen werden: {exc}", flush=True)


async def _sicherungsschleife() -> None:
    """Schreibt in festem Abstand einen Abzug je Organisation.

    Ohne das hinge die einzige Rettung daran, dass jemand daran denkt. Der
    Abstand steht in den Einstellungen; im schlimmsten Fall ist ein halber
    Arbeitstag verloren, nicht der ganze Bestand.

    Läuft als Aufgabe in der Anwendung und nicht als Celery-Job: Es gibt
    keinen Broker in dieser Ausbaustufe, und eine Schleife, die alle sechs
    Stunden einmal aufwacht, rechtfertigt keinen.
    """
    abstand = settings.sicherung_intervall_stunden * 3600
    while True:
        try:
            async with acquire() as conn:
                orgs = await conn.fetch(
                    """
                    select o.id, o.slug, r.user_id
                    from public.orgs o
                    join public.user_org_roles r on r.org_id = o.id and r.role = 'owner'
                    where o.deleted_at is null
                    """
                )
            for org in orgs:
                async with acquire_as(org["user_id"]) as conn:
                    daten = await sicherung.abzug_erstellen(conn, org["id"])
                sicherung.abzug_schreiben(daten, org["slug"])
        except Exception as exc:
            # Eine gescheiterte Sicherung darf die Anwendung nicht
            # mitnehmen — aber sie muss im Protokoll stehen.
            print(f"Selbsttätige Sicherung fehlgeschlagen: {exc}", flush=True)
        await asyncio.sleep(abstand)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_pool()
    await _stammdaten_nachziehen()
    schleife = asyncio.create_task(_sicherungsschleife())
    yield
    schleife.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await schleife
    # Ein Anreicherungslauf, der gerade eine Website liest, soll sein
    # Ergebnis noch ablegen dürfen — sonst bleibt eine Zeile auf „läuft".
    await anreicherung_kern.hintergrund_abwarten()
    await close_pool()


app = FastAPI(
    title="aicrm",
    description="KI-gestütztes CRM für den AImighty-Vertrieb",
    version="0.1.0",
    lifespan=lifespan,
)

app.include_router(companies.router)
app.include_router(angebote.router)
app.include_router(qualifizierung_router.router)
app.include_router(contacts.router)
app.include_router(deals.router)
app.include_router(activities.router)
app.include_router(tasks.router)
app.include_router(settings_router.router)
app.include_router(ki.router)
app.include_router(notiz.router)
app.include_router(briefing.router)
app.include_router(fragen.router)
app.include_router(eingang.router)
app.include_router(eingang.quellen_router)
app.include_router(mitglieder.router)
app.include_router(eigenschaften.router)
app.include_router(pipelines.router)
app.include_router(post.router)
app.include_router(sicherung_router.router)
app.include_router(anreicherung.router)
app.include_router(ansichten.router)


# Doppelte E-Mail, doppelte Domain: Das ist kein Serverfehler, sondern
# eine Eingabe, die schon existiert — im Vertrieb der Normalfall, nicht
# der Ausnahmefall. Ein zentraler Handler statt eines try/except an jeder
# Einfügung: Die Bedingungen stehen im Schema, nicht in den Routern.
UNIQUE_TEXTE: dict[str, str] = {
    "contacts_org_email_uniq": "Ein Kontakt mit dieser E-Mail-Adresse ist schon angelegt.",
    "companies_org_domain_uniq": "Eine Firma mit dieser Domain ist schon angelegt.",
    "orgs_slug_key": "Diese Organisationskennung ist vergeben.",
    "users_olares_username_key": "Dieser Benutzername ist vergeben.",
}


@app.exception_handler(asyncpg.exceptions.UniqueViolationError)
async def doppelter_eintrag(request: Request, exc: asyncpg.exceptions.UniqueViolationError):
    grund = UNIQUE_TEXTE.get(
        exc.constraint_name or "", "Dieser Eintrag existiert bereits."
    )
    return JSONResponse(status_code=409, content={"detail": grund})


@app.get("/health", tags=["system"])
async def health() -> dict[str, str]:
    """Für die Bereitschaftsprüfung von Kubernetes.

    Bewusst ohne Datenbankabfrage: Ein Pod, den die Datenbank kurz nicht
    annimmt, ist noch kein Pod, den Kubernetes neu starten soll.
    """
    return {"status": "ok", "lang": settings.app_lang}
