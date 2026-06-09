"""Settings router — LLM, Ghost, and global configuration."""

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.main import templates
from app.models.settings import Setting

router = APIRouter(tags=["settings"])

SETTING_KEYS = [
    "llm_api_base",
    "llm_api_key",
    "llm_default_model",
    "ghost_admin_url",
    "ghost_admin_api_key",
    "log_level",
]

DEFAULT_VALUES = {
    "llm_api_base": "https://api.openai.com/v1",
    "llm_default_model": "gpt-4o",
    "log_level": "info",
}


@router.get("/", response_class=HTMLResponse)
async def settings_page(
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    """Show the settings page."""
    settings_dict = {}

    for key in SETTING_KEYS:
        result = await session.execute(
            select(Setting).where(Setting.key == key)
        )
        setting = result.scalar_one_or_none()
        settings_dict[key] = setting.value if setting else DEFAULT_VALUES.get(key, "")

    return templates.TemplateResponse(
        "settings.html",
        {
            "request": request,
            "settings": settings_dict,
            "active_page": "settings",
        },
    )


@router.post("/save")
async def save_settings(
    request: Request,
    llm_api_base: str = Form(""),
    llm_api_key: str = Form(""),
    llm_default_model: str = Form(""),
    ghost_admin_url: str = Form(""),
    ghost_admin_api_key: str = Form(""),
    log_level: str = Form("info"),
    session: AsyncSession = Depends(get_session),
):
    """Save all settings."""
    form_values = {
        "llm_api_base": llm_api_base,
        "llm_api_key": llm_api_key,
        "llm_default_model": llm_default_model,
        "ghost_admin_url": ghost_admin_url,
        "ghost_admin_api_key": ghost_admin_api_key,
        "log_level": log_level,
    }

    for key, value in form_values.items():
        result = await session.execute(
            select(Setting).where(Setting.key == key)
        )
        setting = result.scalar_one_or_none()

        if setting:
            setting.value = value
        else:
            setting = Setting(key=key, value=value)
            session.add(setting)

    await session.commit()

    # Update runtime config
    from app.config import settings as app_settings

    app_settings.llm_api_base = llm_api_base or app_settings.llm_api_base
    app_settings.llm_api_key = llm_api_key or app_settings.llm_api_key
    app_settings.llm_default_model = (
        llm_default_model or app_settings.llm_default_model
    )
    app_settings.ghost_admin_url = ghost_admin_url or app_settings.ghost_admin_url
    app_settings.ghost_admin_api_key = (
        ghost_admin_api_key or app_settings.ghost_admin_api_key
    )
    app_settings.log_level = log_level or app_settings.log_level

    return templates.TemplateResponse(
        "settings.html",
        {
            "request": request,
            "settings": form_values,
            "saved": True,
            "active_page": "settings",
        },
    )


@router.post("/test-ghost")
async def test_ghost_connection(
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    """Test the Ghost Admin API connection."""
    from app.services.ghost_client import GhostClient

    # Get current settings
    result = await session.execute(
        select(Setting).where(Setting.key == "ghost_admin_url")
    )
    url_setting = result.scalar_one_or_none()

    result = await session.execute(
        select(Setting).where(Setting.key == "ghost_admin_api_key")
    )
    key_setting = result.scalar_one_or_none()

    admin_url = url_setting.value if url_setting else ""
    admin_key = key_setting.value if key_setting else ""

    ghost = GhostClient(admin_url=admin_url, admin_api_key=admin_key)
    success = await ghost.test_connection()

    return JSONResponse(
        {
            "success": success,
            "message": (
                "Connected successfully!" if success else "Connection failed. Check your URL and API key."
            ),
        }
    )


@router.post("/test-llm")
async def test_llm_connection(
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    """Test the LLM API connection with a simple request."""
    from app.services.llm_client import LlmClient

    result = await session.execute(
        select(Setting).where(Setting.key == "llm_api_base")
    )
    base_setting = result.scalar_one_or_none()

    result = await session.execute(
        select(Setting).where(Setting.key == "llm_api_key")
    )
    key_setting = result.scalar_one_or_none()

    result = await session.execute(
        select(Setting).where(Setting.key == "llm_default_model")
    )
    model_setting = result.scalar_one_or_none()

    api_base = base_setting.value if base_setting else "https://api.openai.com/v1"
    api_key = key_setting.value if key_setting else ""
    model = model_setting.value if model_setting else "gpt-4o"

    llm = LlmClient(base_url=api_base, api_key=api_key, default_model=model)
    try:
        response = await llm.generate_chat(
            messages=[{"role": "user", "content": "Reply with just: OK"}],
            model=model,
            max_tokens=10,
        )
        return JSONResponse(
            {"success": True, "message": "LLM API connected successfully!"}
        )
    except Exception as exc:
        return JSONResponse(
            {"success": False, "message": f"Connection failed: {exc}"}
        )
