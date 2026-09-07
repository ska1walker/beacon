"""Fehler aus der Oberfläche — ins Protokoll der Box, nicht ins Nichts.

„Application error: a client-side exception has occurred“ sagt dem, der
davorsitzt, gar nichts, und dem, der es beheben soll, auch nicht: Der
Stack liegt im Browser eines anderen Menschen. Die Oberfläche schickt
Meldung und Stack deshalb hierher, und hier landen sie im Pod-Log — dort,
wo `kubectl logs` sie findet.

Keine Tabelle, kein Speicher: Ein Fehlerbericht, der selbst eine
Datenbank braucht, fällt genau dann aus, wenn er gebraucht wird.
"""

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel, Field

from app.auth import CurrentUser, get_current_user

router = APIRouter(prefix="/api/fehler", tags=["system"])


class Bericht(BaseModel):
    nachricht: str = Field(max_length=2000)
    stack: str = Field(default="", max_length=8000)
    pfad: str = Field(default="", max_length=500)
    agent: str = Field(default="", max_length=300)


@router.post("", status_code=204)
async def melden(bericht: Bericht, user: CurrentUser = Depends(get_current_user)) -> Response:
    zeilen = [
        f"Oberflächenfehler [{user.olares_username}] {bericht.pfad or '?'}: {bericht.nachricht}",
    ]
    if bericht.agent:
        zeilen.append(f"  Browser: {bericht.agent}")
    if bericht.stack:
        zeilen.extend("  " + z for z in bericht.stack.splitlines())
    print("\n".join(zeilen), flush=True)
    return Response(status_code=204)
