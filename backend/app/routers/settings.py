"""Einstellungen der Organisation."""

from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException

from app import postfach, tresor, versand
from app.auth import CurrentUser, get_current_user, verwaltet
from app.db import acquire_as
from app.llm import load_llm_config
from app.schemas import Absender, OrgSettings, OrgSettingsIn

# Was nie im Klartext gespeichert und nie zurückgegeben wird.
GEHEIM = tresor.SPALTEN["org_settings"][1]

# Welches Geheimnis zu welcher Adresse gehört.
#
# Ein Schlüssel gilt für **einen** Dienst. Bis 0.9.6 stand er in einer
# Spalte, die den Dienst nicht kannte: Wer die Adresse von Brave auf
# Tavily umstellte und das Schlüsselfeld leer ließ — es zeigt „hinterlegt"
# und lädt genau dazu ein —, behielt den Brave-Schlüssel und schickte ihn
# als Bearer an Tavily. Antwort: 401, und im Bildschirm stand weiter
# „hinterlegt". Marc am 10.9.2026: „Musste nur aufpassen wenn du wechselst,
# weil der dann die Secret Keys durcheinander bringt." Er hat es sich
# damals in der Datenbank geradegerückt.
ADRESSE_ZU_GEHEIMNIS = {
    "suche_endpoint_url": "suche_api_key",
    "llm_base_url": "llm_api_key",
    "tts_endpoint_url": "tts_api_key",
    "mail_endpoint_url": "mail_endpoint_secret",
}


def _wirt(adresse: str | None) -> str:
    """Der Rechnername einer Adresse — daran hängt, ob es derselbe Dienst ist.

    Ein Tippfehler im Pfad soll den Schlüssel nicht wegwerfen; ein
    Wechsel von `api.search.brave.com` zu `api.tavily.com` schon.
    """
    if not adresse or not adresse.strip():
        return ""
    return (urlparse(adresse.strip()).hostname or adresse.strip()).lower()

# Wie ein verlorenes Geheimnis im Satz heißt. Der Spaltenname hilft dem
# Menschen vor dem Bildschirm nicht weiter.
GEHEIMTEXT = {
    "smtp_passwort": "Versandpasswort",
    "imap_passwort": "Postfachpasswort",
    "llm_api_key": "Schlüssel des Sprachmodells",
    "suche_api_key": "Schlüssel des Suchdienstes",
    "tts_api_key": "Schlüssel der Sprachausgabe",
    "brevo_api_key": "Brevo-Schlüssel",
    "mail_endpoint_secret": "Geheimnis des Mail-Endpunkts",
}

router = APIRouter(prefix="/api/settings", tags=["settings"])


