"""
tests/test_assessment_engine.py — Unit tests for the assessment scoring engine.

All tests use synthetic data — no database or API calls required.
"""

from __future__ import annotations

import pytest
from src.ai.assessment_engine import (
    score_question,
    aggregate_by_competency,
    compute_overall_score,
    score_assessment,
    QuestionResult,
    CompetencyResult,
    AssessmentResult,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────

QUESTIONS = [
    {"id": "q1", "competency_id": "C1", "correct_answer": "A", "weight": 1.0, "difficulty": "easy"},
    {"id": "q2", "competency_id": "C1", "correct_answer": "B", "weight": 2.0, "difficulty": "medium"},
    {"id": "q3", "competency_id": "C2", "correct_answer": "C", "weight": 1.0, "difficulty": "hard"},
    {"id": "q4", "competency_id": "C2", "correct_answer": "D", "weight": 1.5, "difficulty": "medium"},
]

ALL_CORRECT = [
    {"question_id": "q1", "selected_answer": "A"},
    {"question_id": "q2", "selected_answer": "B"},
    {"question_id": "q3", "selected_answer": "C"},
    {"question_id": "q4", "selected_answer": "D"},
]

ALL_WRONG = [
    {"question_id": "q1", "selected_answer": "B"},
    {"question_id": "q2", "selected_answer": "A"},
    {"question_id": "q3", "selected_answer": "A"},
    {"question_id": "q4", "selected_answer": "A"},
]

PARTIAL = [
    {"question_id": "q1", "selected_answer": "A"},   # correct, w=1
    {"question_id": "q2", "selected_answer": "A"},   # wrong,   w=2
    # q3 not answered (skipped)
    {"question_id": "q4", "selected_answer": "D"},   # correct, w=1.5
]


# ── score_question ─────────────────────────────────────────────────────────────

class TestScoreQuestion:
    def test_correct_answer_earns_full_weight(self):
        result = score_question("q1", "C1", 2.0, "A", "A")
        assert result.is_correct is True
        assert result.earned_points == 2.0
        assert result.max_points == 2.0

    def test_wrong_answer_earns_zero(self):
        result = score_question("q1", "C1", 2.0, "B", "A")
        assert result.is_correct is False
        assert result.earned_points == 0.0
        assert result.max_points == 2.0

    def test_skipped_answer_is_none(self):
        result = score_question("q1", "C1", 1.5, None, "A")
        assert result.is_correct is None
        assert result.selected_answer is None
        assert result.earned_points == 0.0
        assert result.max_points == 1.5

    def test_case_insensitive_matching(self):
        result = score_question("q1", "C1", 1.0, "a", "A")
        assert result.is_correct is True

    def test_zero_weight_clamped(self):
        result = score_question("q1", "C1", 0.0, "A", "A")
        assert result.max_points >= 0.01

    def test_negative_weight_clamped(self):
        result = score_question("q1", "C1", -5.0, "A", "A")
        assert result.max_points >= 0.01


# ── aggregate_by_competency ────────────────────────────────────────────────────

class TestAggregateByCompetency:
    def _make_results(self):
        return [
            score_question("q1", "C1", 1.0, "A", "A"),  # correct
            score_question("q2", "C1", 2.0, "B", "B"),  # correct
            score_question("q3", "C2", 1.0, "A", "C"),  # wrong
            score_question("q4", "C2", 1.5, None, "D"),  # skipped
        ]

    def test_competency_grouping(self):
        results = self._make_results()
        agg = aggregate_by_competency(results)
        assert "C1" in agg
        assert "C2" in agg

    def test_c1_all_correct(self):
        results = self._make_results()
        agg = aggregate_by_competency(results)
        c1 = agg["C1"]
        assert c1.correct_count == 2
        assert c1.weighted_score == pytest.approx(100.0)

    def test_c2_mixed(self):
        results = self._make_results()
        agg = aggregate_by_competency(results)
        c2 = agg["C2"]
        assert c2.question_count == 2
        assert c2.answered_count == 1
        assert c2.correct_count == 0
        assert c2.weighted_score == 0.0  # 0 earned / 2.5 max

    def test_confidence_partial_answer(self):
        results = self._make_results()
        agg = aggregate_by_competency(results)
        c2 = agg["C2"]
        assert 0.0 <= c2.confidence <= 1.0

    def test_competency_names_applied(self):
        results = self._make_results()
        names = {"C1": "Survey Design", "C2": "Data Quality"}
        agg = aggregate_by_competency(results, competency_names=names)
        assert agg["C1"].competency_name == "Survey Design"

    def test_empty_results(self):
        agg = aggregate_by_competency([])
        assert agg == {}


# ── compute_overall_score ─────────────────────────────────────────────────────

class TestComputeOverallScore:
    def test_all_correct(self):
        qrs = [score_question(f"q{i}", "C1", 1.0, "A", "A") for i in range(5)]
        assert compute_overall_score(qrs) == pytest.approx(100.0)

    def test_all_wrong(self):
        qrs = [score_question(f"q{i}", "C1", 1.0, "B", "A") for i in range(5)]
        assert compute_overall_score(qrs) == pytest.approx(0.0)

    def test_half_correct(self):
        qrs = [
            score_question("q1", "C1", 2.0, "A", "A"),  # correct
            score_question("q2", "C1", 2.0, "B", "A"),  # wrong
        ]
        assert compute_overall_score(qrs) == pytest.approx(50.0)

    def test_empty_list(self):
        assert compute_overall_score([]) == 0.0


# ── score_assessment ──────────────────────────────────────────────────────────

class TestScoreAssessment:
    def test_perfect_score(self):
        result = score_assessment("att1", "learner1", ALL_CORRECT, QUESTIONS)
        assert result.overall_score == pytest.approx(100.0)
        assert result.overall_proficiency == "Expert"
        assert result.correct_answers == 4

    def test_zero_score(self):
        result = score_assessment("att1", "learner1", ALL_WRONG, QUESTIONS)
        assert result.overall_score == pytest.approx(0.0)
        assert result.overall_proficiency == "Beginner"
        assert result.correct_answers == 0

    def test_partial_responses(self):
        result = score_assessment("att1", "learner1", PARTIAL, QUESTIONS)
        # q1 correct (w=1), q2 wrong (w=2), q3 skipped (w=1), q4 correct (w=1.5)
        # earned = 1.0 + 0 + 0 + 1.5 = 2.5; max = 1+2+1+1.5 = 5.5
        expected = round(2.5 / 5.5 * 100, 2)
        assert result.overall_score == pytest.approx(expected, abs=0.1)
        assert result.answered_questions == 3  # q1, q2, q4 answered; q3 skipped

    def test_unanswered_questions(self):
        # Only answer q1; rest unanswered
        responses = [{"question_id": "q1", "selected_answer": "A"}]
        result = score_assessment("att1", "learner1", responses, QUESTIONS)
        assert result.total_questions == 4
        assert result.answered_questions == 1

    def test_unknown_question_in_responses(self):
        responses = ALL_CORRECT + [{"question_id": "q999", "selected_answer": "A"}]
        result = score_assessment("att1", "learner1", responses, QUESTIONS)
        assert any("q999" in w for w in result.warnings)

    def test_duplicate_question_in_questions(self):
        dup_questions = QUESTIONS + [QUESTIONS[0]]
        result = score_assessment("att1", "learner1", ALL_CORRECT, dup_questions)
        assert any("Duplicate" in w for w in result.warnings)

    def test_per_competency_breakdown(self):
        result = score_assessment("att1", "learner1", ALL_CORRECT, QUESTIONS)
        comp_ids = {cr.competency_id for cr in result.competency_results}
        assert "C1" in comp_ids
        assert "C2" in comp_ids

    def test_empty_responses(self):
        result = score_assessment("att1", "learner1", [], QUESTIONS)
        assert result.overall_score == 0.0
        assert result.correct_answers == 0

    def test_empty_questions(self):
        result = score_assessment("att1", "learner1", [], [])
        assert result.total_questions == 0

    def test_json_serialisation(self):
        result = score_assessment("att1", "learner1", ALL_CORRECT, QUESTIONS)
        json_str = result.to_json()
        import json
        data = json.loads(json_str)
        assert data["overall_score"] == pytest.approx(100.0)
        assert "competency_results" in data
