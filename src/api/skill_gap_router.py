"""
src/api/skill_gap_router.py — Skill Gap Analysis endpoints.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from src.db.session import get_db
from src.db.models import LearnerProfile
from src.api.auth_router import get_current_user
from src.services.skill_gap_service import run_skill_gap_analysis

router = APIRouter()


class GapRecordOut(BaseModel):
    competency_id: str
    competency_name: str
    competency_category: str
    current_score: float | None
    required_score: float
    gap_score: float
    importance: float
    priority_score: float
    priority_rank: int | None
    is_assessed: bool
    proficiency_current: str
    proficiency_required: str
    explanation: str
    confidence: float


class SkillGapReportOut(BaseModel):
    learner_id: str
    job_role_id: str
    job_role_name: str
    analysed_at: str
    total_required: int
    total_assessed: int
    total_with_gap: int
    total_no_gap: int
    total_unassessed: int
    average_gap: float
    role_readiness_pct: float
    competency_gaps: list[GapRecordOut]
    unassessed_competencies: list[str]
    summary: str
    warnings: list[str]


@router.get("/analyse/{job_role_id}", response_model=SkillGapReportOut)
def analyse_gaps(
    job_role_id: str,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Run skill gap analysis for the current learner against a job role."""
    try:
        report = run_skill_gap_analysis(
            learner_id=current_user.id,
            job_role_id=job_role_id,
            db=db,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    return SkillGapReportOut(
        learner_id=report.learner_id,
        job_role_id=report.job_role_id,
        job_role_name=report.job_role_name,
        analysed_at=report.analysed_at.isoformat(),
        total_required=report.total_required,
        total_assessed=report.total_assessed,
        total_with_gap=report.total_with_gap,
        total_no_gap=report.total_no_gap,
        total_unassessed=report.total_unassessed,
        average_gap=report.average_gap,
        role_readiness_pct=report.role_readiness_pct,
        competency_gaps=[
            GapRecordOut(
                competency_id=g.competency_id,
                competency_name=g.competency_name,
                competency_category=g.competency_category,
                current_score=g.current_score,
                required_score=g.required_score,
                gap_score=g.gap_score,
                importance=g.importance,
                priority_score=g.priority_score,
                priority_rank=g.priority_rank,
                is_assessed=g.is_assessed,
                proficiency_current=g.proficiency_current,
                proficiency_required=g.proficiency_required,
                explanation=g.explanation,
                confidence=g.confidence,
            )
            for g in report.competency_gaps
        ],
        unassessed_competencies=report.unassessed_competencies,
        summary=report.summary,
        warnings=report.warnings,
    )
