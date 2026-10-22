"""
ai/quiz_generator.py — AI-Powered Quiz Generation using Groq.

Generates MCQ questions from document content.
Validates output with Pydantic before persistence.

Design:
- Generation, validation, and storage are separate concerns.
- All Pydantic models are strict.
- Retry logic is bounded (max 2 attempts to parse valid output).
- When Groq is unavailable, raises GroqServiceError — caller handles gracefully.
"""

from __future__ import annotations

import json
import logging
from typing import Optional

from pydantic import BaseModel, Field, field_validator, model_validator

from src.ai.groq_client import generate_json, GroqServiceError, GroqValidationError
from src.core.config import settings

logger = logging.getLogger(__name__)

VALID_ANSWERS = {"A", "B", "C", "D"}
VALID_DIFFICULTIES = {"easy", "medium", "hard"}


# ── Pydantic Schemas ──────────────────────────────────────────────────────────

class GeneratedQuestionSchema(BaseModel):
    """Strict schema for a single AI-generated question."""

    question_text: str = Field(..., min_length=10)
    option_a: str = Field(..., min_length=1)
    option_b: str = Field(..., min_length=1)
    option_c: str = Field(..., min_length=1)
    option_d: str = Field(..., min_length=1)
    correct_answer: str = Field(..., description="Must be A, B, C, or D")
    explanation: str = Field(..., min_length=10)
    difficulty: str = Field(default="medium")
    topic_tags: list[str] = Field(default_factory=list)
    competency_id: Optional[str] = None
    source_page: Optional[int] = None

    @field_validator("correct_answer", mode="before")
    @classmethod
    def _normalise_answer(cls, v: str) -> str:
        return v.strip().upper()

    @field_validator("difficulty", mode="before")
    @classmethod
    def _normalise_difficulty(cls, v: str) -> str:
        return v.strip().lower()

    @field_validator("correct_answer")
    @classmethod
    def _validate_answer(cls, v: str) -> str:
        if v not in VALID_ANSWERS:
            raise ValueError(f"correct_answer must be one of {VALID_ANSWERS}, got {v!r}")
        return v

    @field_validator("difficulty")
    @classmethod
    def _validate_difficulty(cls, v: str) -> str:
        if v not in VALID_DIFFICULTIES:
            raise ValueError(f"difficulty must be one of {VALID_DIFFICULTIES}, got {v!r}")
        return v

    @model_validator(mode="after")
    def _unique_options(self) -> "GeneratedQuestionSchema":
        opts = [self.option_a, self.option_b, self.option_c, self.option_d]
        if len(set(opts)) != 4:
            raise ValueError("All four answer options must be unique.")
        return self

    @model_validator(mode="after")
    def _answer_in_options(self) -> "GeneratedQuestionSchema":
        mapping = {
            "A": self.option_a,
            "B": self.option_b,
            "C": self.option_c,
            "D": self.option_d,
        }
        # This always holds by construction, but is checked to catch malformed output
        if self.correct_answer not in mapping:
            raise ValueError(f"correct_answer {self.correct_answer!r} not in options.")
        return self


class GeneratedQuizSchema(BaseModel):
    """Schema for the full quiz response from Groq."""
    title: str = Field(..., min_length=3)
    questions: list[GeneratedQuestionSchema] = Field(..., min_length=1)


# ── Prompt Templates ──────────────────────────────────────────────────────────

QUIZ_SYSTEM_PROMPT = """You are an expert educational content designer for an official statistics training platform.
Generate multiple-choice quiz questions strictly from the provided document content.
Do NOT invent facts, statistics, or claims not present in the document.
Output ONLY valid JSON matching the required schema.
Each question must have exactly 4 options (A, B, C, D), one correct answer, and a clear explanation."""

