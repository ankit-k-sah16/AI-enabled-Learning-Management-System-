"""
src/api/quiz_router.py — Quiz generation and quiz-taking endpoints.

Separates:
- Quiz generation (Groq, admin-triggered)
- Quiz review/publish (admin workflow)
- Quiz attempt (learner)
- Quiz scoring
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from src.db.session import get_db
from src.db.models import (
    GeneratedQuiz, GeneratedQuestion, QuizAttempt,
    QuizStatus, QuestionDifficulty, User,
)
from src.api.auth_router import get_current_user, require_admin
from src.ai.quiz_generator import generate_quiz_from_content, score_quiz_attempt
from src.ai.groq_client import GroqServiceError, GroqNotConfiguredError
from src.core.config import settings

router = APIRouter()
logger = logging.getLogger(__name__)


# ── Pydantic Models ───────────────────────────────────────────────────────────

class GenerateQuizRequest(BaseModel):
    content: str
    num_questions: int = 5
    competency_context: str = "key concepts in the document"
    document_title: str = "the provided document"
    competency_id: Optional[str] = None
    document_id: Optional[str] = None


class QuizQuestionOut(BaseModel):
    id: str
    question_text: str
    option_a: str
    option_b: str
    option_c: str
    option_d: str
    difficulty: str
    topic_tags: list[str]
    competency_id: Optional[str]
    source_page: Optional[int]


class QuizQuestionWithAnswerOut(QuizQuestionOut):
    correct_answer: str
    explanation: str


class QuizOut(BaseModel):
    id: str
    title: str
    status: str
    total_questions: int
    competency_id: Optional[str]
    created_at: str


class SubmitQuizRequest(BaseModel):
    quiz_id: str
    answers: dict  # {question_id: selected_answer (A/B/C/D)}


class QuizResultOut(BaseModel):
    attempt_id: str
    score_pct: float
    correct: int
    total: int
    results: list[dict]


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/generate", status_code=201)
def generate_quiz(
    body: GenerateQuizRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """
    Generate a quiz from document content using Groq.
    Saves as DRAFT — requires admin review before publishing.
    """
    if not settings.groq_available:
        raise HTTPException(
            status_code=503,
            detail="Groq is not configured. Set GROQ_API_KEY to enable quiz generation.",
        )

    try:
        quiz_schema = generate_quiz_from_content(
            content=body.content,
            num_questions=body.num_questions,
            competency_context=body.competency_context,
            document_title=body.document_title,
            competency_id=body.competency_id,
        )
    except GroqNotConfiguredError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except GroqServiceError as exc:
        raise HTTPException(status_code=502, detail=f"Groq error: {str(exc)[:300]}")
    except Exception as exc:
        logger.error("Quiz generation error: %s", str(exc)[:300])
        raise HTTPException(status_code=500, detail="Quiz generation failed. See server logs.")

    # Persist to DB as DRAFT
    quiz = GeneratedQuiz(
        title=quiz_schema.title,
        document_id=body.document_id,
        created_by_id=current_user.id,
        status=QuizStatus.DRAFT,
        generation_prompt=body.competency_context,
        total_questions=len(quiz_schema.questions),
        competency_id=body.competency_id,
    )
    db.add(quiz)
    db.flush()

    for idx, q in enumerate(quiz_schema.questions):
        try:
            diff = QuestionDifficulty(q.difficulty)
        except ValueError:
            diff = QuestionDifficulty.MEDIUM

        gq = GeneratedQuestion(
            quiz_id=quiz.id,
            question_text=q.question_text,
            option_a=q.option_a,
            option_b=q.option_b,
            option_c=q.option_c,
            option_d=q.option_d,
            correct_answer=q.correct_answer,
            explanation=q.explanation or "",
            difficulty=diff,
            topic_tags=json.dumps(q.topic_tags),
            competency_id=q.competency_id,
            source_page=q.source_page,
            sequence_order=idx,
            is_validated=False,
        )
        db.add(gq)

    db.commit()
    db.refresh(quiz)

    return {
        "quiz_id": quiz.id,
        "title": quiz.title,
        "total_questions": quiz.total_questions,
        "status": quiz.status.value,
        "message": "Quiz generated as DRAFT. Admin review required before publishing.",
    }


@router.get("/list", response_model=list[QuizOut])
def list_quizzes(
    status_filter: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """List quizzes — learners see only PUBLISHED, admins see all."""
    q = db.query(GeneratedQuiz)
    if current_user.role.value == "learner":
        q = q.filter(GeneratedQuiz.status == QuizStatus.PUBLISHED)
    elif status_filter:
        try:
            q = q.filter(GeneratedQuiz.status == QuizStatus(status_filter))
        except ValueError:
            pass
    quizzes = q.order_by(GeneratedQuiz.created_at.desc()).all()
    return [
        QuizOut(
            id=quiz.id,
            title=quiz.title,
            status=quiz.status.value,
            total_questions=quiz.total_questions,
            competency_id=quiz.competency_id,
            created_at=quiz.created_at.isoformat(),
        )
        for quiz in quizzes
    ]


@router.get("/{quiz_id}/questions")
def get_quiz_questions(
    quiz_id: str,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Get quiz questions. Learners cannot see correct answers before attempting."""
    quiz = db.query(GeneratedQuiz).filter(GeneratedQuiz.id == quiz_id).first()
    if not quiz:
        raise HTTPException(status_code=404, detail="Quiz not found.")

    # Learners can only access published quizzes
    if current_user.role.value == "learner" and quiz.status != QuizStatus.PUBLISHED:
        raise HTTPException(status_code=403, detail="This quiz is not yet published.")

    is_admin = current_user.role.value == "admin"
    questions = quiz.questions

    if is_admin:
        return [
            QuizQuestionWithAnswerOut(
                id=q.id,
                question_text=q.question_text,
                option_a=q.option_a,
                option_b=q.option_b,
                option_c=q.option_c,
                option_d=q.option_d,
                difficulty=q.difficulty.value,
                topic_tags=json.loads(q.topic_tags or "[]"),
                competency_id=q.competency_id,
                source_page=q.source_page,
                correct_answer=q.correct_answer,
                explanation=q.explanation or "",
            )
            for q in questions
        ]
    else:
        return [
            QuizQuestionOut(
                id=q.id,
                question_text=q.question_text,
                option_a=q.option_a,
                option_b=q.option_b,
                option_c=q.option_c,
                option_d=q.option_d,
                difficulty=q.difficulty.value,
                topic_tags=json.loads(q.topic_tags or "[]"),
                competency_id=q.competency_id,
                source_page=q.source_page,
            )
            for q in questions
        ]


