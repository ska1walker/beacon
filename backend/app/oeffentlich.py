"""Der öffentliche Pfad — eine eigene Anwendung, die drei Dinge kann.

Sie läuft auf einem eigenen Port hinter einem eigenen, öffentlichen
Entrance. Alles andere in Beacon bleibt dahinter, wo es ist. Was hier
steht, muss deshalb ohne Anmeldung sicher sein — und das heißt: Es gibt
nichts zu holen. Kein Endpunkt liest Daten heraus; jeder nimmt ein Token
entgegen, tut genau eine Sache und zeigt eine Seite, die für jeden gleich
aussieht.

Drei Regeln, die man an einem Fall erkennt:

- **Ein Abmeldelink funktioniert immer.** Nie „abgelaufen“, nie „schon
  benutzt“. Eine verweigerte Abmeldung ist ein Rechtsverstoß und ein
  Ärgernis — und beides wegen eines Tokens, das der Empfänger nicht
  gewählt hat.
- **Ein Bestätigungslink gilt einmal.** Eine Einwilligung ist ein
  Zeitpunkt, kein Zustand, der sich beliebig oft wiederholen lässt.
- **Ein Klick zählt und leitet weiter.** Und zwar auch dann, wenn das
  Zählen scheitert: Der Empfänger wollte zur Seite, nicht zu uns.
"""

from __future__ import annotations

import contextlib
from contextlib import asynccontextmanager
from datetime import datetime
from html import escape
from uuid import UUID

import orjson
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.db import acquire, acquire_als_link, acquire_as, close_pool, init_pool


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_pool()
    yield
    await close_pool()


app = FastAPI(title="beacon — öffentliche Links", docs_url=None, redoc_url=None, lifespan=lifespan)


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "teil": "oeffentlich"}


# ── Die Seite ───────────────────────────────────────────────────────────

def _seite(titel: str, text: str, *, status: int = 200) -> HTMLResponse:
    """Eine Seite, die für jeden gleich aussieht — nichts ist von außen
    ladbar, nichts verrät etwas über die Anfrage."""
    inhalt = f"""<!doctype html>
<html lang="de"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex"><title>{escape(titel)}</title>
<style>
body{{margin:0;font-family:ui-sans-serif,system-ui,sans-serif;background:#f5f9fc;color:#051729;display:flex;min-height:100vh;align-items:center;justify-content:center}}
main{{max-width:28rem;padding:2rem;background:#fff;border:1px solid #cfdbe7;border-radius:.75rem}}
h1{{font-size:1.25rem;margin:0 0 .75rem}}p{{margin:0;line-height:1.55;color:#335578}}
</style></head><body><main><h1>{escape(titel)}</h1><p>{escape(text)}</p></main></body></html>"""
    return HTMLResponse(inhalt, status_code=status)


UNBEKANNT = _seite(
    "Dieser Link ist nicht mehr gültig",
    "Er wurde bereits benutzt oder ist abgelaufen. Wenn Sie ihn gerade erst erhalten haben, "
    "fordern Sie ihn bitte neu an.",
    status=404,
)


async def _link(token: str):
    if not token or len(token) > 100:
        return None
    async with acquire_als_link(token) as conn:
        return await conn.fetchrow(
            "select id, org_id, art::text as art, contact_id, ziel_url, einmalig, gueltig_bis, "
            "benutzt_am from public.oeffentliche_links where token = $1",
            token,
        )


async def _eigner(org_id: UUID) -> UUID | None:
    async with acquire() as conn:
        return await conn.fetchval(
            "select user_id from public.user_org_roles where org_id = $1 and role = 'owner' limit 1",
            org_id,
        )


def _nachweis(request: Request, token: str) -> str:
    """Was den Beleg ausmacht: wann, von wo, womit."""
    return orjson.dumps({
        "zeitpunkt": datetime.now().astimezone().isoformat(),
        "adresse": request.client.host if request.client else None,
        "weitergeleitet_fuer": request.headers.get("x-forwarded-for"),
        "programm": (request.headers.get("user-agent") or "")[:300],
        "token": token[:8] + "…",
    }).decode()


# ── Bestätigen ──────────────────────────────────────────────────────────

@app.get("/o/bestaetigen/{token}")
async def bestaetigen(token: str, request: Request):
    link = await _link(token)
    if link is None or link["art"] != "bestaetigen":
        return UNBEKANNT
    if link["benutzt_am"] is not None:
        return _seite("Schon bestätigt", "Diese Einwilligung liegt bereits vor. Es ist nichts weiter zu tun.")
    if link["gueltig_bis"] and link["gueltig_bis"] < datetime.now().astimezone():
        return UNBEKANNT

    eigner = await _eigner(link["org_id"])
    if eigner is None or link["contact_id"] is None:
        return UNBEKANNT

    async with acquire_as(eigner) as conn:
        async with conn.transaction():
            await conn.execute(
                """
                update public.contacts
                   set marketing_einwilligung = 'bestaetigt',
                       einwilligung_am = now(),
                       einwilligung_quelle = coalesce(einwilligung_quelle, 'double-opt-in'),
                       einwilligung_nachweis = $1::jsonb,
                       abgemeldet_am = null
                 where id = $2 and deleted_at is null
                """,
                _nachweis(request, token), link["contact_id"],
            )
            await conn.execute(
                "update public.oeffentliche_links set benutzt_am = now(), "
                "benutzt_anzahl = benutzt_anzahl + 1 where id = $1",
                link["id"],
            )
    return _seite("Vielen Dank", "Ihre Einwilligung ist bestätigt. Sie können dieses Fenster schließen.")


# ── Abmelden ────────────────────────────────────────────────────────────

@app.get("/o/abmelden/{token}")
async def abmelden(token: str, request: Request):
    link = await _link(token)
    if link is None or link["art"] != "abmelden":
        return UNBEKANNT
    eigner = await _eigner(link["org_id"])
    if eigner is None or link["contact_id"] is None:
        return UNBEKANNT

    async with acquire_as(eigner) as conn:
        async with conn.transaction():
            await conn.execute(
                """
                update public.contacts
                   set marketing_einwilligung = 'abgemeldet',
                       abgemeldet_am = coalesce(abgemeldet_am, now())
                 where id = $1 and deleted_at is null
                """,
                link["contact_id"],
            )
            await conn.execute(
                "update public.oeffentliche_links set benutzt_am = now(), "
                "benutzt_anzahl = benutzt_anzahl + 1 where id = $1",
                link["id"],
            )
    return _seite("Abgemeldet", "Sie erhalten von uns keine weiteren Marketing-Mails. Das gilt sofort.")


# ── Klick ───────────────────────────────────────────────────────────────

@app.get("/o/k/{token}")
async def klick(token: str):
    link = await _link(token)
    if link is None or link["art"] != "klick" or not link["ziel_url"]:
        return UNBEKANNT

    # Zählen darf scheitern — weiterleiten nicht.
    with contextlib.suppress(Exception):
        eigner = await _eigner(link["org_id"])
        if eigner:
            async with acquire_as(eigner) as conn:
                await conn.execute(
                    "update public.oeffentliche_links set benutzt_am = now(), "
                    "benutzt_anzahl = benutzt_anzahl + 1 where id = $1",
                    link["id"],
                )
    return RedirectResponse(link["ziel_url"], status_code=302)
