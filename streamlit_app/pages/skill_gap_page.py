"""
streamlit_app/pages/skill_gap_page.py — Skill gap analysis page.
"""

from __future__ import annotations

import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from streamlit_app.utils import api_get, api_post


def render():
    st.title("🔍 Skill Gap Analysis")
    st.write("Compare your current competencies against a target job role to identify skill gaps.")

    roles = api_get("/api/v1/competencies/roles") or []
    if not roles:
        st.warning("No job roles found. Please contact an administrator.")
        return

    role_map = {r["name"]: r["id"] for r in roles}
    selected_role_name = st.selectbox("Target Job Role", list(role_map.keys()))
    selected_role_id = role_map[selected_role_name]

    if st.button("🔍 Analyse My Skill Gaps", type="primary", use_container_width=True):
        with st.spinner("Running skill gap analysis..."):
            report = api_get(f"/api/v1/gaps/analyse/{selected_role_id}")

        if not report:
            return

        # Normalize if API returned a list of gap items directly instead of a report dict
        if isinstance(report, list):
            total_req = len(report)
            assessed_list = [g for g in report if isinstance(g, dict) and g.get("is_assessed")]
            with_gap_list = [g for g in assessed_list if (g.get("gap_score") or 0) > 0]
            total_assessed = len(assessed_list)
            total_with_gap = len(with_gap_list)
            readiness = (
                round(((total_assessed - total_with_gap) / total_req) * 100, 1)
                if total_req > 0 else 0.0
            )
            report = {
                "summary": "Analysis complete.",
                "total_required": total_req,
                "total_assessed": total_assessed,
                "total_with_gap": total_with_gap,
                "total_no_gap": total_assessed - total_with_gap,
                "total_unassessed": total_req - total_assessed,
                "role_readiness_pct": readiness,
                "competency_gaps": report,
                "unassessed_competencies": [
                    g.get("competency_id", "") for g in report
                    if isinstance(g, dict) and not g.get("is_assessed")
                ],
                "warnings": [],
            }

        st.session_state["skill_gap_report"] = report
        st.session_state["analyzed_role_id"] = selected_role_id

    report = st.session_state.get("skill_gap_report")
    if not report or not isinstance(report, dict):
        return

    # ── Summary ───────────────────────────────────────────────────────────
    st.success(report.get("summary", "Analysis complete."))

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("Required Competencies", report.get("total_required", 0))
    with col2:
        st.metric("Assessed", report.get("total_assessed", 0))
    with col3:
        st.metric("With Gaps", report.get("total_with_gap", 0))
    with col4:
        readiness = report.get("role_readiness_pct", 0.0)
        st.metric("Role Readiness", f"{readiness:.0f}%")

    # ── Gap Bar Chart ──────────────────────────────────────────────────────
    gaps = report.get("competency_gaps", [])
    assessed_gaps = [g for g in gaps if isinstance(g, dict) and g.get("is_assessed")]

    if assessed_gaps:
        st.subheader("📊 Gap Overview")

        names = [g.get("competency_name", "") for g in assessed_gaps]
        current = [g.get("current_score") or 0 for g in assessed_gaps]
        required = [g.get("required_score", 0) for g in assessed_gaps]

        fig = go.Figure()
        fig.add_trace(go.Bar(
            name="Current Score",
            x=names,
            y=current,
            marker_color="#667eea",
        ))
        fig.add_trace(go.Bar(
            name="Required Score",
            x=names,
            y=required,
            marker_color="rgba(118,75,162,0.3)",
            marker_line_color="rgba(118,75,162,0.8)",
            marker_line_width=2,
        ))
        fig.update_layout(
            barmode="overlay",
            xaxis_tickangle=-30,
            yaxis=dict(range=[0, 110], title="Score (0-100)"),
            legend=dict(orientation="h"),
            height=380,
            margin=dict(l=40, r=20, t=20, b=60),
        )
        st.plotly_chart(fig, use_container_width=True)

    # ── Priority List ──────────────────────────────────────────────────────
    st.subheader("🎯 Priority Gaps (Ranked)")

    for gap in gaps:
        if not isinstance(gap, dict):
            continue
        is_assessed = gap.get("is_assessed", False)
        gap_score = gap.get("gap_score", 0.0)
        priority = gap.get("priority_score", 0.0)

        if gap_score <= 0 and is_assessed:
            icon = "✅"
        elif not is_assessed:
            icon = "❓"
        else:
            icon = "⚠️" if priority > 50 else "🔶"

        with st.expander(
            f"{icon} **Rank #{gap.get('priority_rank', '-') }** — {gap.get('competency_name', 'Competency')} "
            f"| Gap: {gap_score:.0f} pts | Priority: {priority:.1f}/100"
        ):
            col_a, col_b = st.columns(2)
            with col_a:
                st.write(f"**Current:** {gap['current_score']:.0f}/100" if is_assessed and gap.get('current_score') is not None else "**Current:** Not Assessed")
                st.write(f"**Required:** {gap.get('required_score', 0):.0f}/100")
            with col_b:
                st.write(f"**Proficiency (current):** {gap.get('proficiency_current', 'Unknown')}")
                st.write(f"**Proficiency (required):** {gap.get('proficiency_required', 'Unknown')}")
            st.info(gap.get("explanation", ""))

    # ── Unassessed ────────────────────────────────────────────────────────
    unassessed = report.get("unassessed_competencies", [])
    if unassessed:
        st.warning(f"⚠️ {len(unassessed)} competency(s) not yet assessed. Take assessments for a complete analysis.")

    st.divider()
    col_a, col_b = st.columns(2)
    with col_a:
        if st.button("📚 Get Recommendations", type="primary", use_container_width=True):
            st.session_state.selected_role_id = selected_role_id
            st.session_state.current_page = "pathway"
            st.rerun()
    with col_b:
        if st.button("📝 Take Assessment", use_container_width=True):
            st.session_state.current_page = "assessment"
            st.rerun()
