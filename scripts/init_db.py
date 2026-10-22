"""
scripts/init_db.py — Database initialisation and seeding script.

Run this once before starting the application:
    python scripts/init_db.py

What it does:
1. Creates all database tables.
2. Seeds competencies, job roles, role requirements, resources, questions.
3. Creates the bootstrap admin account (credentials from .env).
4. Is safe to re-run — skips already-inserted records.

Note: This is a development/demo bootstrap script.
Do NOT run against a production database without review.
"""

from __future__ import annotations

import json
import sys
import os
from pathlib import Path

# Ensure project root is on sys.path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.core.config import settings
from src.db.session import init_db, SessionLocal
from src.db.models import (
    User, UserRole, LearnerProfile,
    JobRole, Competency, CompetencyCategory,
    RoleCompetencyRequirement,
    LearningResource, ResourceType, ResourceDifficulty, ResourceCompetencyMapping,
    AssessmentQuestion, QuestionDifficulty,
)
from data.seed.seed_data import (
    JOB_ROLES, COMPETENCIES, ROLE_REQUIREMENTS, LEARNING_RESOURCES, ASSESSMENT_QUESTIONS
)


def _hash_password(password: str) -> str:
    """Hash a plaintext password using bcrypt via passlib."""
    from passlib.context import CryptContext
    ctx = CryptContext(schemes=["bcrypt"], deprecated="auto")
    return ctx.hash(password)


def seed_job_roles(db) -> dict[str, str]:
    """Insert job roles. Returns {code: id} mapping."""
    existing = {r.code: r.id for r in db.query(JobRole).all()}
    inserted = {}
    for role_data in JOB_ROLES:
        code = role_data["code"]
        if code in existing:
            inserted[code] = existing[code]
            continue
        role = JobRole(
            name=role_data["name"],
            code=code,
            description=role_data.get("description"),
            department=role_data.get("department"),
            level=role_data.get("level"),
        )
        db.add(role)
        db.flush()
        inserted[code] = role.id
        print(f"  [+] JobRole: {code}")
    return inserted


def seed_competencies(db) -> dict[str, str]:
    """Insert competencies. Returns {code: id} mapping."""
    existing = {c.code: c.id for c in db.query(Competency).all()}
    inserted = {}
    for comp_data in COMPETENCIES:
        code = comp_data["code"]
        if code in existing:
            inserted[code] = existing[code]
            continue
        category_str = comp_data.get("category", "Technical")
        try:
            category = CompetencyCategory(category_str)
        except ValueError:
            category = CompetencyCategory.TECHNICAL

        comp = Competency(
            code=code,
            name=comp_data["name"],
            description=comp_data.get("description"),
            category=category,
            learning_outcomes=comp_data.get("learning_outcomes"),
        )
        db.add(comp)
        db.flush()
        inserted[code] = comp.id
        print(f"  [+] Competency: {code}")
    return inserted


def seed_role_requirements(db, role_ids: dict[str, str], comp_ids: dict[str, str]) -> None:
    """Insert role-competency requirements."""
    for role_code, reqs in ROLE_REQUIREMENTS.items():
        role_id = role_ids.get(role_code)
        if not role_id:
            print(f"  [!] Role not found: {role_code}")
            continue
        for req in reqs:
            comp_code = req["competency_code"]
            comp_id = comp_ids.get(comp_code)
            if not comp_id:
                print(f"  [!] Competency not found: {comp_code}")
                continue
            exists = db.query(RoleCompetencyRequirement).filter_by(
                job_role_id=role_id, competency_id=comp_id
            ).first()
            if exists:
                continue
            rcr = RoleCompetencyRequirement(
                job_role_id=role_id,
                competency_id=comp_id,
                required_score=req["required_score"],
                importance=req.get("importance", 1.0),
            )
            db.add(rcr)
    print("  [+] Role-competency requirements seeded.")


