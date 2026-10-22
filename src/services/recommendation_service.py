"""
src/services/recommendation_service.py — Recommendation Service.

Bridges the AI recommendation engine with the database layer.
Fetches catalog, gaps, and history from DB and returns ranked recommendations.
"""

from __future__ import annotations

from sqlalchemy.orm import Session
import json

from src.db.models import (
    LearningResource,
    ResourceCompetencyMapping,
    PathwayActivity,
    ActivityStatus,
    Competency,
)
from src.ai.recommendation_engine import (
    generate_recommendations,
    ResourceCandidate,
    Recommendation,
)
from src.ai.skill_gap_analyzer import SkillGapReport, CompetencyGapRecord


def get_recommendations_for_learner(
    learner_id: str,
    skill_gap_report: SkillGapReport,
    db: Session,
    max_recommendations: int = 15,
) -> list[Recommendation]:
    """
    Generate personalized recommendations for a learner based on their skill gaps.

    Args:
        learner_id:         Learner's user ID.
        skill_gap_report:   Output from skill gap analysis.
        db:                 Database session.
        max_recommendations: Maximum results to return.

    Returns:
        Ranked list of Recommendation objects.
    """
    # 1. Load resource catalog from DB
    resources = db.query(LearningResource).filter(
        LearningResource.is_active == True
    ).all()

    # 2. Load competency mappings for each resource
    mappings = db.query(ResourceCompetencyMapping).all()
    resource_comp_map: dict[str, list[str]] = {}
    for m in mappings:
        resource_comp_map.setdefault(m.resource_id, []).append(m.competency_id)

    # 3. Build ResourceCandidate list
    catalog: list[ResourceCandidate] = []
    for res in resources:
        prereqs = []
        tags = []
        try:
            prereqs = json.loads(res.prerequisites or "[]")
        except Exception:
            pass
        try:
            tags = json.loads(res.tags or "[]")
        except Exception:
            pass

        catalog.append(ResourceCandidate(
            resource_id=res.id,
            title=res.title,
            provider=res.provider or "",
            source_url=res.source_url or "",
            resource_type=res.resource_type.value,
            difficulty=res.difficulty.value,
            description=res.description or "",
            duration_hours=res.duration_hours,
            language=res.language,
            prerequisites=prereqs,
            tags=tags,
            mapped_competency_ids=resource_comp_map.get(res.id, []),
            is_verified=res.is_verified,
            data_source=res.data_source or "",
        ))

    # 4. Find completed resource IDs from all pathways
    completed_ids: set[str] = set()
    completed_activities = db.query(PathwayActivity).filter(
        PathwayActivity.status == ActivityStatus.COMPLETED,
    ).all()
    # Filter by learner via join — simpler approach with existing models
    for act in completed_activities:
        if act.pathway and act.pathway.learner_id == learner_id:
            completed_ids.add(act.resource_id)

    # 5. Fetch competency descriptions for semantic scoring
    comp_ids = [g.competency_id for g in skill_gap_report.competency_gaps]
    comps = db.query(Competency).filter(Competency.id.in_(comp_ids)).all()
    comp_descs = {c.id: c.description or c.name for c in comps}

    # 6. Role competency IDs (all competencies the role requires)
    role_comp_ids = [g.competency_id for g in skill_gap_report.competency_gaps]

    # 7. Generate recommendations
    recommendations = generate_recommendations(
        learner_id=learner_id,
        skill_gaps=skill_gap_report.competency_gaps,
        resource_catalog=catalog,
        completed_resource_ids=completed_ids,
        competency_descriptions=comp_descs,
        role_competency_ids=role_comp_ids,
        max_recommendations=max_recommendations,
    )

    return recommendations
