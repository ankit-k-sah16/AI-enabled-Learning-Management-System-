"""
tests/test_quiz_generator.py — Unit tests for quiz generation validation logic.

Tests that don't require Groq:
- Pydantic schema validation.
- score_quiz_attempt() function.
- Schema rejection of invalid data.

Groq-dependent tests are marked with @pytest.mark.integration
and require GROQ_API_KEY to be set.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.ai.quiz_generator import (
    GeneratedQuestionSchema,
    GeneratedQuizSchema,
    score_quiz_attempt,
)


# ── Valid schema fixtures ─────────────────────────────────────────────────────

VALID_QUESTION = {
    "question_text": "Which sampling method divides the population into subgroups before sampling?",
    "option_a": "Simple random sampling",
    "option_b": "Stratified random sampling",
    "option_c": "Convenience sampling",
    "option_d": "Systematic sampling",
    "correct_answer": "B",
    "explanation": "Stratified sampling divides into strata before sampling each stratum.",
    "difficulty": "medium",
    "topic_tags": ["sampling", "survey design"],
}


# ── GeneratedQuestionSchema ───────────────────────────────────────────────────

class TestGeneratedQuestionSchema:
    def test_valid_question_passes(self):
        q = GeneratedQuestionSchema.model_validate(VALID_QUESTION)
        assert q.correct_answer == "B"
        assert q.difficulty == "medium"

    def test_case_insensitive_answer(self):
        data = {**VALID_QUESTION, "correct_answer": "b"}
        q = GeneratedQuestionSchema.model_validate(data)
        assert q.correct_answer == "B"

    def test_case_insensitive_difficulty(self):
        data = {**VALID_QUESTION, "difficulty": "HARD"}
        q = GeneratedQuestionSchema.model_validate(data)
        assert q.difficulty == "hard"

    def test_invalid_answer_rejected(self):
        data = {**VALID_QUESTION, "correct_answer": "E"}
        with pytest.raises(ValidationError):
            GeneratedQuestionSchema.model_validate(data)

    def test_invalid_difficulty_rejected(self):
        data = {**VALID_QUESTION, "difficulty": "expert"}
        with pytest.raises(ValidationError):
            GeneratedQuestionSchema.model_validate(data)

    def test_duplicate_options_rejected(self):
        data = {**VALID_QUESTION, "option_b": VALID_QUESTION["option_a"]}  # same as A
        with pytest.raises(ValidationError):
            GeneratedQuestionSchema.model_validate(data)

    def test_short_question_text_rejected(self):
        data = {**VALID_QUESTION, "question_text": "Short"}
        with pytest.raises(ValidationError):
            GeneratedQuestionSchema.model_validate(data)

    def test_empty_explanation_rejected(self):
        data = {**VALID_QUESTION, "explanation": ""}
        with pytest.raises(ValidationError):
            GeneratedQuestionSchema.model_validate(data)

    def test_optional_fields_default(self):
        q = GeneratedQuestionSchema.model_validate(VALID_QUESTION)
        assert q.competency_id is None
        assert q.source_page is None
        assert isinstance(q.topic_tags, list)


# ── GeneratedQuizSchema ───────────────────────────────────────────────────────

class TestGeneratedQuizSchema:
    def test_valid_quiz_passes(self):
        quiz_data = {
            "title": "Survey Methods Quiz",
            "questions": [VALID_QUESTION],
        }
        quiz = GeneratedQuizSchema.model_validate(quiz_data)
        assert quiz.title == "Survey Methods Quiz"
        assert len(quiz.questions) == 1

    def test_empty_questions_rejected(self):
        with pytest.raises(ValidationError):
            GeneratedQuizSchema.model_validate({"title": "Test", "questions": []})

    def test_short_title_rejected(self):
        with pytest.raises(ValidationError):
            GeneratedQuizSchema.model_validate({"title": "X", "questions": [VALID_QUESTION]})


# ── score_quiz_attempt ────────────────────────────────────────────────────────

class TestScoreQuizAttempt:
    def _questions(self):
        return [
            {
                "id": "q1",
                "correct_answer": "A",
                "explanation": "Explanation A",
                "option_a": "Opt1", "option_b": "Opt2",
                "option_c": "Opt3", "option_d": "Opt4",
            },
            {
                "id": "q2",
                "correct_answer": "B",
                "explanation": "Explanation B",
                "option_a": "Opt1", "option_b": "Opt2",
                "option_c": "Opt3", "option_d": "Opt4",
            },
            {
                "id": "q3",
                "correct_answer": "C",
                "explanation": "Explanation C",
                "option_a": "Opt1", "option_b": "Opt2",
                "option_c": "Opt3", "option_d": "Opt4",
            },
        ]

    def test_all_correct(self):
        result = score_quiz_attempt(
            self._questions(),
            {"q1": "A", "q2": "B", "q3": "C"},
        )
        assert result["score_pct"] == pytest.approx(100.0)
        assert result["correct"] == 3

    def test_all_wrong(self):
        result = score_quiz_attempt(
            self._questions(),
            {"q1": "D", "q2": "D", "q3": "D"},
        )
        assert result["score_pct"] == pytest.approx(0.0)

    def test_partial_score(self):
        result = score_quiz_attempt(
            self._questions(),
            {"q1": "A", "q2": "D", "q3": "D"},  # 1 correct
        )
        assert result["score_pct"] == pytest.approx(33.33, abs=0.1)

    def test_unanswered_question(self):
        result = score_quiz_attempt(
            self._questions(),
            {"q1": "A"},  # q2, q3 not answered
        )
        assert result["total"] == 3
        assert result["correct"] == 1

    def test_empty_quiz(self):
        result = score_quiz_attempt([], {})
        assert result["score_pct"] == pytest.approx(0.0)

    def test_explanation_included(self):
        result = score_quiz_attempt(self._questions(), {"q1": "A"})
        q1_result = next(r for r in result["results"] if r["question_id"] == "q1")
        assert "Explanation A" in q1_result["explanation"]

    def test_case_insensitive_scoring(self):
        result = score_quiz_attempt(
            self._questions(),
            {"q1": "a"},  # lowercase answer
        )
        assert result["results"][0]["is_correct"] is True
