"""Einstellungen der Organisation."""

from fastapi import APIRouter, Depends

from app.auth import CurrentUser, get_current_user
from app.db import acquire_as
from app.llm import load_llm_config
from app.schemas import OrgSettings, OrgSettingsIn

router = APIRouter(prefix="/api/settings", tags=["settings"])


@router.get("", response_model=OrgSettings)
async def get_settings(user: CurrentUser = Depends(get_current_user)) -> OrgSettings:
    async with acquire_as(user.user_id) as conn:
        row = await conn.fetchrow(
            "select * from public.org_settings where org_id = $1", user.org_id
        )
        cfg = await load_llm_config(conn, user.org_id)
    return OrgSettings(
        llm_base_url=cfg.base_url,
        llm_model=cfg.model,
        # Der Schlüssel geht nie zurück — die Oberfläche muss nur wissen,
        # ob einer da ist, um „hinterlegt" statt eines leeren Feldes zu zeigen.
        llm_api_key_set=bool(cfg.api_key),
        llm_ready=cfg.eingerichtet,
        default_currency=(row["default_currency"] if row else "EUR"),
        locale=(row["locale"] if row else "de"),
    )


@router.put("", response_model=OrgSettings)
async def update_settings(
    payload: OrgSettingsIn,
    user: CurrentUser = Depends(get_current_user),
) -> OrgSettings:
    felder = payload.model_dump(exclude_unset=True)
    async with acquire_as(user.user_id) as conn:
        await conn.execute(
            "insert into public.org_settings (org_id) values ($1) on conflict do nothing",
            user.org_id,
        )
        for name, wert in felder.items():
            # Ein leer gesendetes Schlüsselfeld löscht den Schlüssel nicht
            # versehentlich: Die Oberfläche zeigt ihn nie an, also käme er
            # bei jedem Speichern leer zurück und wäre nach dem ersten
            # Feldwechsel weg. Wer ihn entfernen will, sendet null.
            if name == "llm_api_key" and wert == "":
                continue
            await conn.execute(
                f"update public.org_settings set {name} = $1, updated_at = now(), updated_by = $2 "
                f"where org_id = $3",
                wert,
                user.user_id,
                user.org_id,
            )
    return await get_settings(user)
