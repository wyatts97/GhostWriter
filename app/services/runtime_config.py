"""Runtime configuration — single source of truth merging DB settings with .env fallback.

All services (scheduler, article_generator, llm_client, ghost_client) use this
instead of reading app.config.settings directly, so DB-saved settings are respected
without mutating the pydantic singleton.
"""

import json
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings as env_settings
from app.models.settings import Setting
from app.utils.encryption import decrypt_value

SENSITIVE_KEYS = {"llm_api_key", "openrouter_api_key", "ghost_admin_api_key"}


@dataclass
class RuntimeConfig:
    """Runtime configuration loaded from DB with .env fallback.

    Usage::
        config = await RuntimeConfig.load(session)
        llm = LlmClient(
            base_url=config.llm_api_base,
            api_key=config.llm_api_key,
            default_model=config.llm_default_model,
        )
    """

    # Provider
    llm_provider: str = "openai"

    # OpenAI / generic LLM
    llm_api_base: str = "https://api.openai.com/v1"
    llm_api_key: str = ""
    llm_default_model: str = "gpt-4o"

    # OpenRouter
    openrouter_api_base: str = "https://openrouter.ai/api/v1"
    openrouter_api_key: str = ""
    openrouter_default_model: str = ""

    # Ghost
    ghost_admin_url: str = ""
    ghost_admin_api_key: str = ""

    # General
    log_level: str = "info"

    # Store raw key:value pairs for any other settings
    _raw: dict[str, str] = field(default_factory=dict)

    @classmethod
    async def load(cls, session: AsyncSession) -> "RuntimeConfig":
        """Load runtime config from DB, falling back to .env values."""
        result = await session.execute(
            select(Setting).where(Setting.key.in_(SETTING_KEYS))
        )
        rows = result.scalars().all()
        db_settings = {r.key: r.value for r in rows}

        raw = dict(db_settings)

        # Build config: DB value → .env value → hardcoded default
        config = cls()
        for key, default in DEFAULTS.items():
            if key in db_settings and db_settings[key]:
                value = db_settings[key]
                if key in SENSITIVE_KEYS:
                    value = decrypt_value(value)
                setattr(config, key, value)
            else:
                env_val = getattr(env_settings, key, None) if hasattr(env_settings, key) else None
                if env_val:
                    setattr(config, key, str(env_val))
                else:
                    setattr(config, key, default)

        config._raw = raw
        return config

    def resolve_llm_config(self) -> dict[str, str]:
        """Return the active LLM provider's connection config.

        Returns ``{"base_url": …, "api_key": …, "model": …}`` for whichever
        provider is selected (openai or openrouter).
        """
        if self.llm_provider == "openrouter":
            return {
                "base_url": self.openrouter_api_base,
                "api_key": self.openrouter_api_key,
                "model": self.openrouter_default_model,
            }
        return {
            "base_url": self.llm_api_base,
            "api_key": self.llm_api_key,
            "model": self.llm_default_model,
        }

    @classmethod
    async def save_settings(
        cls, session: AsyncSession, form_values: dict[str, str]
    ) -> None:
        """Persist settings to DB (encrypting sensitive fields)."""
        from app.utils.encryption import encrypt_value

        for key, value in form_values.items():
            if key not in SETTING_KEYS:
                continue

            result = await session.execute(
                select(Setting).where(Setting.key == key)
            )
            setting = result.scalar_one_or_none()

            stored_value = value
            if key in SENSITIVE_KEYS and value:
                stored_value = encrypt_value(value)

            if setting:
                setting.value = stored_value
            else:
                setting = Setting(key=key, value=stored_value)
                session.add(setting)

        await session.commit()


SETTING_KEYS = [
    "llm_provider",
    "llm_api_base",
    "llm_api_key",
    "llm_default_model",
    "openrouter_api_base",
    "openrouter_api_key",
    "openrouter_default_model",
    "ghost_admin_url",
    "ghost_admin_api_key",
    "log_level",
]

DEFAULTS: dict[str, Any] = {
    "llm_provider": "openai",
    "llm_api_base": "https://api.openai.com/v1",
    "llm_api_key": "",
    "llm_default_model": "gpt-4o",
    "openrouter_api_base": "https://openrouter.ai/api/v1",
    "openrouter_api_key": "",
    "openrouter_default_model": "",
    "ghost_admin_url": "",
    "ghost_admin_api_key": "",
    "log_level": "info",
}
