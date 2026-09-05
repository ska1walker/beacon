"""Öffentliche Links anlegen — Bestätigen, Abmelden, Klick.

Die Gegenseite (`app/oeffentlich.py`) löst sie ein. Hier entstehen sie:
eine Zeile, ein zufälliges Token, eine Adresse, die in eine Mail gehört.

Das Token hat 32 zufällige Bytes. Das ist keine Vorsicht, sondern die
einzige Sicherung dieses Pfades — er hat keine Anmeldung, und er soll
keine haben.
"""

from __future__ import annotations

import secrets
from datetime import datetime, timedelta
from uuid import UUID

ART = ("bestaetigen", "abmelden", "klick")

# Ein Bestätigungslink, der nach einer Woche noch gilt, gehört zu einer
# Anfrage, die niemand mehr im Kopf hat.
BESTAETIGEN_GUELTIG = timedelta(days=7)


def neues_token() -> str:
    return secrets.token_urlsafe(32)


async def anlegen(
    conn,
    org_id: UUID,
    art: str,
    *,
    contact_id: UUID | None = None,
    ziel_url: str | None = None,
    payload: dict | None = None,
) -> str:
    """Legt den Link an und gibt sein Token zurück."""
    if art not in ART:
        raise ValueError(f"Unbekannte Linkart: {art}")
    if art == "klick" and not ziel_url:
        raise ValueError("Ein Klick-Link braucht ein Ziel.")

    import orjson

    einmalig = art == "bestaetigen"
    gueltig_bis = (datetime.now().astimezone() + BESTAETIGEN_GUELTIG) if einmalig else None
    token = neues_token()
    await conn.execute(
        """
        insert into public.oeffentliche_links
          (org_id, token, art, contact_id, ziel_url, einmalig, gueltig_bis, payload)
        values ($1,$2,$3::public.link_art,$4,$5,$6,$7,$8::jsonb)
        """,
        org_id, token, art, contact_id, ziel_url, einmalig, gueltig_bis,
        orjson.dumps(payload or {}).decode(),
    )
    return token


def adresse(basis: str, art: str, token: str) -> str:
    """Die Adresse, die in die Mail gehört. `basis` ist der öffentliche
    Entrance — ohne abschließenden Schrägstrich."""
    pfad = {"bestaetigen": "bestaetigen", "abmelden": "abmelden", "klick": "k"}[art]
    return f"{basis.rstrip('/')}/o/{pfad}/{token}"