@router.get("", response_model=OrgSettings)
async def get_settings(user: CurrentUser = Depends(get_current_user)) -> OrgSettings:
    async with acquire_as(user.user_id) as conn:
        row = await conn.fetchrow(
            "select * from public.org_settings where org_id = $1", user.org_id
        )
        cfg = await load_llm_config(conn, user.org_id)
    # Die Absenderfelder kommen unverändert aus der Zeile. Sie einzeln
    # aufzuzählen hieße, jede neue Angabe an zwei Stellen zu pflegen.
    absender = {
        feld: (row[feld] if row and feld in row else None)
        for feld in Absender.model_fields
    }
    # Steht in einer der Spalten ein verschlüsselter Wert, den der
    # Tresorschlüssel nicht mehr aufbekommt, ist das keine Kleinigkeit:
    # Der Dienst bekommt dann ein leeres Geheimnis und antwortet mit 401,
    # während der Bildschirm „hinterlegt" zeigt.
    verloren = sorted(
        GEHEIMTEXT[spalte]
        for spalte in GEHEIM
        if row is not None and tresor.verloren(row[spalte])
    )

    return OrgSettings(
        zugangsdaten_verloren=verloren,
        **absender,
        mail_endpoint_url=(row["mail_endpoint_url"] if row else None),
        mail_absender=(row["mail_absender"] if row else None),
        mail_endpoint_secret_set=tresor.lesbar(row["mail_endpoint_secret"] if row else None),
        llm_base_url=cfg.base_url,
        llm_model=cfg.model,
        # Der Schlüssel geht nie zurück — die Oberfläche muss nur wissen,
        # ob einer da ist, um „hinterlegt" statt eines leeren Feldes zu zeigen.
        llm_api_key_set=bool(cfg.api_key),
        llm_ready=cfg.eingerichtet,
        suche_endpoint_url=(row["suche_endpoint_url"] if row else None),
        suche_api_key_set=tresor.lesbar(row["suche_api_key"] if row else None),
        suche_region=(row["suche_region"] if row else "DE"),
        anreicherung_automatisch=(row["anreicherung_automatisch"] if row else True),
        anreicherung_uebernahme=(row["anreicherung_uebernahme"] if row else "leere_felder"),
        imap_host=(row["imap_host"] if row else None),
        imap_port=(row["imap_port"] if row else 993),
        imap_benutzer=(row["imap_benutzer"] if row else None),
        imap_passwort_set=tresor.lesbar(row["imap_passwort"] if row else None),
        imap_ordner=(row["imap_ordner"] if row else "INBOX"),
        imap_takt_minuten=(row["imap_takt_minuten"] if row else 5),
        imap_aktiv=bool(row and row["imap_aktiv"]),
        imap_zuletzt=(row["imap_zuletzt"] if row else None),
        imap_letzter_fehler=(row["imap_letzter_fehler"] if row else None),
        smtp_host=(row["smtp_host"] if row else None),
        smtp_port=(row["smtp_port"] if row else 587),
        smtp_benutzer=(row["smtp_benutzer"] if row else None),
        smtp_passwort_set=tresor.lesbar(row["smtp_passwort"] if row else None),
        smtp_sicherheit=(row["smtp_sicherheit"] if row else "starttls"),
        smtp_absender=(row["smtp_absender"] if row else None),
        smtp_absender_name=(row["smtp_absender_name"] if row else None),
        smtp_zuletzt=(row["smtp_zuletzt"] if row else None),
        smtp_letzter_fehler=(row["smtp_letzter_fehler"] if row else None),
        smtp_ready=versand.smtp_aus(dict(row) if row else None) is not None,
        marketing_versand=(row["marketing_versand"] if row else "smtp"),
        brevo_api_key_set=tresor.lesbar(row["brevo_api_key"] if row else None),
        marketing_absender=(row["marketing_absender"] if row else None),
        marketing_absender_name=(row["marketing_absender_name"] if row else None),
        links_basis_url=(row["links_basis_url"] if row else None),
        links_basis_wirksam=versand.basis_url(dict(row) if row else None),
        doi_betreff=(row["doi_betreff"] if row else None),
        doi_text=(row["doi_text"] if row else None),
        tts_endpoint_url=(row["tts_endpoint_url"] if row else None),
        tts_api_key_set=bool(row and row["tts_api_key"]),
        tts_modell=(row["tts_modell"] if row else "") or "",
        tts_stimme=(row["tts_stimme"] if row else None),
        tts_modell_2=(row["tts_modell_2"] if row else "") or "",
        tts_stimme_2=(row["tts_stimme_2"] if row else None),
        tts_ready=bool(row and (row["tts_endpoint_url"] or "").strip()),
        podcast_automatisch=bool(row and row["podcast_automatisch"]),
        default_currency=(row["default_currency"] if row else "EUR"),
        locale=(row["locale"] if row else "de"),
    )


