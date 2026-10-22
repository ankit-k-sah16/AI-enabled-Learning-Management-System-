"""
src/api/recommendation_router.py — Recommendation and Learning Pathway endpoints.
"""

from __future__ import annotations

from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from src.db.session import get_db
from src.db.models import (
    LearningPathway, PathwayActivity, ActivityStatus, LearnerProfile
)
from src.api.auth_router import get_current_user
from src.services.skill_gap_service import run_skill_gap_analysis
from src.services.recommendation_service import get_recommendations_for_learner
from src.services.pathway_service import (
    create_pathway_from_recommendations,
    get_active_pathway,
    mark_activity_complete,
    get_pathway_progress,
)

router = APIRouter()


class RecommendationOut(BaseModel):
    resource_id: str
    title: str
    provider: str
    source_url: str
    resource_type: str
    difficulty: str
    description: str
    duration_hours: Optional[float]
    language: str
    relevant_competency_ids: list[str]
    gap_competency_id: str
    recommendation_score: float
    explanation: str
    is_completed: bool
    is_verified: bool
    data_source: str


class PathwayActivityOut(BaseModel):
    id: str
    sequence_order: int
    resource_id: str
    resource_title: str
    resource_type: str
    difficulty: str
    duration_hours: Optional[float]
    provider: str
    source_url: str
    status: str
    recommendation_score: Optional[float]
    recommendation_explanation: Optional[str]
    started_at: Optional[str]
    completed_at: Optional[str]


class PathwayOut(BaseModel):
    id: str
    title: str
    description: Optional[str]
    total_estimated_hours: Optional[float]
    is_active: bool
    created_at: str
    activities: list[PathwayActivityOut]
    progress: dict


class GeneratePathwayRequest(BaseModel):
    job_role_id: str
    max_recommendations: int = 12


@router.get("/recommendations/{job_role_id}", response_model=list[RecommendationOut])
def get_recommendations(
    job_role_id: str,
    max_recs: int = 12,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Get personalized recommendations based on skill gaps for a role."""
    try:
        report = run_skill_gap_analysis(
            learner_id=current_user.id,
            job_role_id=job_role_id,
            db=db,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    recs = get_recommendations_for_learner(
        learner_id=current_user.id,
        skill_gap_report=report,
        db=db,
        max_recommendations=max_recs,
    )

    return [
        RecommendationOut(
            resource_id=r.resource_id,
            title=r.title,
            provider=r.provider,
            source_url=r.source_url,
            resource_type=r.resource_type,
            difficulty=r.difficulty,
            description=r.description,
            duration_hours=r.duration_hours,
            language=r.language,
            relevant_competency_ids=r.relevant_competency_ids,
            gap_competency_id=r.gap_competency_id,
            recommendation_score=r.recommendation_score,
            explanation=r.explanation,
            is_completed=r.is_completed,
            is_verified=r.is_verified,
            data_source=r.data_source,
        )
        for r in recs
    ]


@router.post("/pathway/generate", response_model=PathwayOut)
def generate_pathway(
    body: GeneratePathwayRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Generate a learning pathway from recommendations and persist it."""
    try:
        report = run_skill_gap_analysis(
            learner_id=current_user.id,
            job_role_id=body.job_role_id,
            db=db,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    recs = get_recommendations_for_learner(
        learner_id=current_user.id,
        skill_gap_report=report,
        db=db,
        max_recommendations=body.max_recommendations,
    )

    pathway = create_pathway_from_recommendations(
        learner_id=current_user.id,
        job_role_id=body.job_role_id,
        recommendations=recs,
        db=db,
    )

    return _pathway_to_out(pathway)


@router.get("/pathway/active", response_model=Optional[PathwayOut])
def get_my_pathway(
    job_role_id: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Get the learner's active learning pathway."""
    pathway = get_active_pathway(
        learner_id=current_user.id,
        job_role_id=job_role_id,
        db=db,
    )
    if not pathway:
        return None
    return _pathway_to_out(pathway)


@router.post("/pathway/activity/{activity_id}/complete")
def complete_activity(
    activity_id: str,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Mark a learning activity as complete."""
    try:
        activity = mark_activity_complete(
            activity_id=activity_id,
            learner_id=current_user.id,
            db=db,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    return {
        "activity_id": activity.id,
        "status": activity.status.value,
        "completed_at": activity.completed_at.isoformat() if activity.completed_at else None,
        "message": "Activity marked as complete. Take a new assessment to update your competency score.",
    }


def _pathway_to_out(pathway: LearningPathway) -> PathwayOut:
    """Convert a LearningPathway ORM object to response model."""
    progress = get_pathway_progress(pathway)
    activities = []
    for act in pathway.activities:
        res = act.resource
        if not res:
            continue
        activities.append(PathwayActivityOut(
            id=act.id,
            sequence_order=act.sequence_order,
            resource_id=act.resource_id,
            resource_title=res.title,
            resource_type=res.resource_type.value,
            difficulty=res.difficulty.value,
            duration_hours=res.duration_hours,
            provider=res.provider or "",
            source_url=res.source_url or "",
            status=act.status.value,
            recommendation_score=act.recommendation_score,
            recommendation_explanation=act.recommendation_explanation,
            started_at=act.started_at.isoformat() if act.started_at else None,
            completed_at=act.completed_at.isoformat() if act.completed_at else None,
        ))

    return PathwayOut(
        id=pathway.id,
        title=pathway.title,
        description=pathway.description,
        total_estimated_hours=pathway.total_estimated_hours,
        is_active=pathway.is_active,
        created_at=pathway.created_at.isoformat(),
        activities=activities,
        progress=progress,
    )
