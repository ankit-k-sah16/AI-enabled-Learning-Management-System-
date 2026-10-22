"""
streamlit_app/pages/assessment_page.py — Competency assessment page.
"""

from __future__ import annotations

import streamlit as st
from streamlit_app.utils import api_get, api_post, proficiency_badge


def render():
    st.title("📝 Competency Assessment")
    st.write("Select a competency to assess, answer the questions, and receive your score.")

    # Load competencies
    competencies = api_get("/api/v1/competencies/") or []
    if not competencies:
        st.warning("No competencies available. Please contact an administrator.")
        return

    comp_map = {c["name"]: c["id"] for c in competencies}
    selected_name = st.selectbox("Select Competency", list(comp_map.keys()))
    selected_id = comp_map[selected_name]

    # Assessment flow
    if "assessment_attempt" not in st.session_state:
        st.session_state.assessment_attempt = None
    if "assessment_answers" not in st.session_state:
        st.session_state.assessment_answers = {}
    if "assessment_result" not in st.session_state:
        st.session_state.assessment_result = None

    attempt = st.session_state.assessment_attempt

    # ── Start Assessment ──────────────────────────────────────────────────────
    if attempt is None or st.session_state.assessment_result is not None:
        if st.session_state.assessment_result:
            result = st.session_state.assessment_result
            st.success(f"✅ Assessment complete!")

            col1, col2, col3 = st.columns(3)
            with col1:
                st.metric("Overall Score", f"{result['overall_score']:.1f}/100")
            with col2:
                st.metric("Proficiency", proficiency_badge(result['overall_proficiency']))
            with col3:
                st.metric("Correct Answers", f"{result['correct_answers']}/{result['total_questions']}")

            st.subheader("📊 Competency Breakdown")
            for cr in result.get("competency_results", []):
                with st.expander(f"{cr['competency_name']} — {cr['weighted_score']:.1f}/100"):
                    st.write(f"**Proficiency:** {proficiency_badge(cr['proficiency_level'])}")
                    st.write(f"**Correct:** {cr['correct_count']}/{cr['question_count']} questions")
                    st.progress(cr["weighted_score"] / 100)

            if result.get("warnings"):
                with st.expander("⚠️ Warnings"):
                    for w in result["warnings"]:
                        st.warning(w)

            col_a, col_b = st.columns(2)
            with col_a:
                if st.button("🔄 Retake Assessment", use_container_width=True):
                    st.session_state.assessment_attempt = None
                    st.session_state.assessment_answers = {}
                    st.session_state.assessment_result = None
                    st.rerun()
            with col_b:
                if st.button("🔍 View Skill Gaps", use_container_width=True, type="primary"):
                    st.session_state.assessment_result = None
                    st.session_state.current_page = "skill_gap"
                    st.rerun()
            return

        if st.button(f"▶️ Start Assessment: {selected_name}", type="primary", use_container_width=True):
            with st.spinner("Loading questions..."):
                result = api_post(f"/api/v1/assessments/start/{selected_id}")
            if result:
                st.session_state.assessment_attempt = result
                st.session_state.assessment_answers = {}
                st.session_state.assessment_result = None
                st.rerun()
        return

    # ── Show Questions ────────────────────────────────────────────────────────
    questions = attempt.get("questions", [])
    attempt_id = attempt.get("attempt_id")

    st.info(f"Attempt #{attempt.get('attempt_number', 1)} | {len(questions)} questions")
    st.progress(
        len(st.session_state.assessment_answers) / len(questions) if questions else 0,
        text=f"Answered: {len(st.session_state.assessment_answers)}/{len(questions)}"
    )

    OPTION_LABELS = {"A": "option_a", "B": "option_b", "C": "option_c", "D": "option_d"}

    for i, q in enumerate(questions):
        with st.container():
            st.markdown(f"**Q{i+1}.** {q['question_text']}")
            difficulty_badge = {"easy": "🟢", "medium": "🟡", "hard": "🔴"}.get(q.get("difficulty",""), "⚪")
            st.caption(f"{difficulty_badge} {q.get('difficulty','').capitalize()} | Weight: {q.get('weight', 1.0)}")

            options = {
                f"A: {q['option_a']}": "A",
                f"B: {q['option_b']}": "B",
                f"C: {q['option_c']}": "C",
                f"D: {q['option_d']}": "D",
            }

            current_ans = st.session_state.assessment_answers.get(q["id"])
            # Find label for current answer
            current_label = next(
                (label for label, val in options.items() if val == current_ans),
                None
            )

            selected = st.radio(
                f"q_{q['id']}",
                list(options.keys()),
                index=list(options.keys()).index(current_label) if current_label else None,
                key=f"ans_{q['id']}",
                label_visibility="collapsed",
            )
            if selected:
                st.session_state.assessment_answers[q["id"]] = options[selected]
            st.divider()

    # ── Submit ────────────────────────────────────────────────────────────────
    col1, col2 = st.columns([3, 1])
    with col2:
        if st.button("📤 Submit Assessment", type="primary", use_container_width=True):
            responses = [
                {"question_id": qid, "selected_answer": ans}
                for qid, ans in st.session_state.assessment_answers.items()
            ]
            unanswered = [q["id"] for q in questions if q["id"] not in st.session_state.assessment_answers]
            for qid in unanswered:
                responses.append({"question_id": qid, "selected_answer": None})

            with st.spinner("Scoring your assessment..."):
                result = api_post("/api/v1/assessments/submit", json={
                    "attempt_id": attempt_id,
                    "responses": responses,
                })
            if result:
                st.session_state.assessment_result = result
                st.session_state.assessment_attempt = None
                st.rerun()
    with col1:
        if st.button("❌ Cancel", use_container_width=True):
            st.session_state.assessment_attempt = None
            st.session_state.assessment_answers = {}
            st.rerun()
