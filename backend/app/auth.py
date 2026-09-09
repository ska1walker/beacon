"""Identität aus dem Olares-Header — wir bauen keine eigene Anmeldung.

Der Envoy-Sidecar vor dem Pod hat den Authelia-Token bereits geprüft, wenn
ein Request hier ankommt. Was bleibt, ist die Zuordnung des Olares-Namens
auf unsere interne Kennung.
"""

from uuid import UUID

import asyncpg
from fastapi import Depends, Header, HTTPException, Request
from pydantic import BaseModel

from app import anmeldung as anmeldung_kern
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
    # Die Person, die sich **angemeldet** hat. Gleich `user_id`, solange
    # kein Sitzplatz gewählt ist. Rechte hängen hieran und nicht am Platz:
    # Der Platz ist Zuschreibung, keine Anmeldung — wer ihn wechselt,
    # verliert dadurch weder Rechte noch gewinnt er welche.
    zugang_user_id: UUID | None = None

    @property
    def handelnder(self) -> UUID:
        return self.zugang_user_id or self.user_id


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


# Die vier Stufen, die HubSpot vorgibt und die sich bewährt haben. Die
# Art dahinter entscheidet, ob die Uhr läuft: „wartet auf Kontakt" ist
# die einzige offene Stufe, in der die Frist pausiert.
STANDARD_TICKETSTUFEN = [
    ("Neu", "neu"),
    ("Warten auf Kontakt", "wartet_auf_kontakt"),
    ("Wartet auf uns", "offen"),
    ("Abgeschlossen", "abgeschlossen"),
]

STANDARD_TICKETKATEGORIEN = [
    "Allgemeine Anfrage",
    "Störung",
    "Rechnung",
    "Einrichtung",
    "Erweiterung",
]


async def _seed_ticketpipeline(conn: asyncpg.Connection, org_id: UUID) -> None:
    pipeline_id = await conn.fetchval(
        """
        insert into public.ticket_pipelines (org_id, name, is_default, position)
        values ($1, 'Anliegen', true, 0)
        returning id
        """,
        org_id,
    )
    for position, (name, art) in enumerate(STANDARD_TICKETSTUFEN):
        await conn.execute(
            """
            insert into public.ticket_stages (org_id, pipeline_id, name, art, position)
            values ($1, $2, $3, $4::public.ticket_stufenart, $5)
            """,
            org_id, pipeline_id, name, art, position,
        )
    for position, name in enumerate(STANDARD_TICKETKATEGORIEN):
        await conn.execute(
            "insert into public.ticket_kategorien (org_id, name, position) values ($1,$2,$3) "
            "on conflict do nothing",
            org_id, name, position,
        )


async def _ticketpipelines_bereinigen(conn: asyncpg.Connection, org_id: UUID) -> int:
    """Räumt doppelte Standard-Pipelines weg — die älteste bleibt.

    Bis 0.3.1 prüfte der Start ohne Nutzerkontext, ob eine Ticket-Pipeline
    da ist; unter Zeilensicherheit sah er nie eine und säte bei jedem
    Start eine neue „Anliegen“. Weggeräumt wird nur, was kein Ticket
    trägt: Eine Pipeline mit Tickets ist eine Entscheidung, keine Dublette.
    """
    return await conn.fetchval(
        """
        with behalten as (
            select id from public.ticket_pipelines
             where org_id = $1 and deleted_at is null
             order by created_at, id limit 1
        ), weg as (
            update public.ticket_pipelines p
               set deleted_at = now()
             where p.org_id = $1 and p.deleted_at is null
               and p.id <> (select id from behalten)
               and p.name = (select name from public.ticket_pipelines where id = (select id from behalten))
               and not exists (select 1 from public.tickets t where t.pipeline_id = p.id and t.deleted_at is null)
            returning 1
        )
        select count(*) from weg
        """,
        org_id,
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
            await sicherung.zurueckspielen(conn, daten, org_id, user_id, frisch=True)
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
        await _seed_ticketpipeline(conn, org_id)


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

    Die Abweisung trägt einen Kopf `X-Beacon-Sitzplatz: unbekannt`. Der
    Grund steht in `frontend/lib/api.ts`: Nach einer Neuinstallation ist
    die Datenbank neu, der Platz im Browser aber noch der alte — und dann
    scheitert **jeder** Aufruf, ohne dass ein Mensch den Zusammenhang
    sieht. Am Kopf erkennt die Oberfläche genau diesen Fall und räumt den
    Platz selbst weg. An der Meldung dürfte sie es nicht festmachen; die
    ist Text für Menschen und darf sich ändern.
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
            headers={"X-Beacon-Sitzplatz": "unbekannt"},
        )

    return CurrentUser(
        olares_username=person["olares_username"],
        user_id=person["id"],
        org_id=angemeldet.org_id,
        display_name=person["display_name"],
        login_username=angemeldet.login_username,
        sitzplatz=person["id"] != angemeldet.user_id,
        zugang_user_id=angemeldet.user_id,
    )


async def _aus_sitzung(keks: str) -> CurrentUser | None:
    """Wer steckt hinter diesem Sitzungskeks? Nichts, wenn er nicht (mehr) gilt."""
    async with acquire() as conn:
        sitzung = await anmeldung_kern.sitzung_lesen(conn, keks)
        if sitzung is None:
            return None
        person = await conn.fetchrow(
            "select id, olares_username, display_name from public.users "
            "where id = $1 and deleted_at is null",
            sitzung.user_id,
        )
    if person is None:
        return None
    return CurrentUser(
        olares_username=person["olares_username"],
        user_id=person["id"],
        org_id=sitzung.org_id,
        display_name=person["display_name"],
        login_username=person["olares_username"],
    )


