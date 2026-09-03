"""Protokoll jeder Datenänderung — Kernprinzip, kein Zusatz."""

from typing import TYPE_CHECKING, Any
from uuid import UUID

import asyncpg
import orjson

if TYPE_CHECKING:
    from app.auth import CurrentUser


async def log(
    conn: asyncpg.Connection,
    *,
    org_id: UUID,
    actor_id: UUID | None,
    action: str,
    entity: str,
    entity_id: UUID | None,
    diff: dict[str, Any] | None = None,
    actor_login: str | None = None,
) -> None:
    """Schreibt einen Eintrag.

    `actor_login` ist der Zugang, über den gehandelt wurde. Bei einem
    geteilten Olares-Konto ist er nicht dieselbe Angabe wie `actor_id`:
    Die Kennung sagt, wem die Arbeit zugeschrieben wird, der Zugang, wer
    tatsächlich an der Tastatur saß. Ohne beides sähe das Protokoll aus,
    als hätte sich jede Person selbst angemeldet.
    """
    await conn.execute(
        """
        insert into public.audit_log
          (org_id, actor_id, action, entity, entity_id, diff, actor_login)
        values ($1, $2, $3, $4, $5, $6::jsonb, $7)
        """,
        org_id,
        actor_id,
        action,
        entity,
        entity_id,
        orjson.dumps(diff or {}).decode(),
        actor_login,
    )


async def log_fuer(
    conn: asyncpg.Connection,
    user: "CurrentUser",
    *,
    action: str,
    entity: str,
    entity_id: UUID | None,
    diff: dict[str, Any] | None = None,
) -> None:
    """Wie `log`, nur mit der handelnden Person als einem Argument.

    Die bevorzugte Form: Sie kann Person und Zugang nicht auseinander
    geraten lassen, weil beide aus derselben Quelle kommen.
    """
    await log(
        conn,
        org_id=user.org_id,
        actor_id=user.user_id,
        action=action,
        entity=entity,
        entity_id=entity_id,
        diff=diff,
        actor_login=user.login_username or user.olares_username,
    )
