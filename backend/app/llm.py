"""Anbindung an einen OpenAI-kompatiblen Endpunkt.

Kein eigenes Modell im Paket, keine geratene Adresse. Was nicht
eingerichtet ist, wird nicht aufgerufen — und die Oberfläche sagt das,
statt den Nutzer in einen Verbindungsfehler laufen zu lassen.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

import asyncpg
import httpx

from app.config import settings


class LLMNichtEingerichtet(RuntimeError):  # noqa: N818
    """Kein Endpunkt hinterlegt — kein Grund für einen Netzwerkversuch.

    Ohne Suffix „Error": Die Fachbegriffe in diesem Projekt sind deutsch,
    und „LLMNichtEingerichtetError" wäre ein Wort aus zwei Sprachen.
    """


@dataclass(frozen=True)
class LLMConfig:
    base_url: str
    api_key: str
    model: str

    @property
    def eingerichtet(self) -> bool:
        return bool(self.base_url.strip())

    @property
    def auth_header(self) -> dict[str, str]:
        # `Bearer ` mit leerem Wert ist kein gültiger Kopfwert — httpx
        # lehnt ihn ab, bevor überhaupt eine Verbindung zustande kommt.
        # Lokale Endpunkte verlangen ohnehin keinen Schlüssel.
        key = self.api_key.strip()
        return {"Authorization": f"Bearer {key}"} if key else {}


async def load_llm_config(conn: asyncpg.Connection, org_id: UUID) -> LLMConfig:
    """Werte der Organisation, sonst die aus der Umgebung.

    Ein leerer Wert in der Datenbank heißt „nicht gesetzt" und fällt auf
    die Umgebung zurück; er wird nie als leerer Wert weitergereicht.
    """
    row = await conn.fetchrow(
        "select llm_base_url, llm_api_key, llm_model from public.org_settings where org_id = $1",
        org_id,
    )
    base = (row["llm_base_url"] if row else None) or settings.llm_base_url
    key = (row["llm_api_key"] if row else None) or settings.llm_api_key
    model = (row["llm_model"] if row else None) or settings.llm_model
    return LLMConfig(base_url=(base or "").strip(), api_key=(key or "").strip(), model=(model or "").strip())


async def chat(
    cfg: LLMConfig,
    system: str,
    user: str,
    *,
    temperature: float = 0.3,
    max_tokens: int = 900,
) -> str:
    if not cfg.eingerichtet:
        raise LLMNichtEingerichtet(
            "Es ist kein Sprachmodell hinterlegt. Adresse und Modellname stehen unter Einstellungen."
        )

    url = cfg.base_url.rstrip("/") + "/chat/completions"
    payload = {
        "model": cfg.model or "default",
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": temperature,
        "max_tokens": max_tokens,
    }

    async with httpx.AsyncClient(timeout=settings.llm_timeout_s) as client:
        response = await client.post(url, json=payload, headers=cfg.auth_header)
        response.raise_for_status()
        data = response.json()

    try:
        return str(data["choices"][0]["message"]["content"]).strip()
    except (KeyError, IndexError, TypeError) as exc:
        # Ein Endpunkt, der etwas anderes zurückgibt, ist kein
        # OpenAI-kompatibler Endpunkt. Das gehört gesagt, nicht geraten.
        raise RuntimeError(f"Unerwartete Antwort vom Endpunkt {url}: {data!r}") from exc
