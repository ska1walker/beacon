"""Anmelden, abmelden, Passwort setzen — der einzige Weg herein.

Der Keks trägt alles und ist für JavaScript unsichtbar (`HttpOnly`).
Damit kann kein eingeschleustes Skript die Sitzung stehlen, und es gibt
kein Token im `localStorage`, das ein Werbeblocker-Add-on mitlesen könnte.

`SameSite=Lax` ist der CSRF-Schutz: Ein Formular auf einer fremden Seite
darf den Keks bei einem POST nicht mitschicken. Zusätzlich wird der
`Origin` geprüft, wo er ankommt — Gürtel und Hosenträger, beides billig.
"""

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response
from pydantic import BaseModel, Field

from app import anmeldung as kern
from app import zuruecksetzen
from app.auth import CurrentUser, get_current_user
from app.config import settings
from app.db import acquire, acquire_as

router = APIRouter(prefix="/api", tags=["anmeldung"])


class Zugangsdaten(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    passwort: str = Field(min_length=1, max_length=200)


class Passwortwechsel(BaseModel):
    alt: str = Field(min_length=1, max_length=200)
    neu: str = Field(min_length=1, max_length=200)


class Einloesung(BaseModel):
    passwort: str = Field(min_length=1, max_length=200)


class Vergessen(BaseModel):
    name: str = Field(min_length=1, max_length=200)


class Ruecksetzung(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    code: str = Field(min_length=1, max_length=100)
    passwort: str = Field(min_length=1, max_length=200)


class Ablageort(BaseModel):
    """Wo die Datei liegt. Kein Geheimnis — der Weg dorthin ist eines."""

    # Der Klickweg in der Dateien-App. `pfad` war früher der Pfad im
    # Container, und den gibt es in der Dateien-App nicht.
    ordner: str
    minuten: int


class Lage(BaseModel):
    angemeldet: bool
    name: str | None = None
    modus: str


def _adresse(request: Request) -> str:
    """Die Adresse des Anfragenden — für die Bremse, nicht für Rechte.

    Hinter dem Envoy und dem Next-Proxy steht die echte Adresse in
    `X-Forwarded-For`. Der Wert ist fälschbar; für eine Bremse ist das
    hinnehmbar, für eine Entscheidung über Zugang wäre es das nicht.
    """
    weiter = request.headers.get("x-forwarded-for", "")
    if weiter:
        return weiter.split(",")[0].strip()[:100]
    return request.client.host if request.client else "unbekannt"


def _herkunft_pruefen(request: Request) -> None:
    """Weist einen schreibenden Aufruf von einer fremden Seite ab.

    `SameSite=Lax` hält das meiste schon vom Browser fern; diese Prüfung
    fängt den Rest und kostet nichts. Fehlt der Kopf ganz (etwa bei einem
    Aufruf ohne Browser), wird nicht abgewiesen — sonst wäre jedes Skript
    ausgesperrt, das legitim mit Zugangsdaten arbeitet.
    """
    herkunft = request.headers.get("origin")
    if not herkunft:
        return
    # Der Browser spricht mit dem Frontend, das Frontend leitet weiter.
    # Im `Host` steht deshalb der interne Dienst (`localhost:8010`, auf der
    # Box der Service-Name), nicht die Adresse, die der Mensch sieht — der
    # Vergleich gegen `Host` allein wies jede echte Anmeldung ab. Was der
    # Browser sah, steht in `X-Forwarded-Host`; den setzt der Proxy.
    ziele = {
        request.headers.get("x-forwarded-host", ""),
        request.headers.get("host", ""),
    }
    ziele.discard("")
    if ziele and not any(herkunft.endswith(f"//{z}") for z in ziele):
        raise HTTPException(403, "Diese Anfrage kommt von einer fremden Seite.")


def _ueber_tls(request: Request) -> bool:
    """Kam diese Anfrage verschlüsselt herein?

    Das entscheidet über `Secure` — und zwar an der **Verbindung**, nicht
    am Modus. Am Modus festgemacht trüge der Keks auf der Box im Betrieb
    `olares` kein `Secure`, obwohl dort alles über TLS läuft; und lokal
    ohne TLS verwürfe der Browser einen `Secure`-Keks stillschweigend, was
    wie ein kaputtes Anmelden aussieht. Hinter dem Proxy steht das Schema
    des Browsers in `X-Forwarded-Proto`.
    """
    weiter = request.headers.get("x-forwarded-proto", "")
    if weiter:
        return weiter.split(",")[0].strip() == "https"
    return request.url.scheme == "https"


def _keks_setzen(request: Request, antwort: Response, token: str) -> None:
    antwort.set_cookie(
        kern.KEKS,
        token,
        max_age=settings.sitzung_tage * 86400,
        httponly=True,
        secure=_ueber_tls(request),
        samesite="lax",
        path="/",
    )


@router.get("/anmeldung/lage", response_model=Lage)
async def lage(request: Request) -> Lage:
    """Sagt der Oberfläche, ob jemand angemeldet ist. Verrät sonst nichts."""
    keks = request.cookies.get(kern.KEKS)
    if not keks:
        return Lage(angemeldet=False, modus=settings.anmeldung_modus)
    async with acquire() as conn:
        sitzung = await kern.sitzung_lesen(conn, keks)
        if sitzung is None:
            return Lage(angemeldet=False, modus=settings.anmeldung_modus)
        name = await conn.fetchval("select display_name from public.users where id = $1", sitzung.user_id)
    return Lage(angemeldet=True, name=name, modus=settings.anmeldung_modus)


@router.post("/anmeldung", response_model=Lage)
async def anmelden(
    daten: Zugangsdaten,
    request: Request,
    antwort: Response,
    user_agent: Annotated[str | None, Header()] = None,
) -> Lage:
    _herkunft_pruefen(request)
    async with acquire() as conn:
        try:
            token = await kern.anmelden(conn, daten.name, daten.passwort, user_agent or "", _adresse(request))
        except kern.ZuVieleVersuche as exc:
            raise HTTPException(
                429,
                "Zu viele Versuche. Bitte warten Sie eine Viertelstunde.",
                headers={"Retry-After": str(exc.sekunden)},
            ) from exc
        except kern.Anmeldefehler as exc:
            # Immer dieselbe Meldung: Ob es den Namen gibt, geht niemanden an.
            raise HTTPException(401, "Name oder Passwort stimmt nicht.") from exc
    _keks_setzen(request, antwort, token)
    return Lage(angemeldet=True, name=daten.name, modus=settings.anmeldung_modus)


@router.post("/abmeldung", status_code=204)
async def abmelden(request: Request, antwort: Response) -> Response:
    """Beendet die Sitzung **auf dem Server**. Ein bloß gelöschter Keks
    wäre kein Abmelden: Das Token bliebe gültig, bis es abläuft."""
    keks = request.cookies.get(kern.KEKS)
    if keks:
        async with acquire() as conn:
            await kern.sitzung_beenden(conn, keks)
    antwort.delete_cookie(kern.KEKS, path="/")
    return Response(status_code=204, headers=dict(antwort.headers))


@router.post("/anmeldung/passwort", status_code=204)
async def passwort_aendern(
    daten: Passwortwechsel,
    request: Request,
    user: CurrentUser = Depends(get_current_user),
) -> Response:
    """Das eigene Passwort ändern. Das alte wird verlangt — sonst genügte
    ein fremder, offener Browser, um jemanden auszusperren."""
    _herkunft_pruefen(request)
    try:
        kern.passwort_pruefen(daten.neu)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc

    # Mit Nutzerkontext: Die Zeilensicherheit auf `sitzungen` gibt über
    # `sitzungen_selbst` nur die eigenen frei — und genau die sollen
    # unten beendet werden.
    async with acquire_as(user.user_id) as conn:
        hash_wert = await conn.fetchval("select passwort_hash from public.users where id = $1", user.user_id)
        # Wer noch keines hat, setzt sein erstes — dann gibt es nichts zu prüfen.
        if hash_wert and not kern.passwort_stimmt(hash_wert, daten.alt):
            raise HTTPException(403, "Das bisherige Passwort stimmt nicht.")
        await conn.execute(
            "update public.users set passwort_hash = $1, passwort_am = now() where id = $2",
            kern.hash_passwort(daten.neu), user.user_id,
        )
        # Alle anderen Sitzungen beenden: Ein Passwortwechsel ist oft die
        # Reaktion auf einen Verdacht, und dann muss er alle Geräte treffen.
        keks = request.cookies.get(kern.KEKS)
        await conn.execute(
            "update public.sitzungen set beendet_am = now() "
            "where user_id = $1 and beendet_am is null and token_hash <> $2",
            user.user_id, kern.token_hash(keks) if keks else "",
        )
    return Response(status_code=204)


@router.post("/anmeldung/vergessen", response_model=Ablageort)
async def vergessen(
    daten: Vergessen, request: Request
) -> Ablageort:
    """Legt einen Rücksetzcode in den Datenordner der App.

    Die Antwort ist **immer dieselbe**, ob es den Zugang gibt oder nicht.
    Sonst wäre dieser Endpunkt das Namensverzeichnis, das die
    Anmeldemaske selbst sorgfältig verschweigt.

    Geschrieben wird nur für einen Zugang, der schon ein Passwort hat: Wer
    noch keines gesetzt hat, kommt auf einer frischen Box ohnehin über die
    Box-Sitzung herein und braucht diesen Weg nicht.
    """
    _herkunft_pruefen(request)
    kennungen = [f"name:{daten.name.strip().lower()}", f"ip:{_adresse(request)}"]
    async with acquire() as conn:
        try:
            await kern.bremse_pruefen(conn, kennungen)
        except kern.ZuVieleVersuche as exc:
            raise HTTPException(
                429,
                "Zu viele Versuche. Bitte warten Sie eine Viertelstunde.",
                headers={"Retry-After": str(exc.sekunden)},
            ) from exc
        gibt_es = await conn.fetchval(
            "select exists(select 1 from public.users "
            "where lower(olares_username) = lower($1) and deleted_at is null "
            "and passwort_hash is not null)",
            daten.name.strip(),
        )
        # Der Versuch zählt in jedem Fall. Zählte er nur beim Treffer,
        # ließe sich an der Bremse ablesen, welche Namen es gibt.
        await kern.versuch_merken(conn, kennungen)
    if gibt_es:
        zuruecksetzen.anfordern(daten.name.strip())
    return Ablageort(
        ordner=zuruecksetzen.wo_liegt_die_datei(), minuten=zuruecksetzen.GUELTIG_MINUTEN
    )


@router.post("/anmeldung/zuruecksetzen", response_model=Lage)
async def zuruecksetzen_einloesen(
    daten: Ruecksetzung,
    request: Request,
    antwort: Response,
    user_agent: Annotated[str | None, Header()] = None,
) -> Lage:
    """Setzt mit dem Code aus der Datei ein neues Passwort.

    Danach ist die Datei weg und **jede** offene Sitzung beendet: Wer sein
    Passwort zurücksetzt, tut das oft, weil etwas nicht stimmt.
    """
    _herkunft_pruefen(request)
    try:
        kern.passwort_pruefen(daten.passwort)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc

    kennungen = [f"name:{daten.name.strip().lower()}", f"ip:{_adresse(request)}"]
    async with acquire() as conn:
        try:
            await kern.bremse_pruefen(conn, kennungen)
        except kern.ZuVieleVersuche as exc:
            raise HTTPException(
                429,
                "Zu viele Versuche. Bitte warten Sie eine Viertelstunde.",
                headers={"Retry-After": str(exc.sekunden)},
            ) from exc

        if not zuruecksetzen.stimmt(daten.name, daten.code):
            await kern.versuch_merken(conn, kennungen)
            raise HTTPException(403, "Der Code stimmt nicht oder ist abgelaufen.")

        zeile = await conn.fetchrow(
            """
            select u.id, r.org_id
              from public.users u
              left join public.user_org_roles r on r.user_id = u.id
             where lower(u.olares_username) = lower($1) and u.deleted_at is null
             order by r.joined_at
             limit 1
            """,
            daten.name.strip(),
        )
        if zeile is None or zeile["org_id"] is None:
            raise HTTPException(403, "Der Code stimmt nicht oder ist abgelaufen.")

        await conn.execute(
            "update public.users set passwort_hash = $1, passwort_am = now(), "
            "gesperrt_bis = null where id = $2",
            kern.hash_passwort(daten.passwort), zeile["id"],
        )
        await conn.execute(
            "update public.sitzungen set beendet_am = now() "
            "where user_id = $1 and beendet_am is null",
            zeile["id"],
        )
        await kern.versuche_loeschen(conn, kennungen)
        token = await kern.sitzung_anlegen(conn, zeile["id"], zeile["org_id"], user_agent or "")

    zuruecksetzen.verbrauchen()
    _keks_setzen(request, antwort, token)
    return Lage(angemeldet=True, name=daten.name, modus=settings.anmeldung_modus)


@router.get("/einladung/{token}")
async def einladung_ansehen(token: str) -> dict:
    """Zeigt nur, für wen die Einladung gilt — und ob sie noch gilt.

    `uebernahme` ist der Fall, der eine Warnung verdient: Das Konto hat
    schon ein Passwort, und Einlösen **ersetzt** es. Für einen Eigentümer,
    der jemandem den Zugang zurücksetzt, ist das richtig. Wer den Link
    versehentlich bekommt, sperrt damit aber den bisherigen Inhaber aus —
    genau daran wäre am 8. September fast jemand hängengeblieben, weil der
    Anzeigename und die Kennung auf verschiedene Menschen zeigten.
    """
    async with acquire() as conn:
        row = await kern.einladung_lesen(conn, token)
    if row is None:
        raise HTTPException(404, "Diese Einladung gilt nicht mehr.")
    return {
        "name": row["display_name"] or row["olares_username"],
        "kennung": row["olares_username"],
        "uebernahme": bool(row["hat_passwort"]),
    }


@router.post("/einladung/{token}", response_model=Lage)
async def einladung_einloesen(
    token: str,
    daten: Einloesung,
    request: Request,
    antwort: Response,
    user_agent: Annotated[str | None, Header()] = None,
) -> Lage:
    """Passwort setzen und gleich angemeldet sein. Der Link ist danach tot."""
    _herkunft_pruefen(request)
    async with acquire() as conn:
        try:
            user_id = await kern.einladung_einloesen(conn, token, daten.passwort)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        except kern.Anmeldefehler as exc:
            raise HTTPException(404, str(exc)) from exc
        zeile = await conn.fetchrow(
            "select u.olares_username, u.display_name, r.org_id from public.users u "
            "join public.user_org_roles r on r.user_id = u.id where u.id = $1",
            user_id,
        )
        token_neu = await kern.sitzung_anlegen(conn, user_id, zeile["org_id"], user_agent or "")
    _keks_setzen(request, antwort, token_neu)
    return Lage(angemeldet=True, name=zeile["display_name"] or zeile["olares_username"], modus=settings.anmeldung_modus)




class Geraet(BaseModel):
    """Eine offene Sitzung. Kein Token, keine Adresse — nur, was hilft,
    ein fremdes Gerät zu erkennen."""

    id: UUID
    erstellt_am: datetime
    zuletzt_am: datetime
    laeuft_ab: datetime
    agent: str | None = None
    # Das Gerät, von dem diese Anfrage kommt. Es lässt sich nicht beenden,
    # ohne sich abzumelden — dafür gibt es „Abmelden“.
    aktuell: bool = False


@router.get("/anmeldung/geraete", response_model=list[Geraet])
async def geraete(request: Request, user: CurrentUser = Depends(get_current_user)) -> list[Geraet]:
    """Wo bin ich überall angemeldet?

    Sichtbar sind ausschließlich die eigenen Sitzungen — dafür sorgt die
    Zeilensicherheit über `sitzungen_selbst` und nicht erst diese Abfrage.
    """
    keks = request.cookies.get(kern.KEKS)
    hier = kern.token_hash(keks) if keks else ""
    async with acquire_as(user.user_id) as conn:
        zeilen = await conn.fetch(
            "select id, token_hash, erstellt_am, zuletzt_am, laeuft_ab, agent "
            "from public.sitzungen "
            "where user_id = $1 and beendet_am is null and laeuft_ab > now() "
            "order by zuletzt_am desc",
            user.user_id,
        )
    return [
        Geraet(
            id=z["id"], erstellt_am=z["erstellt_am"], zuletzt_am=z["zuletzt_am"],
            laeuft_ab=z["laeuft_ab"], agent=z["agent"], aktuell=z["token_hash"] == hier,
        )
        for z in zeilen
    ]


@router.delete("/anmeldung/geraete/{geraet_id}", status_code=204)
async def geraet_beenden(
    geraet_id: UUID, request: Request, user: CurrentUser = Depends(get_current_user)
) -> Response:
    """Beendet **eine** Sitzung, serverseitig.

    Die Bedingung `user_id = $2` ist nicht überflüssig neben der
    Zeilensicherheit: Sie ist die zweite Wand, falls jemand die Policy
    einmal lockert. Ein fremdes Gerät zu beenden bleibt damit unmöglich,
    auch wenn man seine Kennung errät.
    """
    _herkunft_pruefen(request)
    async with acquire_as(user.user_id) as conn:
        getroffen = await conn.fetchval(
            "update public.sitzungen set beendet_am = now() "
            "where id = $1 and user_id = $2 and beendet_am is null returning id",
            geraet_id, user.user_id,
        )
    if getroffen is None:
        raise HTTPException(404, "Dieses Gerät ist nicht (mehr) angemeldet.")
    return Response(status_code=204)


@router.post("/anmeldung/geraete/andere-beenden", status_code=200)
async def andere_beenden(
    request: Request, user: CurrentUser = Depends(get_current_user)
) -> dict[str, int]:
    """Meldet alle Geräte ab außer diesem.

    Der Knopf, den man drückt, wenn ein Rechner abhandenkommt. Das eigene
    bleibt: Wer sich beim Aufräumen selbst aussperrt, muss sich neu
    anmelden und traut sich beim nächsten Mal nicht mehr.
    """
    _herkunft_pruefen(request)
    keks = request.cookies.get(kern.KEKS)
    async with acquire_as(user.user_id) as conn:
        ergebnis = await conn.execute(
            "update public.sitzungen set beendet_am = now() "
            "where user_id = $1 and beendet_am is null and token_hash <> $2",
            user.user_id, kern.token_hash(keks) if keks else "",
        )
    return {"beendet": int(ergebnis.split()[-1])}
