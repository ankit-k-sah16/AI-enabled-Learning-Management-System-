"""
main.py — FastAPI application entry point.

Provides:
- /api/v1/* REST endpoints (auth, competencies, assessment, gaps, recommendations, RAG, quiz)
- /health endpoint
- Auto-generated OpenAPI docs at /docs and /redoc
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.core.config import settings
from src.db.session import init_db

logging.basicConfig(
    level=getattr(logging, settings.log_level, logging.INFO),
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown events."""
    logger.info("Starting %s v%s", settings.app_name, settings.app_version)
    init_db()
    logger.info("Database initialised.")
    if not settings.groq_available:
        logger.warning(
            "GROQ_API_KEY not configured — AI generation features will be unavailable."
        )
    yield
    logger.info("Shutting down.")


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description=(
        "AI-enabled Learning Management System for official statistics competency development. "
        "SIH 2026 | PS 26101"
    ),
    lifespan=lifespan,
)

# ── CORS ──────────────────────────────────────────────────────────────────────

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:8501", "http://127.0.0.1:8501"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Routers ───────────────────────────────────────────────────────────────────
# Imported inline to avoid circular imports at module load time

from src.api import auth_router, competency_router, assessment_router, health_router  # noqa: E402

app.include_router(health_router.router, tags=["Health"])
app.include_router(auth_router.router, prefix="/api/v1/auth", tags=["Authentication"])
app.include_router(competency_router.router, prefix="/api/v1/competencies", tags=["Competencies"])
app.include_router(assessment_router.router, prefix="/api/v1/assessments", tags=["Assessments"])
