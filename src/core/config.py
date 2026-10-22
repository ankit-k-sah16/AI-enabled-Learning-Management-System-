"""
config.py — Centralised application configuration.

Reads settings from environment variables and .env file.
All modules import from here; no scattered os.getenv() calls.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment / .env file."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── Application ────────────────────────────────────────────────
    app_name: str = "AI Skill Intelligence Platform"
    app_version: str = "0.1.0"
    debug: bool = False
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"

    # ── Groq LLM ──────────────────────────────────────────────────
    groq_api_key: str = Field(default="", alias="GROQ_API_KEY")
    groq_model_primary: str = Field(
        default="llama-3.3-70b-versatile", alias="GROQ_MODEL_PRIMARY"
    )
    groq_model_fast: str = Field(
        default="llama-3.1-8b-instant", alias="GROQ_MODEL_FAST"
    )
    groq_max_retries: int = 3
    groq_timeout_seconds: int = 60

    # ── Database ──────────────────────────────────────────────────
    database_url: str = "sqlite:///./data/lms.db"

    # ── Auth / JWT ────────────────────────────────────────────────
    secret_key: str = Field(
        default="CHANGE_ME_IN_DOT_ENV_FILE_AT_LEAST_32_CHARS", alias="SECRET_KEY"
    )
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 480

    # ── FastAPI ───────────────────────────────────────────────────
    api_host: str = "127.0.0.1"
    api_port: int = 8000

    # ── Streamlit ─────────────────────────────────────────────────
    streamlit_port: int = 8501
    api_base_url: str = "http://127.0.0.1:8000"

    # ── Embeddings & Vector Store ─────────────────────────────────
    vector_store_path: str = "./vector_store"
    embedding_model: str = "all-MiniLM-L6-v2"

    # ── File Uploads ──────────────────────────────────────────────
    max_upload_size_mb: int = 50
    allowed_extensions: str = "pdf,docx,pptx"

    # ── Admin Bootstrap ───────────────────────────────────────────
    admin_email: str = "admin@lms.local"
    admin_password: str = Field(
        default="CHANGE_BEFORE_DEMO", alias="ADMIN_PASSWORD"
    )

    # ── Proficiency Scale Thresholds ──────────────────────────────
    proficiency_beginner_max: int = 39        # 0–39
    proficiency_intermediate_max: int = 59    # 40–59
    proficiency_advanced_max: int = 79        # 60–79
    # Expert: 80–100

    @field_validator("groq_api_key", mode="before")
    @classmethod
    def _strip_api_key(cls, v: str) -> str:
        return (v or "").strip()

    @property
    def groq_available(self) -> bool:
        """True when a non-placeholder API key is configured."""
        key = self.groq_api_key
        return bool(key) and key not in {"", "your_groq_api_key_here"}

    @property
    def allowed_extensions_list(self) -> list[str]:
        return [ext.strip().lower() for ext in self.allowed_extensions.split(",")]

    @property
    def vector_store_dir(self) -> Path:
        return Path(self.vector_store_path)

    @property
    def proficiency_label(self) -> dict[str, tuple[int, int]]:
        """Return proficiency band ranges."""
        return {
            "Beginner":     (0,  self.proficiency_beginner_max),
            "Intermediate": (self.proficiency_beginner_max + 1,
                             self.proficiency_intermediate_max),
            "Advanced":     (self.proficiency_intermediate_max + 1,
                             self.proficiency_advanced_max),
            "Expert":       (self.proficiency_advanced_max + 1, 100),
        }

    def score_to_proficiency(self, score: float) -> str:
        """Map a 0–100 score to a proficiency label."""
        s = max(0.0, min(100.0, score))
        if s <= self.proficiency_beginner_max:
            return "Beginner"
        if s <= self.proficiency_intermediate_max:
            return "Intermediate"
        if s <= self.proficiency_advanced_max:
            return "Advanced"
        return "Expert"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return cached Settings instance. Import this everywhere."""
    return Settings()


# Module-level convenience alias
settings = get_settings()
