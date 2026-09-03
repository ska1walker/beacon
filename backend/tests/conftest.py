"""Testaufbau.

Die Tests laufen gegen eine echte Postgres-Instanz mit einer eigenen
Datenbank, nicht gegen Attrappen. Der Grund ist die Zeilensicherheit: Sie
ist die Trennung zwischen zwei Mandanten, und eine nachgebaute Datenbank
würde genau das nicht prüfen, worauf es ankommt.
"""

import os
import pathlib

# Vor jedem Import aus app: die Einstellungen werden beim Laden des Moduls
# gelesen, ein späteres Setzen käme zu spät.
os.environ["DB_NAME"] = "aicrm_test"
os.environ["DB_USER"] = os.environ.get("TEST_DB_USER", "aicrm")
os.environ["DB_PASSWORD"] = os.environ.get("TEST_DB_PASSWORD", "aicrm_dev_only")
os.environ["DB_HOST"] = os.environ.get("TEST_DB_HOST", "localhost")
os.environ["DEV_USER"] = ""
os.environ["LLM_BASE_URL"] = ""
os.environ["LLM_API_KEY"] = ""
os.environ["LLM_MODEL"] = ""

import asyncpg  # noqa: E402
import pytest_asyncio  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402

from app.config import settings  # noqa: E402
from app.db import close_pool, init_pool  # noqa: E402
from app.main import app  # noqa: E402

MIGRATIONEN = pathlib.Path(__file__).resolve().parents[2] / "supabase" / "migrations"


async def _verwaltungsverbindung() -> asyncpg.Connection:
    return await asyncpg.connect(
        host=settings.db_host,
        port=settings.db_port,
        user=settings.db_user,
        password=settings.db_password,
        database="postgres",
    )


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def datenbank():
    verwaltung = await _verwaltungsverbindung()
    await verwaltung.execute("drop database if exists aicrm_test")
    await verwaltung.execute("create database aicrm_test")
    await verwaltung.close()

    # Die Migrationen laufen mit derselben Rolle wie die Anwendung. Das ist
    # kein Zufall: Sie wird dadurch Eigentümerin der Tabellen, genau wie
    # auf der Box — und nur so prüft der Test das FORCE aus 0002 wirklich.
    conn = await asyncpg.connect(
        host=settings.db_host,
        port=settings.db_port,
        user=settings.db_user,
        password=settings.db_password,
        database="aicrm_test",
    )
    for datei in sorted(MIGRATIONEN.glob("*.sql")):
        await conn.execute(datei.read_text())
    await conn.close()

    await init_pool()
    yield
    await close_pool()

    verwaltung = await _verwaltungsverbindung()
    await verwaltung.execute("drop database if exists aicrm_test")
    await verwaltung.close()


def _klient(nutzer: str) -> AsyncClient:
    """Ein Klient, der sich als bestimmter Olares-Nutzer ausgibt."""
    return AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        headers={"X-Bfl-User": nutzer},
    )


@pytest_asyncio.fixture(loop_scope="session")
async def kai(datenbank):
    async with _klient("kai") as c:
        yield c


@pytest_asyncio.fixture(loop_scope="session")
async def marc(datenbank):
    async with _klient("marc") as c:
        yield c
