"""Settings router — LLM, Ghost, and global configuration."""

import httpx
from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.main import templates
from app.models.settings import Setting
from app.services.runtime_config import RuntimeConfig
from app.utils.encryption import encrypt_value

router = APIRouter(tags=["settings"])


@router.get("/", response_class=HTMLResponse)
async def settings_page(
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    """Show the settings page."""
    config = await RuntimeConfig.load(session)

    # Convert dataclass to dict for the template (skip _raw)
    from app.services.runtime_config import SETTING_KEYS

    settings_dict = {
        key: getattr(config, key, "")
        for key in SETTING_KEYS
    }

    return templates.TemplateResponse(
        request,
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
    llm_provider: str = Form("openai"),
    # OpenAI / generic fields
    llm_api_base: str = Form(""),
    llm_api_key: str = Form(""),
    llm_default_model: str = Form(""),
    # OpenRouter fields
    openrouter_api_base: str = Form(""),
    openrouter_api_key: str = Form(""),
    openrouter_default_model: str = Form(""),
    # Ghost fields
    ghost_admin_url: str = Form(""),
    ghost_admin_api_key: str = Form(""),
    # General
    log_level: str = Form("info"),
    session: AsyncSession = Depends(get_session),
):
    """Save all settings to DB (encrypted) — stops mutating the pydantic singleton."""
    form_values = {
        "llm_provider": llm_provider,
        "llm_api_base": llm_api_base,
        "llm_api_key": llm_api_key,
        "llm_default_model": llm_default_model,
        "openrouter_api_base": openrouter_api_base,
        "openrouter_api_key": openrouter_api_key,
        "openrouter_default_model": openrouter_default_model,
        "ghost_admin_url": ghost_admin_url,
        "ghost_admin_api_key": ghost_admin_api_key,
        "log_level": log_level,
    }

    await RuntimeConfig.save_settings(session, form_values)

    return templates.TemplateResponse(
        request,
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
    """Test the Ghost Admin API connection using RuntimeConfig."""
    from app.services.ghost_client import GhostClient

    config = await RuntimeConfig.load(session)

    ghost = GhostClient(
        admin_url=config.ghost_admin_url,
        admin_api_key=config.ghost_admin_api_key,
    )
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
    """Test the LLM API connection using RuntimeConfig (active provider)."""
    from app.services.llm_client import LlmClient

    config = await RuntimeConfig.load(session)
    llm_cfg = config.resolve_llm_config()

    llm = LlmClient(
        base_url=llm_cfg["base_url"],
        api_key=llm_cfg["api_key"],
        default_model=llm_cfg["model"],
    )
    try:
        await llm.generate_chat(
            messages=[{"role": "user", "content": "Reply with just: OK"}],
            model=llm_cfg["model"],
            max_tokens=10,
        )
        return JSONResponse(
            {"success": True, "message": "LLM API connected successfully!"}
        )
    except Exception as exc:
        return JSONResponse(
            {"success": False, "message": f"Connection failed: {exc}"}
        )


@router.get("/openrouter-models")
async def list_openrouter_models(request: Request):
    """Fetch available models from OpenRouter API."""
    from app.database import async_session_factory
    from app.utils.encryption import decrypt_value

    async with async_session_factory() as session:
        key_row = (await session.execute(
            select(Setting).where(Setting.key == "openrouter_api_key")
        )).scalar_one_or_none()
        base_row = (await session.execute(
            select(Setting).where(Setting.key == "openrouter_api_base")
        )).scalar_one_or_none()

    api_key = decrypt_value(key_row.value) if key_row and key_row.value else ""
    api_base = (base_row.value if base_row else "https://openrouter.ai/api/v1").rstrip("/")

    if not api_key:
        return JSONResponse(
            {"success": False, "error": "OpenRouter API key not configured. Save your key first."}
        )

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            headers = {"Authorization": f"Bearer {api_key}"}
            resp = await client.get(f"{api_base}/models", headers=headers)
            if resp.status_code != 200:
                return JSONResponse(
                    {"success": False, "error": f"OpenRouter returned {resp.status_code}"}
                )
            data = resp.json()
            models = [
                {"id": m["id"], "name": m.get("name", m["id"])}
                for m in data.get("data", [])
                if m.get("id")
            ]
            models.sort(key=lambda x: x["id"].lower())
            return JSONResponse({"success": True, "models": models})
    except Exception as exc:
        return JSONResponse(
            {"success": False, "error": str(exc)}
        )
