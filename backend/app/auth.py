"""Identität aus dem Olares-Header — wir bauen keine eigene Anmeldung.

Der Envoy-Sidecar vor dem Pod hat den Authelia-Token bereits geprüft, wenn
ein Request hier ankommt. Was bleibt, ist die Zuordnung des Olares-Namens
auf unsere interne Kennung.
"""

from uuid import UUID

import asyncpg
from fastapi import Header, HTTPException
from pydantic import BaseModel

from app import sicherung
from app.config import settings
from app.db import acquire, acquire_as

# Die Stufen, mit denen ein Vertrieb anfängt. Sie stehen hier und nicht in
# einer Migration, weil Organisationen zur Laufzeit entstehen — eine
# Migration läuft genau einmal und hätte für die zweite Organisation nichts
# angelegt. Wer die Stufen ändert, ändert sie danach in der Oberfläche.
STANDARD_STUFEN: list[tuple[str, str, float]] = [
    ("Erstkontakt", "open", 0.05),
    ("Qualifiziert", "open", 0.20),
    ("Vorführung", "open", 0.40),
    ("Angebot", "open", 0.60),
    ("Verhandlung", "open", 0.80),
    ("Gewonnen", "won", 1.00),
    ("Verloren", "lost", 0.00),
]


class CurrentUser(BaseModel):
    olares_username: str
    user_id: UUID
    org_id: UUID
    display_name: str | None = None


async def _seed_pipeline(conn: asyncpg.Connection, org_id: UUID) -> None:
    pipeline_id = await conn.fetchval(
        """
        insert into public.pipelines (org_id, name, is_default, position)
        values ($1, 'Vertrieb', true, 0)
        returning id
        """,
        org_id,
    )
    for position, (name, kind, probability) in enumerate(STANDARD_STUFEN):
        await conn.execute(
            """
            insert into public.pipeline_stages
              (org_id, pipeline_id, name, kind, probability, position)
            values ($1, $2, $3, $4::public.stage_kind, $5, $6)
            """,
            org_id,
            pipeline_id,
            name,
            kind,
            probability,
            position,
        )


async def _einrichten(conn: asyncpg.Connection, org_id: UUID, user_id: UUID) -> None:
    """Eine frisch angelegte Organisation füllen.

    Der Normalfall ist die leere Pipeline. Der andere Fall ist der teure:
    Nach einer Deinstallation legt Olares die Datenbank neu an, samt neuer
    Org-Kennung — der gesamte Vertrieb wäre weg. Liegt neben den Daten ein
    Abzug, wird er stattdessen zurückgespielt. Er überlebt, weil
    /app/data unter permission.appData steht und die Datenbank nicht.

    Zurückgespielt wird aber **nur in die erste Organisation der Box**.
    Ohne diese Bedingung bekäme der zweite Mensch, der sich anmeldet, den
    Bestand des ersten in seine eigene Organisation gelegt — ein Leck
    zwischen Mandanten, und zwar eines, das wie eine Rettung aussieht.
    Eine zweite Organisation ist kein Wiederanlauf, sondern ein zweiter
    Nutzer, und der fängt leer an.
    """
    orgs = await conn.fetchval("select count(*) from public.orgs where deleted_at is null")
    erster_anlauf = orgs == 1

    letzter = next(iter(sicherung.staende()), None) if erster_anlauf else None
    if letzter is not None:
        try:
            daten = sicherung.abzug_lesen(letzter["name"])
            await sicherung.zurueckspielen(conn, daten, org_id, user_id)
        except Exception as exc:
            # Ein kaputter Abzug darf die Anmeldung nicht verhindern. Dann
            # gibt es eben eine leere Pipeline, und der Stand liegt weiter
            # da — von Hand einlesbar.
            print(f"Sicherung {letzter['name']} nicht lesbar: {exc}", flush=True)

    vorhanden = await conn.fetchval(
        "select count(*) from public.pipelines where org_id = $1 and deleted_at is null", org_id
    )
    if not vorhanden:
        await _seed_pipeline(conn, org_id)


async def _ensure_user_and_org(olares_username: str) -> CurrentUser:
    """Nutzer und Organisation anlegen, falls es sie noch nicht gibt.

    Auf der Box legt das Onboarding beides an. Lokal — und beim ersten
    Aufruf einer neuen Kennung — passiert es hier, damit der erste Request
    nicht ins Leere läuft.
    """
    async with acquire() as conn:
        async with conn.transaction():
            row = await conn.fetchrow(
                """
                insert into public.users (olares_username, display_name)
                values ($1, $1)
                on conflict (olares_username) do update set last_seen_at = now()
                returning id, display_name
                """,
                olares_username,
            )
            user_id: UUID = row["id"]

            org = await conn.fetchrow(
                """
                select o.id
                from public.orgs o
                join public.user_org_roles r on r.org_id = o.id
                where r.user_id = $1 and o.deleted_at is null
                limit 1
                """,
                user_id,
            )

            neu_angelegt = org is None
            if org is None:
                org = await conn.fetchrow(
                    """
                    insert into public.orgs (name, slug)
                    values ($1, $2)
                    returning id
                    """,
                    f"Organisation {olares_username}",
                    f"org-{olares_username}",
                )
                await conn.execute(
                    """
                    insert into public.user_org_roles (user_id, org_id, role)
                    values ($1, $2, 'owner')
                    on conflict (user_id, org_id) do nothing
                    """,
                    user_id,
                    org["id"],
                )

    # Einstellungen, Bestand und Pipeline entstehen erst hier — mit
    # gesetztem Nutzerkontext. Die Tabellen stehen unter FORCE ROW LEVEL
    # SECURITY; ohne Kontext würde die Zeilensicherheit die Anlage
    # abweisen. Der Block oben kann ihn noch nicht setzen: Die Rolle, aus
    # der er sich ableitet, entsteht dort ja gerade erst.
    if neu_angelegt:
        async with acquire_as(user_id) as conn:
            await conn.execute(
                "insert into public.org_settings (org_id) values ($1) on conflict do nothing",
                org["id"],
            )
            await _einrichten(conn, org["id"], user_id)

    return CurrentUser(
        olares_username=olares_username,
        user_id=user_id,
        org_id=org["id"],
        display_name=row["display_name"],
    )


async def get_current_user(
    x_bfl_user: str | None = Header(None, alias="X-Bfl-User"),
) -> CurrentUser:
    name = (x_bfl_user or "").strip() or settings.dev_user.strip()
    if not name:
        # Auf der Box kommt hier nie etwas an: Envoy setzt den Header oder
        # lässt den Request gar nicht durch. Fehlt er trotzdem, ist etwas
        # an der Kette kaputt — und dann ist Verweigern richtig.
        raise HTTPException(status_code=401, detail="Keine Identität im Request (X-Bfl-User fehlt)")
    return await _ensure_user_and_org(name)
