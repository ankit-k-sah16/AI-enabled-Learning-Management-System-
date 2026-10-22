"""
src/api/assessment_router.py — Assessment and scoring endpoints.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from src.db.session import get_db
from src.db.models import (
    AssessmentAttempt, AssessmentQuestion, LearnerResponse,
    CompetencyScore, ProficiencyLevel, Competency,
)
from src.ai.assessment_engine import score_assessment
from src.api.auth_router import get_current_user
from src.core.config import settings

router = APIRouter()


# ── Pydantic Models ───────────────────────────────────────────────────────────

class QuestionOut(BaseModel):
    id: str
    competency_id: str
    question_text: str
    option_a: str
    option_b: str
    option_c: str
    option_d: str
    difficulty: str
    weight: float


class SubmitAssessmentRequest(BaseModel):
    attempt_id: str
    responses: list[dict]   # [{question_id: str, selected_answer: str|None}]


class AssessmentResultOut(BaseModel):
    attempt_id: str
    overall_score: float
    overall_proficiency: str
    total_questions: int
    answered_questions: int
    correct_answers: int
    competency_results: list[dict]
    warnings: list[str]


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/questions/{competency_id}", response_model=list[QuestionOut])
def get_questions_for_competency(
    competency_id: str,
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    """Return active assessment questions for a competency."""
    questions = (
        db.query(AssessmentQuestion)
        .filter(
            AssessmentQuestion.competency_id == competency_id,
            AssessmentQuestion.is_active == True,
        )
        .all()
    )
    if not questions:
        raise HTTPException(status_code=404, detail="No questions found for this competency.")
    return [
        QuestionOut(
            id=q.id,
            competency_id=q.competency_id,
            question_text=q.question_text,
            option_a=q.option_a,
            option_b=q.option_b,
            option_c=q.option_c,
            option_d=q.option_d,
            difficulty=q.difficulty.value,
            weight=q.weight,
        )
        for q in questions
    ]


@router.post("/start/{competency_id}")
def start_assessment(
    competency_id: str,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Create a new assessment attempt record and return questions."""
    # Count existing attempts for this competency
    prev_attempts = (
        db.query(AssessmentAttempt)
        .filter(
            AssessmentAttempt.learner_id == current_user.id,
            AssessmentAttempt.competency_id == competency_id,
        )
        .count()
    )

    attempt = AssessmentAttempt(
        learner_id=current_user.id,
        competency_id=competency_id,
        attempt_number=prev_attempts + 1,
    )
    db.add(attempt)
    db.commit()
    db.refresh(attempt)

    questions = (
        db.query(AssessmentQuestion)
        .filter(
            AssessmentQuestion.competency_id == competency_id,
            AssessmentQuestion.is_active == True,
        )
        .all()
    )

    return {
        "attempt_id": attempt.id,
        "attempt_number": attempt.attempt_number,
        "questions": [
            {
                "id": q.id,
                "question_text": q.question_text,
                "option_a": q.option_a,
                "option_b": q.option_b,
                "option_c": q.option_c,
                "option_d": q.option_d,
                "difficulty": q.difficulty.value,
                "weight": q.weight,
            }
            for q in questions
        ],
    }


@router.post("/submit", response_model=AssessmentResultOut)
def submit_assessment(
    body: SubmitAssessmentRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Score a submitted assessment attempt."""
    attempt = db.query(AssessmentAttempt).filter(
        AssessmentAttempt.id == body.attempt_id,
        AssessmentAttempt.learner_id == current_user.id,
    ).first()

    if not attempt:
        raise HTTPException(status_code=404, detail="Assessment attempt not found.")
    if attempt.is_complete:
        raise HTTPException(status_code=400, detail="This attempt has already been submitted.")

    # Fetch questions
    questions = (
        db.query(AssessmentQuestion)
        .filter(AssessmentQuestion.competency_id == attempt.competency_id)
        .all()
    )
    q_dicts = [
        {
            "id": q.id,
            "competency_id": q.competency_id,
            "correct_answer": q.correct_answer,
            "weight": q.weight,
            "difficulty": q.difficulty.value,
        }
        for q in questions
    ]
    comp_names = {
        q.competency_id: q.competency.name
        for q in questions
        if q.competency
    }

    # Score
    result = score_assessment(
        attempt_id=attempt.id,
        learner_id=current_user.id,
        responses=body.responses,
        questions=q_dicts,
        competency_names=comp_names,
    )

    # Persist responses
    for resp_data in body.responses:
        qid = resp_data.get("question_id", "")
        q = next((q for q in questions if q.id == qid), None)
        if not q:
            continue
        selected = resp_data.get("selected_answer")
        is_correct = (
            selected.strip().upper() == q.correct_answer.upper()
            if selected else None
        )
        lr = LearnerResponse(
            attempt_id=attempt.id,
            question_id=qid,
            selected_answer=selected,
            is_correct=is_correct,
        )
        db.add(lr)

    # Update attempt
    attempt.is_complete = True
    attempt.completed_at = result.completed_at
    attempt.raw_score = result.overall_score
    attempt.weighted_score = result.overall_score
    attempt.total_questions = result.total_questions
    attempt.answered_questions = result.answered_questions
    attempt.correct_answers = result.correct_answers
    attempt.score_breakdown = result.to_json()

    # Upsert competency score
    for cr in result.competency_results:
        existing = db.query(CompetencyScore).filter_by(
            learner_id=current_user.id,
            competency_id=cr.competency_id,
        ).first()
        try:
            level = ProficiencyLevel(cr.proficiency_level)
        except ValueError:
            level = ProficiencyLevel.UNKNOWN

        if existing:
            existing.score = cr.weighted_score
            existing.proficiency_level = level
            existing.attempt_id = attempt.id
            existing.confidence = cr.confidence
            existing.assessed_at = result.completed_at
        else:
            cs = CompetencyScore(
                learner_id=current_user.id,
                competency_id=cr.competency_id,
                score=cr.weighted_score,
                proficiency_level=level,
                attempt_id=attempt.id,
                confidence=cr.confidence,
                assessed_at=result.completed_at,
            )
            db.add(cs)

    db.commit()

    return AssessmentResultOut(
        attempt_id=result.attempt_id,
        overall_score=result.overall_score,
        overall_proficiency=result.overall_proficiency,
        total_questions=result.total_questions,
        answered_questions=result.answered_questions,
        correct_answers=result.correct_answers,
        competency_results=[
            {
                "competency_id": cr.competency_id,
                "competency_name": cr.competency_name,
                "weighted_score": cr.weighted_score,
                "proficiency_level": cr.proficiency_level,
                "correct_count": cr.correct_count,
                "question_count": cr.question_count,
                "confidence": cr.confidence,
            }
            for cr in result.competency_results
        ],
        warnings=result.warnings,
    )


@router.get("/scores/me")
def my_competency_scores(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Return current user's competency scores."""
    scores = db.query(CompetencyScore).filter(
        CompetencyScore.learner_id == current_user.id
    ).all()
    return [
        {
            "competency_id": s.competency_id,
            "competency_name": s.competency.name if s.competency else "",
            "score": s.score,
            "proficiency_level": s.proficiency_level.value,
            "confidence": s.confidence,
            "assessed_at": s.assessed_at.isoformat() if s.assessed_at else None,
        }
        for s in scores
    ]
