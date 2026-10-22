"""
src/api/health_router.py — Health and readiness endpoints.
"""

from __future__ import annotations

from fastapi import APIRouter

from src.core.config import settings

router = APIRouter()


@router.get("/health")
def health_check():
    """Basic health check — never exposes secrets or tracebacks."""
    return {
        "status": "healthy",
        "app": settings.app_name,
        "version": settings.app_version,
        "groq_configured": settings.groq_available,
    }


@router.get("/health/groq")
def groq_health():
    """Check Groq API availability. May be slow if API is unreachable."""
    from src.ai.groq_client import check_groq_health
    return check_groq_health()
