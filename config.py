"""
Application configuration — all settings are read from environment
variables (via .env file). Pydantic Settings handles validation and
type coercion automatically.
"""

from functools import lru_cache
from typing import Annotated, List

from pydantic import BeforeValidator, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def parse_allowed_origins(v: str | list) -> list:
    """Parse comma-separated origins string into list."""
    if isinstance(v, str):
        return [origin.strip() for origin in v.split(",")]
    return v


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── App ───────────────────────────────────────────────────────────────────
    app_name: str = "dark-guard-ai"
    app_version: str = "0.1.0"
    app_env: str = Field(default="development", pattern="^(development|staging|production)$")
    debug: bool = True
    secret_key: str = Field(min_length=32)
    api_key: str = Field(min_length=16)

    # ── Server ────────────────────────────────────────────────────────────────
    backend_host: str = "0.0.0.0"
    backend_port: int = 8000
    allowed_origins: Annotated[List[str], BeforeValidator(parse_allowed_origins)] = [
        "http://localhost:3000"
    ]

    # ── OpenAI ────────────────────────────────────────────────────────────────
    openai_api_key: str
    openai_model: str = "gpt-4o"
    openai_embedding_model: str = "text-embedding-3-small"
    openai_max_tokens: int = 2048
    openai_temperature: float = 0.1

    # ── MCP Server ────────────────────────────────────────────────────────────
    mcp_host: str = "0.0.0.0"
    mcp_port: int = 8001
    mcp_secret: str = Field(min_length=16)

    # ── Redis ─────────────────────────────────────────────────────────────────
    redis_url: str = "redis://localhost:6379/0"
    redis_password: str = ""
    redis_scan_cache_ttl: int = 300       # 5 minutes
    redis_session_ttl: int = 3600         # 1 hour

    # ── Qdrant ────────────────────────────────────────────────────────────────
    qdrant_host: str = "localhost"
    qdrant_port: int = 6333
    qdrant_grpc_port: int = 6334
    qdrant_api_key: str = ""
    qdrant_collection_examples: str = "pattern_examples"
    qdrant_collection_history: str = "detection_history"
    qdrant_vector_size: int = 1536        # text-embedding-3-small dimensions

    # ── SQLite ────────────────────────────────────────────────────────────────
    database_url: str = "sqlite+aiosqlite:///./dark_guard.db"

    # ── Playwright ────────────────────────────────────────────────────────────
    playwright_browser: str = "chromium"
    playwright_headless: bool = True
    playwright_timeout: int = 30_000      # ms
    playwright_pool_size: int = 3

    # ── Detection ─────────────────────────────────────────────────────────────
    detection_confidence_threshold: float = 0.70

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    @property
    def is_development(self) -> bool:
        return self.app_env == "development"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """
    Returns a cached singleton Settings instance.
    Call this anywhere in the app:
        from backend.config import get_settings
        settings = get_settings()
    """
    return Settings()
