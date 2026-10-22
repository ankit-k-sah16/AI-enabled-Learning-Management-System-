"""
src/api/competency_router.py — Competency framework endpoints.
"""

from __future__ import annotations

from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from src.db.session import get_db
from src.db.models import Competency, JobRole, RoleCompetencyRequirement
from src.api.auth_router import get_current_user

router = APIRouter()


class CompetencyOut(BaseModel):
    id: str
    code: str
    name: str
    description: Optional[str]
    category: str


class JobRoleOut(BaseModel):
    id: str
    code: str
    name: str
    description: Optional[str]
    department: Optional[str]
    level: Optional[str]


class RoleRequirementOut(BaseModel):
    competency_id: str
    competency_name: str
    competency_code: str
    required_score: float
    importance: float


@router.get("/", response_model=list[CompetencyOut])
def list_competencies(db: Session = Depends(get_db), _=Depends(get_current_user)):
    comps = db.query(Competency).filter(Competency.is_active == True).all()
    return [
        CompetencyOut(
            id=c.id, code=c.code, name=c.name,
            description=c.description, category=c.category.value,
        )
        for c in comps
    ]


@router.get("/roles", response_model=list[JobRoleOut])
def list_job_roles(db: Session = Depends(get_db), _=Depends(get_current_user)):
    roles = db.query(JobRole).filter(JobRole.is_active == True).all()
    return [
        JobRoleOut(
            id=r.id, code=r.code, name=r.name,
            description=r.description, department=r.department, level=r.level,
        )
        for r in roles
    ]


@router.get("/roles/{role_id}/requirements", response_model=list[RoleRequirementOut])
def get_role_requirements(
    role_id: str,
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    reqs = (
        db.query(RoleCompetencyRequirement)
        .filter(RoleCompetencyRequirement.job_role_id == role_id)
        .all()
    )
    if not reqs:
        raise HTTPException(status_code=404, detail="Role or requirements not found.")
    return [
        RoleRequirementOut(
            competency_id=r.competency_id,
            competency_name=r.competency.name,
            competency_code=r.competency.code,
            required_score=r.required_score,
            importance=r.importance,
        )
        for r in reqs
    ]
