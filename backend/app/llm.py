"""Anbindung an einen OpenAI-kompatiblen Endpunkt.

Kein eigenes Modell im Paket, keine geratene Adresse. Was nicht
eingerichtet ist, wird nicht aufgerufen — und die Oberfläche sagt das,
statt den Nutzer in einen Verbindungsfehler laufen zu lassen.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any
from uuid import UUID

import asyncpg
import httpx

from app import tresor
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
    key = tresor.entschluesseln(row["llm_api_key"] if row else None) or settings.llm_api_key
    model = (row["llm_model"] if row else None) or settings.llm_model
    return LLMConfig(base_url=(base or "").strip(), api_key=(key or "").strip(), model=(model or "").strip())


async def chat(
    cfg: LLMConfig,
    system: str,
    user: str,
    *,
    temperature: float = 0.3,
    max_tokens: int = 900,
    bilder: list[str] | None = None,
) -> str:
    """Eine Frage an das Modell. Mit `bilder` wird sie multimodal.

    Die Bilder gehen als `data:`-URL im OpenAI-Format mit — dasselbe, was
    LiteLLM und vLLM erwarten. Kann das eingestellte Modell keine Bilder,
    antwortet der Endpunkt mit einem Fehler; den zu deuten ist Sache des
    Aufrufers, denn „das Modell sieht nichts" ist eine andere Auskunft
    als „der Endpunkt ist aus".
    """
    if not cfg.eingerichtet:
        raise LLMNichtEingerichtet(
            "Es ist kein Sprachmodell hinterlegt. Adresse und Modellname stehen unter Einstellungen."
        )

    url = cfg.base_url.rstrip("/") + "/chat/completions"
    inhalt: Any = user
    if bilder:
        inhalt = [{"type": "text", "text": user}] + [
            {"type": "image_url", "image_url": {"url": b}} for b in bilder
        ]
    payload = {
        "model": cfg.model or "default",
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": inhalt},
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


async def chat_werkzeuge(
    cfg: LLMConfig,
    nachrichten: list[dict[str, Any]],
    werkzeuge: list[dict[str, Any]],
    *,
    max_tokens: int = 6000,
) -> dict[str, Any]:
    """Ein Gesprächsschritt mit Werkzeugen — gibt die Antwortnachricht zurück.

    OpenAI-Form: `tool_calls` in der Antwort, `tool`-Nachrichten in der
    Frage. Auf der Box geprüft: LiteLLM mit `chat` liefert saubere
    Aufrufe, samt aufgelöstem Datum. `reasoning_content` eines
    Denkmodells wird nicht weitergereicht — es ist Weg, nicht Ergebnis.
    """
    if not cfg.eingerichtet:
        raise LLMNichtEingerichtet(
            "Es ist kein Sprachmodell hinterlegt. Adresse und Modellname stehen unter Einstellungen."
        )
    url = cfg.base_url.rstrip("/") + "/chat/completions"
    payload = {
        "model": cfg.model or "default",
        "messages": nachrichten,
        "tools": werkzeuge,
        "tool_choice": "auto",
        "temperature": 0.0,
        "max_tokens": max_tokens,
    }
    async with httpx.AsyncClient(timeout=settings.llm_timeout_s) as client:
        response = await client.post(url, json=payload, headers=cfg.auth_header)
        response.raise_for_status()
        data = response.json()
    try:
        nachricht = data["choices"][0]["message"]
    except (KeyError, IndexError, TypeError) as exc:
        raise RuntimeError(f"Unerwartete Antwort vom Endpunkt {url}: {data!r}") from exc
    return {
        "role": "assistant",
        "content": nachricht.get("content") or "",
        "tool_calls": nachricht.get("tool_calls") or [],
    }


def json_aus_antwort(text: str) -> Any:
    """Holt das JSON-Objekt aus einer Modellantwort.

    Modelle rahmen ihre Antwort gern mit ```json ein oder schreiben einen
    Satz davor, egal wie deutlich die Aufforderung war. Statt darauf zu
    hoffen, wird der äußerste geschweifte Block gesucht und gelesen. Was
    dann immer noch kein JSON ist, ist ein Fehler und wird als solcher
    gemeldet — nicht stillschweigend zu einem leeren Ergebnis.
    """
    roh = text.strip()
    if roh.startswith("```"):
        roh = roh.split("```")[1]
        if roh.startswith("json"):
            roh = roh[4:]
        roh = roh.strip()

    try:
        return json.loads(roh)
    except json.JSONDecodeError:
        pass

    anfang = roh.find("{")
    ende = roh.rfind("}")
    if anfang != -1 and ende > anfang:
        try:
            return json.loads(roh[anfang : ende + 1])
        except json.JSONDecodeError as exc:
            raise ValueError(f"Die Antwort enthält kein lesbares JSON: {exc}") from exc

    raise ValueError("Die Antwort enthält kein JSON-Objekt.")
