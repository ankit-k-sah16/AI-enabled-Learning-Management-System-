"""
src/services/pathway_service.py — Learning Pathway Service.

Creates and manages ordered learning pathways based on recommendations.
Tracks activity completion and pathway progress.

Design:
- Pathway creation transforms recommendations into ordered activities.
- Completion of activities does NOT auto-increase competency scores.
- Progress is tracked at activity level.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from src.db.models import (
    LearningPathway,
    PathwayActivity,
    ActivityStatus,
    LearningResource,
    JobRole,
)
from src.ai.recommendation_engine import Recommendation


def create_pathway_from_recommendations(
    learner_id: str,
    job_role_id: Optional[str],
    recommendations: list[Recommendation],
    db: Session,
    title: Optional[str] = None,
    deactivate_old: bool = True,
) -> LearningPathway:
    """
    Create (or replace) a learning pathway from a list of recommendations.

    Args:
        learner_id:       The learner's user ID.
        job_role_id:      Optional job role context.
        recommendations:  Ordered list of Recommendation objects.
        db:               Database session.
        title:            Custom pathway title (auto-generated if None).
        deactivate_old:   Deactivate existing active pathways for this role.

    Returns:
        Newly created LearningPathway.
    """
    now = datetime.now(timezone.utc)

    # Deactivate existing active pathways for same learner/role
    if deactivate_old:
        old = db.query(LearningPathway).filter(
            LearningPathway.learner_id == learner_id,
            LearningPathway.is_active == True,
        )
        if job_role_id:
            old = old.filter(LearningPathway.job_role_id == job_role_id)
        for p in old.all():
            p.is_active = False

    # Build title
    if not title:
        role_name = ""
        if job_role_id:
            role = db.query(JobRole).filter(JobRole.id == job_role_id).first()
            if role:
                role_name = f" — {role.name}"
        title = f"Personalised Learning Pathway{role_name}"

    # Estimate total duration
    total_hours = sum(
        r.duration_hours for r in recommendations if r.duration_hours is not None
    )

    pathway = LearningPathway(
        learner_id=learner_id,
        job_role_id=job_role_id,
        title=title,
        description=(
            f"Personalised pathway targeting {len(recommendations)} resources "
            f"based on competency gap analysis."
        ),
        total_estimated_hours=total_hours if total_hours > 0 else None,
        is_active=True,
    )
    db.add(pathway)
    db.flush()

    # Create activities in recommendation order
    for idx, rec in enumerate(recommendations):
        # Verify resource exists in DB
        resource = db.query(LearningResource).filter(
            LearningResource.id == rec.resource_id
        ).first()
        if not resource:
            continue

        activity = PathwayActivity(
            pathway_id=pathway.id,
            resource_id=rec.resource_id,
            sequence_order=idx + 1,
            status=ActivityStatus.NOT_STARTED,
            priority_competency_id=(
                rec.gap_competency_id if rec.gap_competency_id else None
            ),
            recommendation_score=rec.recommendation_score,
            recommendation_explanation=rec.explanation,
        )
        db.add(activity)

    db.commit()
    db.refresh(pathway)
    return pathway


def get_active_pathway(
    learner_id: str,
    job_role_id: Optional[str],
    db: Session,
) -> Optional[LearningPathway]:
    """Return the learner's active pathway for a given role."""
    q = db.query(LearningPathway).filter(
        LearningPathway.learner_id == learner_id,
        LearningPathway.is_active == True,
    )
    if job_role_id:
        q = q.filter(LearningPathway.job_role_id == job_role_id)
    return q.order_by(LearningPathway.created_at.desc()).first()


def mark_activity_complete(
    activity_id: str,
    learner_id: str,
    db: Session,
) -> PathwayActivity:
    """
    Mark a pathway activity as complete.

    NOTE: This does NOT update competency scores.
    Competency improvement requires a new assessment.
    """
    activity = db.query(PathwayActivity).filter(
        PathwayActivity.id == activity_id,
    ).first()

    if not activity:
        raise ValueError(f"Activity {activity_id!r} not found.")

    # Verify the activity belongs to this learner's pathway
    pathway = db.query(LearningPathway).filter(
        LearningPathway.id == activity.pathway_id,
        LearningPathway.learner_id == learner_id,
    ).first()
    if not pathway:
        raise ValueError("Activity does not belong to this learner.")

    now = datetime.now(timezone.utc)
    if activity.status == ActivityStatus.NOT_STARTED:
        activity.started_at = now
    activity.status = ActivityStatus.COMPLETED
    activity.completed_at = now

    db.commit()
    db.refresh(activity)
    return activity


def get_pathway_progress(pathway: LearningPathway) -> dict:
    """Return progress statistics for a pathway."""
    activities = pathway.activities
    total = len(activities)
    completed = sum(1 for a in activities if a.status == ActivityStatus.COMPLETED)
    in_progress = sum(1 for a in activities if a.status == ActivityStatus.IN_PROGRESS)

    return {
        "total_activities": total,
        "completed": completed,
        "in_progress": in_progress,
        "not_started": total - completed - in_progress,
        "progress_pct": round((completed / total * 100) if total > 0 else 0.0, 1),
    }
