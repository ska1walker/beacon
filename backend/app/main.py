"""aicrm — FastAPI-Anwendung.

Keine eigene Anmeldung, kein CORS-Rundumschlag, keine Telemetrie: Auf
Olares steht der Envoy-Sidecar davor und hat den Token bereits geprüft.
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.config import settings
from app.db import close_pool, init_pool
from app.routers import activities, companies, contacts, deals, ki, tasks
from app.routers import settings as settings_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_pool()
    yield
    await close_pool()


app = FastAPI(
    title="aicrm",
    description="KI-gestütztes CRM für den AImighty-Vertrieb",
    version="0.1.0",
    lifespan=lifespan,
)

app.include_router(companies.router)
app.include_router(contacts.router)
app.include_router(deals.router)
app.include_router(activities.router)
app.include_router(tasks.router)
app.include_router(settings_router.router)
app.include_router(ki.router)


@app.get("/health", tags=["system"])
async def health() -> dict[str, str]:
    """Für die Bereitschaftsprüfung von Kubernetes.

    Bewusst ohne Datenbankabfrage: Ein Pod, den die Datenbank kurz nicht
    annimmt, ist noch kein Pod, den Kubernetes neu starten soll.
    """
    return {"status": "ok", "lang": settings.app_lang}