# Sobald einmal ein Passwort existierte, muss nie wieder gefragt werden:
# Der Weg führt nur in eine Richtung. Ein Neustart setzt den Merker zurück
# und fragt einmal nach — das kostet eine Abfrage, keine Sicherheit.
_bewohnt = False


async def _noch_unbewohnt() -> bool:
    """Hat in dieser Datenbank noch **niemand** ein Passwort?

    Das ist die Bedingung der Erstinstallation. Sie ist bewusst nicht „gibt
    es Nutzer?": Der Kopf legt beim ersten Aufruf ja selbst einen an, und
    danach stünde die Tür wieder zu, bevor jemand ein Passwort setzen
    konnte. Erst das erste Passwort schließt sie — endgültig.
    """
    global _bewohnt
    if _bewohnt:
        return False
    async with acquire() as conn:
        vorhanden = await conn.fetchval(
            "select exists(select 1 from public.users where passwort_hash is not null)"
        )
    _bewohnt = bool(vorhanden)
    return not _bewohnt


async def get_current_user(
    request: Request,
    x_bfl_user: str | None = Header(None, alias="X-Bfl-User"),
    x_beacon_sitzplatz: str | None = Header(None, alias="X-Beacon-Sitzplatz"),
) -> CurrentUser:
    """Wer handelt — aus der eigenen Sitzung, sonst aus dem Olares-Kopf.

    Die Reihenfolge ist die Sicherheit: Ein gültiger Sitzungskeks gewinnt
    immer. Der Kopf `X-Bfl-User` gilt **nur** im Modus `olares`, in dem der
    Envoy-Sidecar davorsteht und ihn setzt. Im Modus `eigen` ist der Kopf
    wertlos — sonst genügte `curl -H 'X-Bfl-User: kaivostudio'`, um bei
    offenem Entrance der Eigentümer zu sein.

    Die eine Ausnahme ist die **Erstinstallation**, und sie ist keine
    Bequemlichkeit, sondern die Rettung: Eine frische Datenbank hat keinen
    Nutzer, kein Passwort und keine Einladung. Ohne Ausnahme wäre eine aus
    dem Markt installierte App unbenutzbar — 401 auf alles, und niemand,
    der einen Zugang anlegen könnte. Genau das ist am 8. September einem
    zweiten Nutzer passiert, der Beacon frisch auf seiner eigenen Box
    installierte.

    Solange **niemand** ein Passwort hat, zählt der Kopf deshalb weiter;
    mit dem ersten Passwort ist er endgültig tot. Eine frische Installation
    steht dabei hinter `authLevel: internal`, es kommt also ohnehin nur
    herein, wer an der Box angemeldet ist.
    """
    angemeldet: CurrentUser | None = None

    keks = request.cookies.get(anmeldung_kern.KEKS)
    if keks:
        angemeldet = await _aus_sitzung(keks)
    aus_sitzung = angemeldet is not None

    if angemeldet is None and (settings.anmeldung_modus != "eigen" or await _noch_unbewohnt()):
        name = (x_bfl_user or "").strip() or settings.dev_user.strip()
        if name:
            angemeldet = await _ensure_user_and_org(name)
            angemeldet = angemeldet.model_copy(update={"login_username": name})

    if angemeldet is None:
        raise HTTPException(status_code=401, detail="Nicht angemeldet.")

    gewaehlt = (x_beacon_sitzplatz or "").strip()
    if not gewaehlt:
        return angemeldet

    # Wer sich selbst angemeldet hat, ist bereits er selbst.
    #
    # Der Sitzplatz entstand für den Fall, dass **ein** Olares-Zugang von
    # mehreren Menschen benutzt wird: Er schreibt Arbeit der richtigen
    # Person zu. Mit eigener Anmeldung gibt es nichts mehr zuzuschreiben —
    # und er wäre dann das Gegenteil eines Schutzes: Ein `member` nähme
    # den Platz des Eigentümers ein und erbte über `verwaltet` dessen
    # Rechte. Deshalb greift der Kopf nur beim geteilten Zugang.
    if aus_sitzung:
        return angemeldet

    try:
        sitzplatz_id = UUID(gewaehlt)
    except ValueError:
        raise HTTPException(400, "Der Sitzplatz ist keine gültige Kennung.") from None

    if sitzplatz_id == angemeldet.user_id:
        return angemeldet

    return await _sitzplatz_einnehmen(angemeldet, sitzplatz_id)


# Rollen, die verwalten dürfen. `member` und `viewer` arbeiten im Bestand,
# aber sie ändern keine Schlüssel, laden niemanden ein und spielen keine
# Sicherung zurück — mit offenem Eingang ist das nicht mehr verhandelbar.
VERWALTET = ("owner", "admin")


async def verwaltet(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
    """Abhängigkeit für die Endpunkte mit der größten Sprengkraft.

    Geprüft wird die Rolle der **angemeldeten** Person, nicht die des
    gewählten Sitzplatzes. Sonst verlöre ein Eigentümer seine Rechte,
    sobald er den Platz eines Mitglieds einnimmt — und umgekehrt wäre der
    Platz ein Weg, sich welche zu holen.
    """
    async with acquire() as conn:
        rolle = await conn.fetchval(
            "select role::text from public.user_org_roles where user_id = $1 and org_id = $2",
            user.handelnder, user.org_id,
        )
    if rolle not in VERWALTET:
        raise HTTPException(403, "Dafür fehlt Ihnen die Berechtigung. Fragen Sie den Eigentümer.")
    return user
