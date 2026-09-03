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
# Der Produktkatalog aus claude/Produkte.md. Preise netto in Cent.
#
# Der Servicetag steht ohne Preis: In der Produktbeschreibung ist keiner
# genannt, und ein geratener Tagessatz landete sonst in einem Angebot beim
# Kunden. Wer ihn einträgt, trägt ihn im Katalog ein.
STANDARD_PRODUKTE: list[dict[str, object]] = [
    {
        "key": "assistent",
        "name": "Assistent",
        "description": "Ein Werkzeug. Bis 5 gleichzeitige Nutzer, 500 Dokumente, Open WebUI.",
        "kind": "system",
        "list_price_cents": 990000,
        "default_service_days": 6,
    },
    {
        "key": "analyst",
        "name": "Analyst",
        "description": "Ein Kollege. Eine Sitzung, 2.500 Dokumente, Zugriff auf Dokumente und Netz.",
        "kind": "system",
        "list_price_cents": 1450000,
        "default_service_days": 8,
    },
    {
        "key": "experte",
        "name": "Experte",
        "description": "Ein Prozess. Läuft selbstständig, Zugriff auf Anwendungen, Datenbanken, Verzeichnisse.",
        "kind": "system",
        "list_price_cents": 1450000,
        "default_service_days": 12,
    },
    {
        "key": "servicetag",
        "name": "Zusätzlicher Servicetag",
        "description": "Einführung, Anpassung, Schulung — über die enthaltenen Tage hinaus.",
        "kind": "service",
        "list_price_cents": 0,
        "default_service_days": None,
    },
]

# Die Gründe, aus denen ein Geschäft bei AImighty verloren geht. Sie
# stehen hier als Startpunkt, nicht als Wahrheit — der Vertrieb ergänzt
# sie, sobald er einen neuen kennenlernt.
STANDARD_VERLUSTGRUENDE: list[str] = [
    "Preis",
    "Kein Budget",
    "Zeitpunkt passt nicht",
    "Widerstand aus der IT",
    "Cloud-Lösung gewählt",
    "Kein Bedarf erkannt",
    "Entscheider nicht erreicht",
    "Projekt verschoben",
    "Kontakt abgebrochen",
]

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
    """Wer handelt — und über welchen Zugang.

    Bei einem geteilten Olares-Konto sind das zwei verschiedene Dinge:
    `user_id` ist die Person, der die Arbeit zugeschrieben wird,
    `login_username` der Zugang, über den sie hereinkam. Das Protokoll
    hält beides fest, sonst sähe es aus, als hätte die Person sich selbst
    angemeldet.
    """

    olares_username: str
    user_id: UUID
    org_id: UUID
    display_name: str | None = None
    # Der Olares-Name aus X-Bfl-User. Gleich `olares_username`, solange
    # kein Sitzplatz gewählt ist.
    login_username: str = ""
    sitzplatz: bool = False


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


async def _seed_verlustgruende(conn: asyncpg.Connection, org_id: UUID) -> None:
    for position, grund in enumerate(STANDARD_VERLUSTGRUENDE):
        await conn.execute(
            "insert into public.loss_reasons (org_id, name, position) values ($1,$2,$3) "
            "on conflict (org_id, name) do nothing",
            org_id,
            grund,
            position,
        )


async def _seed_produkte(conn: asyncpg.Connection, org_id: UUID) -> None:
    for position, produkt in enumerate(STANDARD_PRODUKTE):
        await conn.execute(
            """
            insert into public.products
              (org_id, key, name, description, kind, list_price_cents,
               default_service_days, position)
            values ($1,$2,$3,$4,$5::public.product_kind,$6,$7,$8)
            on conflict (org_id, key) do nothing
            """,
            org_id,
            produkt["key"],
            produkt["name"],
            produkt["description"],
            produkt["kind"],
            produkt["list_price_cents"],
            produkt["default_service_days"],
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

    katalog = await conn.fetchval(
        "select count(*) from public.products where org_id = $1", org_id
    )
    if not katalog:
        await _seed_produkte(conn, org_id)

    gruende = await conn.fetchval(
        "select count(*) from public.loss_reasons where org_id = $1", org_id
    )
    if not gruende:
        await _seed_verlustgruende(conn, org_id)


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


async def _sitzplatz_einnehmen(angemeldet: CurrentUser, sitzplatz_id: UUID) -> CurrentUser:
    """Wechselt die handelnde Person innerhalb derselben Organisation.

    Die Prüfung ist die eigentliche Substanz dieser Funktion: Ein
    Sitzplatz greift **nur**, wenn er Mitglied derselben Organisation ist
    wie der angemeldete Olares-Nutzer. Ohne diese Bedingung wäre der
    Sitzplatz ein Weg in fremde Mandanten — und damit die Umgehung von
    allem, was die Zeilensicherheit schützt.

    Ein unbekannter oder fremder Sitzplatz wird abgewiesen und nicht
    stillschweigend ignoriert: Sonst schriebe die Oberfläche Arbeit der
    falschen Person zu und niemand würde es merken.
    """
    async with acquire() as conn:
        person = await conn.fetchrow(
            """
            select u.id, u.display_name, u.olares_username, u.zugang
            from public.users u
            join public.user_org_roles r on r.user_id = u.id
            where u.id = $1 and r.org_id = $2 and u.deleted_at is null
            """,
            sitzplatz_id,
            angemeldet.org_id,
        )

    if person is None:
        raise HTTPException(
            status_code=403,
            detail="Dieser Sitzplatz gehört nicht zu Ihrer Organisation.",
        )

    return CurrentUser(
        olares_username=person["olares_username"],
        user_id=person["id"],
        org_id=angemeldet.org_id,
        display_name=person["display_name"],
        login_username=angemeldet.login_username,
        sitzplatz=person["id"] != angemeldet.user_id,
    )


async def get_current_user(
    x_bfl_user: str | None = Header(None, alias="X-Bfl-User"),
    x_aicrm_sitzplatz: str | None = Header(None, alias="X-Aicrm-Sitzplatz"),
) -> CurrentUser:
    name = (x_bfl_user or "").strip() or settings.dev_user.strip()
    if not name:
        # Auf der Box kommt hier nie etwas an: Envoy setzt den Header oder
        # lässt den Request gar nicht durch. Fehlt er trotzdem, ist etwas
        # an der Kette kaputt — und dann ist Verweigern richtig.
        raise HTTPException(status_code=401, detail="Keine Identität im Request (X-Bfl-User fehlt)")

    angemeldet = await _ensure_user_and_org(name)
    angemeldet = angemeldet.model_copy(update={"login_username": name})

    gewaehlt = (x_aicrm_sitzplatz or "").strip()
    if not gewaehlt:
        return angemeldet

    try:
        sitzplatz_id = UUID(gewaehlt)
    except ValueError:
        raise HTTPException(400, "Der Sitzplatz ist keine gültige Kennung.") from None

    if sitzplatz_id == angemeldet.user_id:
        return angemeldet

    return await _sitzplatz_einnehmen(angemeldet, sitzplatz_id)
