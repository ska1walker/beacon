"""Verbindungspool und der Nutzerkontext, den die Zeilensicherheit liest."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from uuid import UUID

import asyncpg

from app.config import settings

_pool: asyncpg.Pool | None = None


async def init_pool() -> asyncpg.Pool:
    global _pool
    if _pool is None:
        _pool = await asyncpg.create_pool(
            host=settings.db_host,
            port=settings.db_port,
            user=settings.db_user,
            password=settings.db_password,
            database=settings.db_name,
            min_size=2,
            max_size=10,
        )
    return _pool


async def close_pool() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


def get_pool() -> asyncpg.Pool:
    if _pool is None:
        raise RuntimeError("Pool nicht initialisiert. init_pool() beim Start aufrufen.")
    return _pool


@asynccontextmanager
async def acquire() -> AsyncIterator[asyncpg.Connection]:
    """Verbindung ohne Nutzerkontext — für Anmeldung und Wartung."""
    pool = get_pool()
    async with pool.acquire() as conn:
        yield conn


@asynccontextmanager
async def acquire_as(user_id: UUID) -> AsyncIterator[asyncpg.Connection]:
    """Verbindung mit gesetztem Nutzerkontext, in einer Transaktion.

    `SET LOCAL` gilt nur innerhalb einer Transaktion — deshalb die
    Transaktion, und nicht nur der Bequemlichkeit halber. Ohne sie fiele
    der Wert nach der ersten Anweisung zurück, und die Policies aus
    0002_rls_policies.sql würden alles ausblenden.

    Der Pool gibt Verbindungen weiter; ein `SET` ohne LOCAL bliebe an der
    Verbindung kleben und der nächste Request liefe unter fremder Kennung.
    Das ist der Fehler, den diese Funktion verhindert.
    """
    pool = get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute("select set_config('app.current_user_id', $1, true)", str(user_id))
            yield conn


@asynccontextmanager
async def acquire_als_quelle(source_id: UUID) -> AsyncIterator[asyncpg.Connection]:
    """Verbindung, die genau eine Webhook-Quelle lesen darf.

    Der Empfangspfad hat keine Olares-Identität — der Absender ist eine
    Maschine. Um die Signatur prüfen zu können, muss das Backend aber die
    Zeile dieser einen Quelle lesen; unter FORCE ROW LEVEL SECURITY geht
    das ohne Kontext nicht.

    Diese Funktion setzt deshalb `app.webhook_source` auf die
    angesprochene Kennung. Die Policy `webhook_sources_selbstauskunft`
    gibt daraufhin genau diese eine Zeile frei — keine zweite, und
    schreiben lässt sich über sie gar nichts.
    """
    pool = get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute(
                "select set_config('app.webhook_source', $1, true)", str(source_id)
            )
            yield conn


@asynccontextmanager
async def acquire_als_link(token: str) -> AsyncIterator[asyncpg.Connection]:
    """Verbindung, die genau einen öffentlichen Link lesen darf.

    Dasselbe Muster wie `acquire_als_quelle`: kein Nutzerkontext, weil
    der Aufrufer ein Empfänger ist, der auf einen Link geklickt hat. Die
    Policy `oeffentliche_links_selbstauskunft` gibt die eine Zeile mit
    diesem Token frei — sonst nichts, und schreiben geht darüber nicht.
    """
    pool = get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute(
                "select set_config('app.oeffentlicher_link', $1, true)", token
            )
            yield conn
