"""
streamlit_app/utils.py — Shared utilities for the Streamlit application.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import requests
import streamlit as st

sys.path.insert(0, str(Path(__file__).parent.parent))
from src.core.config import settings


def api_url(path: str) -> str:
    """Build a full API URL from a relative path."""
    base = settings.api_base_url.rstrip("/")
    return f"{base}{path}"


def get_auth_header() -> dict:
    """Return Authorization header with current session token."""
    token = st.session_state.get("access_token")
    if not token:
        return {}
    return {"Authorization": f"Bearer {token}"}


def clear_session():
    """Clear all session state (logout)."""
    for key in list(st.session_state.keys()):
        del st.session_state[key]


def api_get(path: str, params: dict | None = None) -> dict | list | None:
    """Make an authenticated GET request to the API."""
    try:
        response = requests.get(
            api_url(path),
            headers=get_auth_header(),
            params=params,
            timeout=30,
        )
        if response.status_code == 401:
            st.error("Session expired. Please log in again.")
            clear_session()
            st.rerun()
        if response.ok:
            return response.json()
        st.error(f"API Error {response.status_code}: {response.json().get('detail', 'Unknown error')}")
        return None
    except requests.ConnectionError:
        st.error(
            "⚠️ Cannot reach the API server. "
            f"Make sure FastAPI is running at {settings.api_base_url}"
        )
        return None
    except Exception as exc:
        st.error(f"Unexpected error: {exc}")
        return None


def api_post(path: str, json: dict | None = None, data: dict | None = None) -> dict | None:
    """Make an authenticated POST request to the API."""
    try:
        response = requests.post(
            api_url(path),
            headers=get_auth_header(),
            json=json,
            data=data,
            timeout=30,
        )
        if response.status_code == 401:
            st.error("Session expired. Please log in again.")
            clear_session()
            st.rerun()
        if response.ok:
            return response.json()
        st.error(f"API Error {response.status_code}: {response.json().get('detail', 'Unknown error')}")
        return None
    except requests.ConnectionError:
        st.error(
            "⚠️ Cannot reach the API server. "
            f"Make sure FastAPI is running at {settings.api_base_url}"
        )
        return None
    except Exception as exc:
        st.error(f"Unexpected error: {exc}")
        return None


def show_metric_card(label: str, value: str, delta: str | None = None, help_text: str | None = None):
    """Render a styled metric card."""
    with st.container():
        st.metric(label=label, value=value, delta=delta, help=help_text)


def proficiency_badge(level: str) -> str:
    """Return a coloured emoji badge for a proficiency level."""
    badges = {
        "Expert":       "🟢 Expert",
        "Advanced":     "🔵 Advanced",
        "Intermediate": "🟡 Intermediate",
        "Beginner":     "🔴 Beginner",
        "Unknown":      "⚪ Not Assessed",
    }
    return badges.get(level, f"⚪ {level}")
