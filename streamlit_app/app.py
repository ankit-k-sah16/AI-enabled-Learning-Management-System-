"""
streamlit_app/app.py — Main Streamlit application entry point.

Run with:
    streamlit run streamlit_app/app.py

This file handles:
- Session state initialisation.
- Navigation / page routing.
- API base URL configuration.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Ensure project root is on path for direct runs
sys.path.insert(0, str(Path(__file__).parent.parent))

import streamlit as st
from streamlit_app.utils import api_url, get_auth_header, clear_session

# ── Page Configuration ────────────────────────────────────────────────────────

st.set_page_config(
    page_title="AI Skill Intelligence Platform",
    page_icon="🎓",
    layout="wide",
    initial_sidebar_state="expanded",
    menu_items={
        "About": "AI-enabled LMS for official statistics. SIH 2026 | PS 26101",
    },
)

# ── Session State Initialisation ──────────────────────────────────────────────

def _init_session():
    defaults = {
        "access_token": None,
        "user_id": None,
        "user_role": None,
        "user_name": None,
        "current_page": "home",
        "selected_role_id": None,
        "assessment_attempt": None,
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v


_init_session()

# ── Navigation ────────────────────────────────────────────────────────────────

def _learner_nav():
    st.sidebar.title("🎓 Learning Hub")
    st.sidebar.write(f"👤 {st.session_state.get('user_name', '')}")
    pages = {
        "🏠 Dashboard": "dashboard",
        "📋 My Competencies": "competencies",
        "📝 Take Assessment": "assessment",
        "🔍 Skill Gap Analysis": "skill_gap",
        "🗺️ Learning Pathway": "pathway",
        "📚 Resource Catalog": "catalog",
        "🤖 Quiz Generator": "quiz",
        "💬 AI Assistant": "assistant",
        "📈 My Progress": "progress",
    }
    for label, page in pages.items():
        if st.sidebar.button(label, use_container_width=True, key=f"nav_{page}"):
            st.session_state.current_page = page
            st.rerun()
    if st.sidebar.button("🚪 Logout", use_container_width=True):
        clear_session()
        st.rerun()


def _admin_nav():
    st.sidebar.title("⚙️ Admin Hub")
    st.sidebar.write(f"🔑 {st.session_state.get('user_name', '')}")
    pages = {
        "📊 Overview": "admin_overview",
        "🎯 Competency Framework": "admin_competencies",
        "📚 Resource Catalog": "admin_catalog",
        "📄 Knowledge Base": "admin_documents",
        "✅ Quiz Review": "admin_quizzes",
        "📈 Analytics": "admin_analytics",
    }
    for label, page in pages.items():
        if st.sidebar.button(label, use_container_width=True, key=f"nav_{page}"):
            st.session_state.current_page = page
            st.rerun()
    if st.sidebar.button("🚪 Logout", use_container_width=True):
        clear_session()
        st.rerun()


# ── Page Router ───────────────────────────────────────────────────────────────

def main():
    if not st.session_state.access_token:
        from streamlit_app.pages import login_page
        login_page.render()
        return

    role = st.session_state.user_role
    page = st.session_state.current_page

    if role == "admin":
        _admin_nav()
    else:
        _learner_nav()

    if page in ("home", "dashboard"):
        from streamlit_app.pages import dashboard_page
        dashboard_page.render()
    elif page == "competencies":
        from streamlit_app.pages import competencies_page
        competencies_page.render()
    elif page == "assessment":
        from streamlit_app.pages import assessment_page
        assessment_page.render()
    elif page == "skill_gap":
        from streamlit_app.pages import skill_gap_page
        skill_gap_page.render()
    elif page == "pathway":
        from streamlit_app.pages import pathway_page
        pathway_page.render()
    elif page == "catalog":
        from streamlit_app.pages import catalog_page
        catalog_page.render()
    elif page == "quiz":
        from streamlit_app.pages import quiz_page
        quiz_page.render()
    elif page == "assistant":
        from streamlit_app.pages import assistant_page
        assistant_page.render()
    elif page == "progress":
        from streamlit_app.pages import progress_page
        progress_page.render()
    elif page == "admin_overview":
        from streamlit_app.pages import admin_overview_page
        admin_overview_page.render()
    else:
        st.info(f"Page '{page}' is coming soon.")


main()
