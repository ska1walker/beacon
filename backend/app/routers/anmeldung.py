"""Anmelden, abmelden, Passwort setzen — der einzige Weg herein.

Der Keks trägt alles und ist für JavaScript unsichtbar (`HttpOnly`).
Damit kann kein eingeschleustes Skript die Sitzung stehlen, und es gibt
kein Token im `localStorage`, das ein Werbeblocker-Add-on mitlesen könnte.

`SameSite=Lax` ist der CSRF-Schutz: Ein Formular auf einer fremden Seite
darf den Keks bei einem POST nicht mitschicken. Zusätzlich wird der
`Origin` geprüft, wo er ankommt — Gürtel und Hosenträger, beides billig.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response
from pydantic import BaseModel, Field

from app import anmeldung as kern
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


@router.get("/einladung/{token}")
async def einladung_ansehen(token: str) -> dict:
    """Zeigt nur, für wen die Einladung gilt — und ob sie noch gilt."""
    async with acquire() as conn:
        row = await kern.einladung_lesen(conn, token)
    if row is None:
        raise HTTPException(404, "Diese Einladung gilt nicht mehr.")
    return {"name": row["display_name"] or row["olares_username"], "kennung": row["olares_username"]}


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


