"""
streamlit_app/pages/login_page.py — Login and registration page.
"""

from __future__ import annotations

import streamlit as st
import requests
from streamlit_app.utils import api_url, api_post


def render():
    st.markdown("""
    <style>
    .hero-title {
        font-size: 2.8rem;
        font-weight: 800;
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        text-align: center;
        margin-bottom: 0;
    }
    .hero-sub {
        text-align: center;
        color: #6b7280;
        font-size: 1.1rem;
        margin-bottom: 2rem;
    }
    </style>
    """, unsafe_allow_html=True)

    st.markdown('<div class="hero-title">🎓 AI Skill Intelligence Platform</div>', unsafe_allow_html=True)
    st.markdown('<div class="hero-sub">SIH 2026 | PS 26101 — Official Statistics Competency Development</div>', unsafe_allow_html=True)

    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        tab_login, tab_register = st.tabs(["🔐 Login", "📝 Register"])

        with tab_login:
            with st.form("login_form"):
                email = st.text_input("Email", placeholder="your@email.com")
                password = st.text_input("Password", type="password")
                submitted = st.form_submit_button("Login", use_container_width=True, type="primary")

            if submitted:
                if not email or not password:
                    st.error("Please enter both email and password.")
                else:
                    try:
                        resp = requests.post(
                            api_url("/api/v1/auth/token"),
                            data={"username": email, "password": password},
                            timeout=10,
                        )
                        if resp.ok:
                            data = resp.json()
                            st.session_state.access_token = data["access_token"]
                            st.session_state.user_id = data["user_id"]
                            st.session_state.user_role = data["role"]
                            st.session_state.user_name = data["full_name"]
                            st.session_state.current_page = "dashboard"
                            st.success(f"Welcome back, {data['full_name']}!")
                            st.rerun()
                        else:
                            detail = resp.json().get("detail", "Login failed.")
                            st.error(f"❌ {detail}")
                    except requests.ConnectionError:
                        st.error("⚠️ Cannot connect to the API server. Please start FastAPI first.")

        with tab_register:
            with st.form("register_form"):
                full_name = st.text_input("Full Name", placeholder="Your full name")
                reg_email = st.text_input("Email", placeholder="your@email.com", key="reg_email")
                reg_password = st.text_input("Password (min 8 chars)", type="password", key="reg_pw")
                reg_submitted = st.form_submit_button("Create Account", use_container_width=True, type="primary")

            if reg_submitted:
                if len(reg_password) < 8:
                    st.error("Password must be at least 8 characters.")
                else:
                    result = api_post("/api/v1/auth/register", json={
                        "email": reg_email,
                        "password": reg_password,
                        "full_name": full_name,
                    })
                    if result:
                        st.success("✅ Account created! Please login above.")

        st.divider()
        st.caption("💡 Demo credentials — Admin: admin@lms.local / (see .env ADMIN_PASSWORD)")