@router.put("", response_model=OrgSettings)
async def update_settings(
    payload: OrgSettingsIn,
    # Schlüssel für Sprachmodell, SMTP und Suche stehen hier. Wer sie
    # ändern darf, ist eine andere Frage als wer sie sehen darf.
    user: CurrentUser = Depends(verwaltet),
) -> OrgSettings:
    felder = payload.model_dump(exclude_unset=True)
    async with acquire_as(user.user_id) as conn:
        await conn.execute(
            "insert into public.org_settings (org_id) values ($1) on conflict do nothing",
            user.org_id,
        )

        # Zeigt eine Adresse auf einen anderen Rechner, gilt das
        # hinterlegte Geheimnis nicht mehr. Kommt in derselben Anfrage ein
        # neues mit, bleibt es dabei; sonst wird das alte gelöscht, damit
        # die Maske ehrlich „keiner hinterlegt" zeigt statt den Schlüssel
        # des Vorgängers an den neuen Dienst zu schicken.
        vorher = await conn.fetchrow(
            "select * from public.org_settings where org_id = $1", user.org_id
        )
        for adressfeld, geheimfeld in ADRESSE_ZU_GEHEIMNIS.items():
            if adressfeld not in felder or felder.get(geheimfeld):
                continue
            if _wirt(felder[adressfeld]) != _wirt(vorher[adressfeld] if vorher else None):
                felder[geheimfeld] = None
        for name, wert in felder.items():
            # Ein leer gesendetes Schlüsselfeld löscht den Schlüssel nicht
            # versehentlich: Die Oberfläche zeigt ihn nie an, also käme er
            # bei jedem Speichern leer zurück und wäre nach dem ersten
            # Feldwechsel weg. Wer ihn entfernen will, sendet null.
            if name in GEHEIM and wert == "":
                continue
            # Geheimnisse gehen verschlüsselt in die Datenbank (app/tresor.py).
            # Der Schlüssel liegt als Datei neben den Daten, nicht in der
            # Datenbank — ein Abzug allein gibt damit nichts her.
            if name in GEHEIM:
                wert = tresor.verschluesseln(wert)
            await conn.execute(
                f"update public.org_settings set {name} = $1, updated_at = now(), updated_by = $2 "
                f"where org_id = $3",
                wert,
                user.user_id,
                user.org_id,
            )
    return await get_settings(user)


@router.post("/postfach/abholen")
async def postfach_abholen(user: CurrentUser = Depends(get_current_user)) -> dict:
    """Holt sofort ab, statt auf den Takt zu warten.

    Der Knopf, der eine Einrichtung beweist: Zugangsdaten, die erst beim
    nächsten Lauf in fünf Minuten stillschweigend scheitern, sind keine
    Einrichtung, sondern eine Hoffnung. Der Fehler kommt deshalb hier
    zurück und nicht nur ins Protokoll.
    """
    async with acquire_as(user.user_id) as conn:
        try:
            bilanz = await postfach.einlesen(conn, user.org_id, user.user_id)
        except Exception as exc:
            grund = f"{type(exc).__name__}: {exc}"[:500]
            await conn.execute(
                "update public.org_settings set imap_letzter_fehler = $1, imap_zuletzt = now() "
                "where org_id = $2",
                grund, user.org_id,
            )
            raise HTTPException(502, f"Das Postfach antwortet nicht: {exc}") from exc
    return bilanz


@router.post("/versand/testen")
async def versand_testen(user: CurrentUser = Depends(get_current_user)) -> dict:
    """Schickt eine Mail an die eigene Absenderadresse — der Knopf, der
    ein Konto beweist. Dasselbe Muster wie „Jetzt abholen“ beim Postfach:
    Der Fehler kommt hierher zurück, nicht erst in fünf Minuten ins
    Protokoll."""
    async with acquire_as(user.user_id) as conn:
        einst = await conn.fetchrow("select * from public.org_settings where org_id = $1", user.org_id)
        konto = versand.smtp_aus(dict(einst) if einst else None)
        if konto is None:
            raise HTTPException(409, "Kein SMTP-Konto hinterlegt. Server und Absenderadresse fehlen.")
        mail_id = await versand.einreihen(
            conn, user.org_id, art="transaktional", an=konto.absender,
            betreff="beacon: Testmail", text="Wenn diese Mail ankommt, ist der Versand eingerichtet.\n",
            created_by=user.user_id, payload={"zweck": "test"},
        )
        try:
            zeile = await versand.versenden(conn, user.org_id, mail_id)
        except versand.Unmoeglich as exc:
            raise HTTPException(409, str(exc)) from exc
    if zeile["status"] != "gesendet":
        raise HTTPException(502, f"Der Mailserver hat abgelehnt: {zeile['fehler']}")
    return {"gesendet": True, "an": zeile["an"], "message_id": zeile["message_id"]}