QUIZ_USER_TEMPLATE = """\
Document Content:
\"\"\"
{content}
\"\"\"

Generate {num_questions} multiple-choice questions from the above content.

Return a JSON object with this exact structure:
{{
  "title": "<quiz title>",
  "questions": [
    {{
      "question_text": "<clear question>",
      "option_a": "<option A>",
      "option_b": "<option B>",
      "option_c": "<option C>",
      "option_d": "<option D>",
      "correct_answer": "A" | "B" | "C" | "D",
      "explanation": "<why this answer is correct, referencing the document>",
      "difficulty": "easy" | "medium" | "hard",
      "topic_tags": ["tag1", "tag2"],
      "source_page": <page number or null>
    }}
  ]
}}

Requirements:
- Vary difficulty levels across questions.
- Make incorrect options plausible but clearly wrong.
- Keep explanations concise and factual.
- Use difficulty levels: easy, medium, hard.
- Do not repeat questions.
- Focus on {competency_context}.
"""


# ── Generator ─────────────────────────────────────────────────────────────────

def generate_quiz_from_content(
    content: str,
    num_questions: int = 5,
    competency_context: str = "key concepts in the document",
    document_title: str = "the provided document",
    competency_id: Optional[str] = None,
) -> GeneratedQuizSchema:
    """
    Generate a validated quiz from document text using Groq.

    Args:
        content:             Document text (should be pre-chunked to fit context).
        num_questions:       Number of questions to generate (1–20).
        competency_context:  Competency focus area for the prompt.
        document_title:      Source document title for the quiz title.
        competency_id:       Optional competency to tag on questions.

    Returns:
        GeneratedQuizSchema — validated, ready for admin review.

    Raises:
        GroqServiceError:    When Groq is unavailable.
        GroqValidationError: When output cannot be parsed into the schema.
    """
    num_questions = max(1, min(20, num_questions))

    # Truncate content to avoid exceeding model context
    max_content_chars = 8000
    if len(content) > max_content_chars:
        content = content[:max_content_chars] + "\n[Content truncated for length]"
        logger.info("Document content truncated to %d chars for quiz generation.", max_content_chars)

    user_prompt = QUIZ_USER_TEMPLATE.format(
        content=content,
        num_questions=num_questions,
        competency_context=competency_context,
    )

    last_error: Optional[Exception] = None
    for attempt in range(1, 3):   # max 2 parse attempts
        try:
            raw = generate_json(
                system_prompt=QUIZ_SYSTEM_PROMPT,
                user_prompt=user_prompt,
                model=settings.groq_model_primary,
                temperature=0.4,
                max_tokens=4096,
            )
            quiz = GeneratedQuizSchema.model_validate(raw)
            # Attach competency_id if provided
            if competency_id:
                for q in quiz.questions:
                    if not q.competency_id:
                        q.competency_id = competency_id
            logger.info(
                "Quiz generated: %d questions for '%s' (attempt %d).",
                len(quiz.questions), document_title, attempt,
            )
            return quiz
        except (GroqServiceError, GroqValidationError):
            raise   # Don't retry API / config errors
        except Exception as exc:
            last_error = exc
            logger.warning(
                "Quiz parse attempt %d failed: %s — %s", attempt, type(exc).__name__, str(exc)[:200]
            )

    raise GroqValidationError(
        f"Quiz generation failed after 2 parse attempts. Last error: {last_error}",
        original=last_error,
    )


def score_quiz_attempt(
    questions: list[dict],
    answers: dict[str, str],
) -> dict:
    """
    Score a learner's quiz attempt.

    Args:
        questions: List of dicts with {id, correct_answer, explanation, option_a/b/c/d}.
        answers:   Dict {question_id: selected_answer (A/B/C/D)}.

    Returns:
        {score_pct, correct, total, results: [{question_id, is_correct, explanation}]}
    """
    results = []
    correct_count = 0

    for q in questions:
        qid = q.get("id", "")
        selected = (answers.get(qid) or "").strip().upper()
        correct = (q.get("correct_answer") or "").strip().upper()
        is_correct = selected == correct and selected in VALID_ANSWERS
        if is_correct:
            correct_count += 1
        results.append({
            "question_id": qid,
            "selected": selected or None,
            "correct_answer": correct,
            "is_correct": is_correct,
            "explanation": q.get("explanation", ""),
        })

    total = len(questions)
    score_pct = round((correct_count / total * 100) if total > 0 else 0.0, 2)

    return {
        "score_pct": score_pct,
        "correct": correct_count,
        "total": total,
        "results": results,
    }
