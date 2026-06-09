from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Ghost Integration
    ghost_admin_url: str = ""
    ghost_admin_api_key: str = ""

    # LLM Provider (OpenAI-compatible)
    llm_api_base: str = "https://api.openai.com/v1"
    llm_api_key: str = ""
    llm_default_model: str = "gpt-4o"

    # Application
    app_secret_key: str = "change-me-to-a-random-secret"
    log_level: str = "info"
    database_url: str = "sqlite+aiosqlite:///app/data/ghostwriter.db"

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
