"""
streamlit_app/pages/dashboard_page.py — Learner dashboard.
"""

from __future__ import annotations

import plotly.graph_objects as go
import streamlit as st

from streamlit_app.utils import api_get, proficiency_badge


def render():
    st.title("🏠 My Dashboard")
    st.write(f"Welcome, **{st.session_state.get('user_name', 'Learner')}**! Here's your learning overview.")

    # Load competency scores
    scores = api_get("/api/v1/assessments/scores/me") or []
    roles = api_get("/api/v1/competencies/roles") or []

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("Competencies Assessed", len(scores))
    with col2:
        assessed_scores = [s["score"] for s in scores if s.get("score") is not None]
        avg = round(sum(assessed_scores) / len(assessed_scores), 1) if assessed_scores else 0
        st.metric("Average Score", f"{avg}/100")
    with col3:
        expert_count = sum(1 for s in scores if s.get("proficiency_level") == "Expert")
        st.metric("Expert Level", expert_count)
    with col4:
        st.metric("Job Roles Available", len(roles))

    st.divider()

    if scores:
        st.subheader("📊 Competency Radar")
        comp_names = [s.get("competency_name", s["competency_id"])[:20] for s in scores]
        comp_scores = [s.get("score") or 0 for s in scores]

        fig = go.Figure()
        fig.add_trace(go.Scatterpolar(
            r=comp_scores + [comp_scores[0]],
            theta=comp_names + [comp_names[0]],
            fill="toself",
            name="Current Score",
            line=dict(color="#667eea"),
            fillcolor="rgba(102,126,234,0.2)",
        ))
        fig.update_layout(
            polar=dict(radialaxis=dict(visible=True, range=[0, 100])),
            showlegend=False,
            height=400,
            margin=dict(l=60, r=60, t=40, b=40),
        )
        st.plotly_chart(fig, use_container_width=True)

        st.subheader("📋 Competency Scores")
        for s in sorted(scores, key=lambda x: x.get("score") or 0, reverse=True):
            score_val = s.get("score")
            if score_val is not None:
                pct = int(score_val)
                col_name, col_level, col_bar = st.columns([3, 1.5, 3])
                with col_name:
                    st.write(s.get("competency_name", s["competency_id"]))
                with col_level:
                    st.write(proficiency_badge(s.get("proficiency_level", "Unknown")))
                with col_bar:
                    st.progress(pct / 100, text=f"{pct}/100")
    else:
        st.info("📝 No assessments completed yet. Go to **Take Assessment** to get started!")

    st.divider()
    col_a, col_b = st.columns(2)
    with col_a:
        if st.button("📝 Take Assessment", use_container_width=True, type="primary"):
            st.session_state.current_page = "assessment"
            st.rerun()
    with col_b:
        if st.button("🔍 View Skill Gaps", use_container_width=True):
            st.session_state.current_page = "skill_gap"
            st.rerun()
