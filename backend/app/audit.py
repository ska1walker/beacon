"""Protokoll jeder Datenänderung — Kernprinzip, kein Zusatz."""

from typing import Any
from uuid import UUID

import asyncpg
import orjson


async def log(
    conn: asyncpg.Connection,
    *,
    org_id: UUID,
    actor_id: UUID | None,
    action: str,
    entity: str,
    entity_id: UUID | None,
    diff: dict[str, Any] | None = None,
) -> None:
    await conn.execute(
        """
        insert into public.audit_log (org_id, actor_id, action, entity, entity_id, diff)
        values ($1, $2, $3, $4, $5, $6::jsonb)
        """,
        org_id,
        actor_id,
        action,
        entity,
        entity_id,
        orjson.dumps(diff or {}).decode(),
    )