def seed_resources(db, comp_ids: dict[str, str]) -> None:
    """Insert learning resources and their competency mappings."""
    for res_data in LEARNING_RESOURCES:
        existing = db.query(LearningResource).filter_by(
            title=res_data["title"], provider=res_data.get("provider", "")
        ).first()
        if existing:
            continue

        try:
            rtype = ResourceType(res_data.get("resource_type", "Course"))
        except ValueError:
            rtype = ResourceType.COURSE
        try:
            diff = ResourceDifficulty(res_data.get("difficulty", "Beginner"))
        except ValueError:
            diff = ResourceDifficulty.BEGINNER

        resource = LearningResource(
            title=res_data["title"],
            provider=res_data.get("provider"),
            source_url=res_data.get("source_url"),
            resource_type=rtype,
            difficulty=diff,
            description=res_data.get("description"),
            duration_hours=res_data.get("duration_hours"),
            tags=res_data.get("tags"),
            is_verified=res_data.get("is_verified", False),
            data_source=res_data.get("data_source", "synthetic-demo"),
        )
        db.add(resource)
        db.flush()

        for comp_code in res_data.get("competency_codes", []):
            comp_id = comp_ids.get(comp_code)
            if comp_id:
                mapping = ResourceCompetencyMapping(
                    resource_id=resource.id,
                    competency_id=comp_id,
                    relevance_score=1.0,
                )
                db.add(mapping)

        print(f"  [+] Resource: {res_data['title'][:50]}")


def seed_questions(db, comp_ids: dict[str, str]) -> None:
    """Insert assessment questions."""
    for q_data in ASSESSMENT_QUESTIONS:
        comp_code = q_data["competency_code"]
        comp_id = comp_ids.get(comp_code)
        if not comp_id:
            print(f"  [!] Competency not found for question: {comp_code}")
            continue

        # Avoid duplicates by checking question text
        existing = db.query(AssessmentQuestion).filter_by(
            competency_id=comp_id,
            question_text=q_data["question_text"],
        ).first()
        if existing:
            continue

        try:
            diff = QuestionDifficulty(q_data.get("difficulty", "medium"))
        except ValueError:
            diff = QuestionDifficulty.MEDIUM

        q = AssessmentQuestion(
            competency_id=comp_id,
            question_text=q_data["question_text"],
            option_a=q_data["option_a"],
            option_b=q_data["option_b"],
            option_c=q_data["option_c"],
            option_d=q_data["option_d"],
            correct_answer=q_data["correct_answer"].upper(),
            explanation=q_data.get("explanation"),
            difficulty=diff,
            weight=float(q_data.get("weight", 1.0)),
            source=q_data.get("source", "seed"),
        )
        db.add(q)
    print("  [+] Assessment questions seeded.")


def seed_admin(db) -> None:
    """Create bootstrap admin account."""
    admin_email = settings.admin_email
    exists = db.query(User).filter_by(email=admin_email).first()
    if exists:
        print(f"  [=] Admin already exists: {admin_email}")
        return

    hashed = _hash_password(settings.admin_password)
    admin = User(
        email=admin_email,
        hashed_password=hashed,
        full_name="Platform Administrator",
        role=UserRole.ADMIN,
        is_active=True,
    )
    db.add(admin)
    db.flush()
    print(f"  [+] Admin created: {admin_email}")
    print(f"  [!] CHANGE the admin password after first login.")


def main():
    print("=" * 60)
    print("AI Skill Intelligence Platform — Database Initialisation")
    print("=" * 60)

    # Ensure data directory exists
    Path("data").mkdir(exist_ok=True)

    print("\n[1] Creating database tables...")
    init_db()
    print("    Tables created.")

    print("\n[2] Seeding data...")
    db = SessionLocal()
    try:
        role_ids = seed_job_roles(db)
        comp_ids = seed_competencies(db)
        seed_role_requirements(db, role_ids, comp_ids)
        seed_resources(db, comp_ids)
        seed_questions(db, comp_ids)
        seed_admin(db)
        db.commit()
        print("\n[3] All seed data committed successfully.")
    except Exception as exc:
        db.rollback()
        print(f"\n[ERROR] Seeding failed: {exc}")
        raise
    finally:
        db.close()

    print("\n" + "=" * 60)
    print("Initialisation complete.")
    print(f"  Database: {settings.database_url}")
    print(f"  Admin email: {settings.admin_email}")
    print("=" * 60)


if __name__ == "__main__":
    main()
