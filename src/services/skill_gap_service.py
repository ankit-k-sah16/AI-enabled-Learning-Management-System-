"""
src/services/skill_gap_service.py — Skill Gap Analysis Service.

Bridges the AI module (skill_gap_analyzer) with the database layer.
Fetches role requirements and learner scores from DB, runs the analysis,
persists the results, and returns the report.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from src.db.models import (
    RoleCompetencyRequirement,
    CompetencyScore,
    SkillGapRecord,
    JobRole,
    Competency,
)
from src.ai.skill_gap_analyzer import analyse_skill_gaps, SkillGapReport


def run_skill_gap_analysis(
    learner_id: str,
    job_role_id: str,
    db: Session,
) -> SkillGapReport:
    """
    Run skill gap analysis for a learner against a job role.

    Steps:
    1. Fetch job role and competency requirements.
    2. Fetch learner's current competency scores.
    3. Run the AI analysis module.
    4. Persist gap records to the database.
    5. Return the report.
    """
    # 1. Fetch job role
    role = db.query(JobRole).filter(JobRole.id == job_role_id).first()
    if not role:
        raise ValueError(f"Job role {job_role_id!r} not found.")

    # 2. Fetch requirements
    requirements = (
        db.query(RoleCompetencyRequirement)
        .filter(RoleCompetencyRequirement.job_role_id == job_role_id)
        .all()
    )
    req_dicts = [
        {
            "competency_id": r.competency_id,
            "required_score": r.required_score,
            "importance": r.importance,
        }
        for r in requirements
    ]

    # 3. Fetch learner scores (keyed by competency_id)
    scores_db = (
        db.query(CompetencyScore)
        .filter(CompetencyScore.learner_id == learner_id)
        .all()
    )
    learner_scores: dict = {
        s.competency_id: {
            "score": s.score,
            "confidence": s.confidence,
            "proficiency_level": s.proficiency_level.value,
        }
        for s in scores_db
    }

    # 4. Fetch competency metadata
    comp_ids = [r.competency_id for r in requirements]
    comps = db.query(Competency).filter(Competency.id.in_(comp_ids)).all()
    comp_meta = {
        c.id: {"name": c.name, "category": c.category.value}
        for c in comps
    }

    # 5. Run AI analysis
    report = analyse_skill_gaps(
        learner_id=learner_id,
        job_role_id=job_role_id,
        job_role_name=role.name,
        role_requirements=req_dicts,
        learner_scores=learner_scores,
        competency_meta=comp_meta,
    )

    # 6. Persist gap records (upsert)
    now = datetime.now(timezone.utc)
    for gap in report.competency_gaps:
        existing = db.query(SkillGapRecord).filter_by(
            learner_id=learner_id,
            competency_id=gap.competency_id,
            job_role_id=job_role_id,
        ).first()

        if existing:
            existing.current_score = gap.current_score
            existing.required_score = gap.required_score
            existing.gap_score = gap.gap_score
            existing.importance = gap.importance
            existing.priority_score = gap.priority_score
            existing.priority_rank = gap.priority_rank
            existing.is_assessed = gap.is_assessed
            existing.explanation = gap.explanation
            existing.computed_at = now
        else:
            record = SkillGapRecord(
                learner_id=learner_id,
                competency_id=gap.competency_id,
                job_role_id=job_role_id,
                current_score=gap.current_score,
                required_score=gap.required_score,
                gap_score=gap.gap_score,
                importance=gap.importance,
                priority_score=gap.priority_score,
                priority_rank=gap.priority_rank,
                is_assessed=gap.is_assessed,
                explanation=gap.explanation,
                computed_at=now,
            )
            db.add(record)

    db.commit()
    return report