@router.post("/{quiz_id}/publish")
def publish_quiz(
    quiz_id: str,
    db: Session = Depends(get_db),
    admin=Depends(require_admin),
):
    """Publish a quiz after admin review."""
    quiz = db.query(GeneratedQuiz).filter(GeneratedQuiz.id == quiz_id).first()
    if not quiz:
        raise HTTPException(status_code=404, detail="Quiz not found.")
    quiz.status = QuizStatus.PUBLISHED
    db.commit()
    return {"quiz_id": quiz.id, "status": quiz.status.value}


@router.post("/attempt/submit", response_model=QuizResultOut)
def submit_quiz_attempt(
    body: SubmitQuizRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Submit answers for a quiz and receive scored results."""
    quiz = db.query(GeneratedQuiz).filter(GeneratedQuiz.id == body.quiz_id).first()
    if not quiz:
        raise HTTPException(status_code=404, detail="Quiz not found.")
    if quiz.status != QuizStatus.PUBLISHED:
        raise HTTPException(status_code=400, detail="Quiz is not published.")

    questions = quiz.questions
    q_dicts = [
        {
            "id": q.id,
            "correct_answer": q.correct_answer,
            "explanation": q.explanation or "",
            "option_a": q.option_a,
            "option_b": q.option_b,
            "option_c": q.option_c,
            "option_d": q.option_d,
        }
        for q in questions
    ]

    result = score_quiz_attempt(questions=q_dicts, answers=body.answers)

    # Persist attempt
    now = datetime.now(timezone.utc)
    attempt = QuizAttempt(
        quiz_id=quiz.id,
        learner_id=current_user.id,
        started_at=now,
        completed_at=now,
        score=result["score_pct"],
        total_questions=result["total"],
        correct_answers=result["correct"],
        is_complete=True,
        answers=json.dumps(body.answers),
    )
    db.add(attempt)
    db.commit()
    db.refresh(attempt)

    return QuizResultOut(
        attempt_id=attempt.id,
        score_pct=result["score_pct"],
        correct=result["correct"],
        total=result["total"],
        results=result["results"],
    )
