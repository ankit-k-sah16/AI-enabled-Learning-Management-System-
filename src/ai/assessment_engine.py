"""
ai/assessment_engine.py — Competency Assessment Scoring Engine.

Responsibilities:
- Calculate weighted scores from learner responses.
- Aggregate scores per competency.
- Map scores to proficiency levels.
- Produce an explainable score breakdown.

Design notes:
- Rules-based; no ML model required for baseline scoring.
- All formulas are documented inline.
- Designed so an ML model can later replace score_assessment().
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Optional

from src.core.config import settings


# ── Data Contracts ────────────────────────────────────────────────────────────

@dataclass
class QuestionResult:
    """Result for a single assessment question."""
    question_id: str
    competency_id: str
    weight: float
    selected_answer: Optional[str]   # None if skipped
    correct_answer: str
    is_correct: Optional[bool]        # None if skipped
    earned_points: float              # weight if correct, else 0
    max_points: float                 # weight (regardless of answer)
    difficulty: str = "medium"


@dataclass
class CompetencyResult:
    """
    Aggregated result for a single competency in an assessment.

    Scoring formula:
        weighted_score = (sum of earned_points / sum of max_points) × 100

    Confidence:
        confidence = min(1.0, answered_count / FULL_CONFIDENCE_THRESHOLD)
        Reflects that fewer questions yield less reliable scores.
    """
    FULL_CONFIDENCE_THRESHOLD: int = field(default=10, init=False, repr=False)

    competency_id: str
    competency_name: str = ""
    question_count: int = 0
    answered_count: int = 0
    correct_count: int = 0
    total_earned_points: float = 0.0
    total_max_points: float = 0.0
    weighted_score: float = 0.0      # 0–100
    proficiency_level: str = "Unknown"
    confidence: float = 0.0          # 0–1

    def compute(self) -> "CompetencyResult":
        """Compute derived fields. Call after populating raw tallies."""
        if self.total_max_points > 0:
            self.weighted_score = round(
                (self.total_earned_points / self.total_max_points) * 100.0, 2
            )
        else:
            self.weighted_score = 0.0

        self.proficiency_level = settings.score_to_proficiency(self.weighted_score)

        if self.question_count > 0:
            answered_ratio = self.answered_count / self.question_count
            volume_factor = min(1.0, self.answered_count / self.FULL_CONFIDENCE_THRESHOLD)
            self.confidence = round(answered_ratio * volume_factor, 4)
        else:
            self.confidence = 0.0

        return self


@dataclass
class AssessmentResult:
    """
    Full result for a completed assessment attempt.

    Contains per-competency breakdowns and overall summary.
    """
    attempt_id: str
    learner_id: str
    job_role_id: Optional[str]
    completed_at: datetime
    overall_score: float                              # weighted average across all questions
    overall_proficiency: str
    total_questions: int
    answered_questions: int
    correct_answers: int
    competency_results: list[CompetencyResult] = field(default_factory=list)
    question_results: list[QuestionResult] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        """Serialise to JSON-compatible dict for storage."""
        d = asdict(self)
        d["completed_at"] = self.completed_at.isoformat()
        return d

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), default=str, indent=2)


# ── Core Scoring Functions ────────────────────────────────────────────────────

def score_question(
    question_id: str,
    competency_id: str,
    weight: float,
    selected_answer: Optional[str],
    correct_answer: str,
    difficulty: str = "medium",
) -> QuestionResult:
    """
    Score a single question response.

    Rules:
    - Skipped / None → not counted as correct; weight is still included in max_points.
    - Invalid answer strings are treated as incorrect.
    - Weights must be > 0; clamped to 0.01 if not.
    """
    weight = max(0.01, weight)
    ca = correct_answer.strip().upper() if correct_answer else ""

    if selected_answer is None:
        return QuestionResult(
            question_id=question_id,
            competency_id=competency_id,
            weight=weight,
            selected_answer=None,
            correct_answer=ca,
            is_correct=None,
            earned_points=0.0,
            max_points=weight,
            difficulty=difficulty,
        )

    sa = selected_answer.strip().upper()
    is_correct = sa == ca
    earned = weight if is_correct else 0.0

    return QuestionResult(
        question_id=question_id,
        competency_id=competency_id,
        weight=weight,
        selected_answer=sa,
        correct_answer=ca,
        is_correct=is_correct,
        earned_points=earned,
        max_points=weight,
        difficulty=difficulty,
    )


def aggregate_by_competency(
    question_results: list[QuestionResult],
    competency_names: Optional[dict[str, str]] = None,
) -> dict[str, CompetencyResult]:
    """
    Group question results by competency and compute CompetencyResult per group.

    Args:
        question_results: List of individual question results.
        competency_names:  Optional {competency_id: name} lookup.

    Returns:
        Dict mapping competency_id → CompetencyResult.
    """
    cmap: dict[str, CompetencyResult] = {}

    for qr in question_results:
        cid = qr.competency_id
        if cid not in cmap:
            cmap[cid] = CompetencyResult(
                competency_id=cid,
                competency_name=(competency_names or {}).get(cid, cid),
            )

        cr = cmap[cid]
        cr.question_count += 1
        cr.total_max_points += qr.max_points

        if qr.selected_answer is not None:
            cr.answered_count += 1
            cr.total_earned_points += qr.earned_points
            if qr.is_correct:
                cr.correct_count += 1

    for cr in cmap.values():
        cr.compute()

    return cmap


def compute_overall_score(question_results: list[QuestionResult]) -> float:
    """
    Overall weighted score across all questions.

    Formula:
        overall = (Σ earned_points / Σ max_points) × 100
    """
    total_earned = sum(qr.earned_points for qr in question_results)
    total_max = sum(qr.max_points for qr in question_results)
    if total_max <= 0:
        return 0.0
    return round((total_earned / total_max) * 100.0, 2)


def score_assessment(
    attempt_id: str,
    learner_id: str,
    responses: list[dict],
    questions: list[dict],
    job_role_id: Optional[str] = None,
    competency_names: Optional[dict[str, str]] = None,
) -> AssessmentResult:
    """
    Score a complete assessment attempt.

    Args:
        attempt_id:       ID of the AssessmentAttempt record.
        learner_id:       ID of the learner.
        responses:        List of dicts: {question_id, selected_answer}.
        questions:        List of dicts: {id, competency_id, correct_answer,
                          weight, difficulty}.
        job_role_id:      Optional role context.
        competency_names: Optional competency name lookup.

    Returns:
        AssessmentResult with full breakdown.

    Edge cases handled:
    - Question in responses not in questions dict → skipped with warning.
    - Question in questions not in responses → treated as skipped (None).
    - Duplicate question_id in questions → last entry wins, with warning.
    - Weight ≤ 0 → clamped to 0.01.
    """
    warnings: list[str] = []

    # Build question lookup
    question_lookup: dict[str, dict] = {}
    for q in questions:
        qid = q.get("id") or q.get("question_id", "")
        if qid in question_lookup:
            warnings.append(f"Duplicate question_id {qid!r} found; using last entry.")
        question_lookup[qid] = q

    # Build response lookup
    response_lookup: dict[str, Optional[str]] = {}
    for r in responses:
        qid = r.get("question_id", "")
        ans = r.get("selected_answer")
        if qid not in question_lookup:
            warnings.append(
                f"Response for unknown question_id {qid!r} ignored."
            )
            continue
        response_lookup[qid] = ans

    # Score every question in the question set
    question_results: list[QuestionResult] = []
    for qid, q in question_lookup.items():
        selected = response_lookup.get(qid, None)  # None = not answered
        qr = score_question(
            question_id=qid,
            competency_id=q.get("competency_id", "unknown"),
            weight=float(q.get("weight", 1.0)),
            selected_answer=selected,
            correct_answer=q.get("correct_answer", ""),
            difficulty=q.get("difficulty", "medium"),
        )
        question_results.append(qr)

    competency_results_map = aggregate_by_competency(question_results, competency_names)
    overall_score = compute_overall_score(question_results)
    answered_count = sum(1 for qr in question_results if qr.selected_answer is not None)
    correct_count = sum(1 for qr in question_results if qr.is_correct is True)

    return AssessmentResult(
        attempt_id=attempt_id,
        learner_id=learner_id,
        job_role_id=job_role_id,
        completed_at=datetime.now(timezone.utc),
        overall_score=overall_score,
        overall_proficiency=settings.score_to_proficiency(overall_score),
        total_questions=len(question_results),
        answered_questions=answered_count,
        correct_answers=correct_count,
        competency_results=list(competency_results_map.values()),
        question_results=question_results,
        warnings=warnings,
    )
