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
