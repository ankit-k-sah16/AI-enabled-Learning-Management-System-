"""
db/models.py — SQLAlchemy ORM models for the AI Skill Intelligence Platform.

All tables are designed to be portable to PostgreSQL.
Foreign-key constraints and indexes are explicitly defined.
Timestamps use UTC.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


# ── Helpers ───────────────────────────────────────────────────────────────────

def _now() -> datetime:
    return datetime.now(timezone.utc)


def _uuid() -> str:
    return str(uuid.uuid4())


# ── Enums ─────────────────────────────────────────────────────────────────────

class UserRole(str, enum.Enum):
    LEARNER = "learner"
    ADMIN = "admin"


class ProficiencyLevel(str, enum.Enum):
    BEGINNER = "Beginner"
    INTERMEDIATE = "Intermediate"
    ADVANCED = "Advanced"
    EXPERT = "Expert"
    UNKNOWN = "Unknown"


class CompetencyCategory(str, enum.Enum):
    TECHNICAL = "Technical"
    DOMAIN = "Domain"
    BEHAVIOURAL = "Behavioural"
    LEADERSHIP = "Leadership"
    DIGITAL = "Digital"


class ResourceType(str, enum.Enum):
    COURSE = "Course"
    MODULE = "Module"
    VIDEO = "Video"
    ARTICLE = "Article"
    ASSESSMENT = "Assessment"
    WORKSHOP = "Workshop"
    WEBINAR = "Webinar"
    DOCUMENT = "Document"


class ResourceDifficulty(str, enum.Enum):
    BEGINNER = "Beginner"
    INTERMEDIATE = "Intermediate"
    ADVANCED = "Advanced"
    EXPERT = "Expert"


class ActivityStatus(str, enum.Enum):
    NOT_STARTED = "not_started"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    SKIPPED = "skipped"


class DocumentStatus(str, enum.Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    INDEXED = "indexed"
    FAILED = "failed"


class QuizStatus(str, enum.Enum):
    DRAFT = "draft"
    REVIEW = "review"
    PUBLISHED = "published"
    ARCHIVED = "archived"


class QuestionDifficulty(str, enum.Enum):
    EASY = "easy"
    MEDIUM = "medium"
    HARD = "hard"


# ── Base ──────────────────────────────────────────────────────────────────────

class Base(DeclarativeBase):
    pass


# ── Users & Auth ──────────────────────────────────────────────────────────────

class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[UserRole] = mapped_column(Enum(UserRole), default=UserRole.LEARNER, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)

    profile: Mapped[Optional["LearnerProfile"]] = relationship(back_populates="user", uselist=False)
    assessment_attempts: Mapped[list["AssessmentAttempt"]] = relationship(back_populates="learner")
    pathways: Mapped[list["LearningPathway"]] = relationship(back_populates="learner")
    uploaded_documents: Mapped[list["Document"]] = relationship(back_populates="uploader")
    quiz_attempts: Mapped[list["QuizAttempt"]] = relationship(back_populates="learner")

    def __repr__(self) -> str:
        return f"<User {self.email} [{self.role}]>"


class LearnerProfile(Base):
    __tablename__ = "learner_profiles"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False)
    department: Mapped[Optional[str]] = mapped_column(String(255))
    designation: Mapped[Optional[str]] = mapped_column(String(255))
    years_experience: Mapped[Optional[int]] = mapped_column(Integer)
    target_job_role_id: Mapped[Optional[str]] = mapped_column(ForeignKey("job_roles.id", ondelete="SET NULL"))
    preferred_language: Mapped[str] = mapped_column(String(10), default="en")
    available_hours_per_week: Mapped[Optional[float]] = mapped_column(Float)
    bio: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)

    user: Mapped["User"] = relationship(back_populates="profile")
    target_job_role: Mapped[Optional["JobRole"]] = relationship(foreign_keys=[target_job_role_id])

    def __repr__(self) -> str:
        return f"<LearnerProfile user={self.user_id}>"


# ── Competency Framework ──────────────────────────────────────────────────────

class JobRole(Base):
    __tablename__ = "job_roles"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    code: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)
    department: Mapped[Optional[str]] = mapped_column(String(255))
    level: Mapped[Optional[str]] = mapped_column(String(50))  # e.g. Junior, Senior, Lead
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    role_competency_requirements: Mapped[list["RoleCompetencyRequirement"]] = relationship(
        back_populates="job_role", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<JobRole {self.code}: {self.name}>"


class Competency(Base):
    __tablename__ = "competencies"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    code: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)
    category: Mapped[CompetencyCategory] = mapped_column(
        Enum(CompetencyCategory), default=CompetencyCategory.TECHNICAL, nullable=False
    )
    learning_outcomes: Mapped[Optional[str]] = mapped_column(Text)  # JSON string
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)

    role_requirements: Mapped[list["RoleCompetencyRequirement"]] = relationship(
        back_populates="competency"
    )
    assessment_questions: Mapped[list["AssessmentQuestion"]] = relationship(
        back_populates="competency"
    )
    competency_scores: Mapped[list["CompetencyScore"]] = relationship(
        back_populates="competency"
    )
    skill_gaps: Mapped[list["SkillGapRecord"]] = relationship(back_populates="competency")
    resource_mappings: Mapped[list["ResourceCompetencyMapping"]] = relationship(
        back_populates="competency"
    )

    def __repr__(self) -> str:
        return f"<Competency {self.code}: {self.name}>"


class RoleCompetencyRequirement(Base):
    """Associates a required proficiency score with a competency for a job role."""

    __tablename__ = "role_competency_requirements"
    __table_args__ = (
        UniqueConstraint("job_role_id", "competency_id", name="uq_role_competency"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    job_role_id: Mapped[str] = mapped_column(ForeignKey("job_roles.id", ondelete="CASCADE"), nullable=False)
    competency_id: Mapped[str] = mapped_column(ForeignKey("competencies.id", ondelete="CASCADE"), nullable=False)
    required_score: Mapped[float] = mapped_column(Float, nullable=False)   # 0–100
    importance: Mapped[float] = mapped_column(Float, default=1.0)           # weight for priority
    notes: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    job_role: Mapped["JobRole"] = relationship(back_populates="role_competency_requirements")
    competency: Mapped["Competency"] = relationship(back_populates="role_requirements")

    def __repr__(self) -> str:
        return f"<RoleCompetencyRequirement role={self.job_role_id} comp={self.competency_id} req={self.required_score}>"


# ── Learning Resources ────────────────────────────────────────────────────────

class LearningResource(Base):
    __tablename__ = "learning_resources"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    provider: Mapped[Optional[str]] = mapped_column(String(255))
    source_url: Mapped[Optional[str]] = mapped_column(String(1000))
    resource_type: Mapped[ResourceType] = mapped_column(Enum(ResourceType), default=ResourceType.COURSE)
    difficulty: Mapped[ResourceDifficulty] = mapped_column(
        Enum(ResourceDifficulty), default=ResourceDifficulty.BEGINNER
    )
    description: Mapped[Optional[str]] = mapped_column(Text)
    duration_hours: Mapped[Optional[float]] = mapped_column(Float)
    language: Mapped[str] = mapped_column(String(10), default="en")
    prerequisites: Mapped[Optional[str]] = mapped_column(Text)  # JSON list of resource IDs
    tags: Mapped[Optional[str]] = mapped_column(Text)           # JSON list of strings
    is_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    data_source: Mapped[Optional[str]] = mapped_column(String(255))  # provenance
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)

    competency_mappings: Mapped[list["ResourceCompetencyMapping"]] = relationship(
        back_populates="resource", cascade="all, delete-orphan"
    )
    pathway_activities: Mapped[list["PathwayActivity"]] = relationship(back_populates="resource")

    def __repr__(self) -> str:
        return f"<LearningResource {self.title[:40]}>"


class ResourceCompetencyMapping(Base):
    """Maps a learning resource to one or more competencies it addresses."""

    __tablename__ = "resource_competency_mappings"
    __table_args__ = (
        UniqueConstraint("resource_id", "competency_id", name="uq_resource_competency"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    resource_id: Mapped[str] = mapped_column(ForeignKey("learning_resources.id", ondelete="CASCADE"))
    competency_id: Mapped[str] = mapped_column(ForeignKey("competencies.id", ondelete="CASCADE"))
    relevance_score: Mapped[float] = mapped_column(Float, default=1.0)  # 0–1

    resource: Mapped["LearningResource"] = relationship(back_populates="competency_mappings")
    competency: Mapped["Competency"] = relationship(back_populates="resource_mappings")


# ── Assessments ───────────────────────────────────────────────────────────────

class AssessmentQuestion(Base):
    __tablename__ = "assessment_questions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    competency_id: Mapped[str] = mapped_column(ForeignKey("competencies.id", ondelete="CASCADE"), nullable=False)
    question_text: Mapped[str] = mapped_column(Text, nullable=False)
    option_a: Mapped[str] = mapped_column(Text, nullable=False)
    option_b: Mapped[str] = mapped_column(Text, nullable=False)
    option_c: Mapped[str] = mapped_column(Text, nullable=False)
    option_d: Mapped[str] = mapped_column(Text, nullable=False)
    correct_answer: Mapped[str] = mapped_column(String(1), nullable=False)  # A, B, C, or D
    explanation: Mapped[Optional[str]] = mapped_column(Text)
    difficulty: Mapped[QuestionDifficulty] = mapped_column(
        Enum(QuestionDifficulty), default=QuestionDifficulty.MEDIUM
    )
    weight: Mapped[float] = mapped_column(Float, default=1.0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    source: Mapped[Optional[str]] = mapped_column(String(255))  # "seed", "generated", "imported"
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    competency: Mapped["Competency"] = relationship(back_populates="assessment_questions")
    responses: Mapped[list["LearnerResponse"]] = relationship(back_populates="question")

    def __repr__(self) -> str:
        return f"<AssessmentQuestion comp={self.competency_id} diff={self.difficulty}>"


class AssessmentAttempt(Base):
    __tablename__ = "assessment_attempts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    learner_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    competency_id: Mapped[Optional[str]] = mapped_column(ForeignKey("competencies.id", ondelete="SET NULL"))
    job_role_id: Mapped[Optional[str]] = mapped_column(ForeignKey("job_roles.id", ondelete="SET NULL"))
    attempt_number: Mapped[int] = mapped_column(Integer, default=1)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    raw_score: Mapped[Optional[float]] = mapped_column(Float)        # 0–100
    weighted_score: Mapped[Optional[float]] = mapped_column(Float)   # 0–100
    total_questions: Mapped[int] = mapped_column(Integer, default=0)
    answered_questions: Mapped[int] = mapped_column(Integer, default=0)
    correct_answers: Mapped[int] = mapped_column(Integer, default=0)
    score_breakdown: Mapped[Optional[str]] = mapped_column(Text)  # JSON
    is_complete: Mapped[bool] = mapped_column(Boolean, default=False)

    learner: Mapped["User"] = relationship(back_populates="assessment_attempts")
    responses: Mapped[list["LearnerResponse"]] = relationship(back_populates="attempt")

    __table_args__ = (
        Index("ix_attempt_learner_comp", "learner_id", "competency_id"),
    )

    def __repr__(self) -> str:
        return f"<AssessmentAttempt learner={self.learner_id} attempt={self.attempt_number}>"


class LearnerResponse(Base):
    __tablename__ = "learner_responses"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    attempt_id: Mapped[str] = mapped_column(ForeignKey("assessment_attempts.id", ondelete="CASCADE"), nullable=False)
    question_id: Mapped[str] = mapped_column(ForeignKey("assessment_questions.id", ondelete="CASCADE"), nullable=False)
    selected_answer: Mapped[Optional[str]] = mapped_column(String(1))  # A/B/C/D or None if skipped
    is_correct: Mapped[Optional[bool]] = mapped_column(Boolean)
    time_taken_seconds: Mapped[Optional[int]] = mapped_column(Integer)
    responded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    attempt: Mapped["AssessmentAttempt"] = relationship(back_populates="responses")
    question: Mapped["AssessmentQuestion"] = relationship(back_populates="responses")

    def __repr__(self) -> str:
        return f"<LearnerResponse attempt={self.attempt_id} q={self.question_id} ans={self.selected_answer}>"


# ── Competency Scores & Skill Gaps ───────────────────────────────────────────

class CompetencyScore(Base):
    """Latest computed competency score per learner per competency."""

    __tablename__ = "competency_scores"
    __table_args__ = (
        UniqueConstraint("learner_id", "competency_id", name="uq_learner_competency_score"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    learner_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    competency_id: Mapped[str] = mapped_column(ForeignKey("competencies.id", ondelete="CASCADE"), nullable=False)
    score: Mapped[Optional[float]] = mapped_column(Float)   # 0–100; None = not assessed
    proficiency_level: Mapped[ProficiencyLevel] = mapped_column(
        Enum(ProficiencyLevel), default=ProficiencyLevel.UNKNOWN
    )
    attempt_id: Mapped[Optional[str]] = mapped_column(ForeignKey("assessment_attempts.id"))
    confidence: Mapped[float] = mapped_column(Float, default=1.0)  # 0–1; lower if few questions
    assessed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)

    learner: Mapped["User"] = relationship()
    competency: Mapped["Competency"] = relationship(back_populates="competency_scores")

    def __repr__(self) -> str:
        return f"<CompetencyScore learner={self.learner_id} comp={self.competency_id} score={self.score}>"


class SkillGapRecord(Base):
    """Computed skill gap between current and required proficiency."""

    __tablename__ = "skill_gap_records"
    __table_args__ = (
        UniqueConstraint("learner_id", "competency_id", "job_role_id", name="uq_gap_record"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    learner_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    competency_id: Mapped[str] = mapped_column(ForeignKey("competencies.id", ondelete="CASCADE"), nullable=False)
    job_role_id: Mapped[str] = mapped_column(ForeignKey("job_roles.id", ondelete="CASCADE"), nullable=False)
    current_score: Mapped[Optional[float]] = mapped_column(Float)   # None = not assessed
    required_score: Mapped[float] = mapped_column(Float, nullable=False)
    gap_score: Mapped[float] = mapped_column(Float, nullable=False)  # max(0, required – current)
    importance: Mapped[float] = mapped_column(Float, default=1.0)
    priority_score: Mapped[float] = mapped_column(Float, default=0.0)  # gap × importance normalised
    priority_rank: Mapped[Optional[int]] = mapped_column(Integer)
    is_assessed: Mapped[bool] = mapped_column(Boolean, default=False)
    explanation: Mapped[Optional[str]] = mapped_column(Text)
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    learner: Mapped["User"] = relationship()
    competency: Mapped["Competency"] = relationship(back_populates="skill_gaps")
    job_role: Mapped["JobRole"] = relationship()

    def __repr__(self) -> str:
        return f"<SkillGapRecord learner={self.learner_id} gap={self.gap_score:.1f}>"


# ── Learning Pathways ─────────────────────────────────────────────────────────

class LearningPathway(Base):
    __tablename__ = "learning_pathways"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    learner_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    job_role_id: Mapped[Optional[str]] = mapped_column(ForeignKey("job_roles.id", ondelete="SET NULL"))
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)
    total_estimated_hours: Mapped[Optional[float]] = mapped_column(Float)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)

    learner: Mapped["User"] = relationship(back_populates="pathways")
    job_role: Mapped[Optional["JobRole"]] = relationship()
    activities: Mapped[list["PathwayActivity"]] = relationship(
        back_populates="pathway", cascade="all, delete-orphan",
        order_by="PathwayActivity.sequence_order"
    )

    def __repr__(self) -> str:
        return f"<LearningPathway learner={self.learner_id} title={self.title[:40]}>"


class PathwayActivity(Base):
    __tablename__ = "pathway_activities"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    pathway_id: Mapped[str] = mapped_column(ForeignKey("learning_pathways.id", ondelete="CASCADE"), nullable=False)
    resource_id: Mapped[str] = mapped_column(ForeignKey("learning_resources.id", ondelete="CASCADE"), nullable=False)
    sequence_order: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[ActivityStatus] = mapped_column(Enum(ActivityStatus), default=ActivityStatus.NOT_STARTED)
    priority_competency_id: Mapped[Optional[str]] = mapped_column(ForeignKey("competencies.id"))
    recommendation_score: Mapped[Optional[float]] = mapped_column(Float)
    recommendation_explanation: Mapped[Optional[str]] = mapped_column(Text)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    notes: Mapped[Optional[str]] = mapped_column(Text)

    pathway: Mapped["LearningPathway"] = relationship(back_populates="activities")
    resource: Mapped["LearningResource"] = relationship(back_populates="pathway_activities")
    priority_competency: Mapped[Optional["Competency"]] = relationship(foreign_keys=[priority_competency_id])

    def __repr__(self) -> str:
        return f"<PathwayActivity seq={self.sequence_order} status={self.status}>"


# ── Documents & RAG ──────────────────────────────────────────────────────────

class Document(Base):
    __tablename__ = "documents"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    uploader_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    filename: Mapped[str] = mapped_column(String(500), nullable=False)
    original_filename: Mapped[str] = mapped_column(String(500), nullable=False)
    file_type: Mapped[str] = mapped_column(String(10), nullable=False)  # pdf/docx/pptx
    file_size_bytes: Mapped[int] = mapped_column(Integer)
    status: Mapped[DocumentStatus] = mapped_column(Enum(DocumentStatus), default=DocumentStatus.PENDING)
    total_chunks: Mapped[int] = mapped_column(Integer, default=0)
    error_message: Mapped[Optional[str]] = mapped_column(Text)
    is_approved: Mapped[bool] = mapped_column(Boolean, default=False)
    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    processed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    uploader: Mapped[Optional["User"]] = relationship(back_populates="uploaded_documents")
    chunks: Mapped[list["DocumentChunk"]] = relationship(
        back_populates="document", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Document {self.original_filename} [{self.status}]>"


class DocumentChunk(Base):
    __tablename__ = "document_chunks"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True)
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    page_number: Mapped[Optional[int]] = mapped_column(Integer)
    section_heading: Mapped[Optional[str]] = mapped_column(String(500))
    token_count: Mapped[Optional[int]] = mapped_column(Integer)
    vector_id: Mapped[Optional[str]] = mapped_column(String(100))  # ID in vector store

    document: Mapped["Document"] = relationship(back_populates="chunks")

    def __repr__(self) -> str:
        return f"<DocumentChunk doc={self.document_id} idx={self.chunk_index}>"


# ── Quizzes ───────────────────────────────────────────────────────────────────

class GeneratedQuiz(Base):
    __tablename__ = "generated_quizzes"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    document_id: Mapped[Optional[str]] = mapped_column(ForeignKey("documents.id", ondelete="SET NULL"))
    created_by_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    status: Mapped[QuizStatus] = mapped_column(Enum(QuizStatus), default=QuizStatus.DRAFT)
    generation_prompt: Mapped[Optional[str]] = mapped_column(Text)
    total_questions: Mapped[int] = mapped_column(Integer, default=0)
    competency_id: Mapped[Optional[str]] = mapped_column(ForeignKey("competencies.id", ondelete="SET NULL"))
    reviewer_notes: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)

    questions: Mapped[list["GeneratedQuestion"]] = relationship(
        back_populates="quiz", cascade="all, delete-orphan"
    )
    attempts: Mapped[list["QuizAttempt"]] = relationship(back_populates="quiz")

    def __repr__(self) -> str:
        return f"<GeneratedQuiz {self.title[:40]} [{self.status}]>"


class GeneratedQuestion(Base):
    __tablename__ = "generated_questions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    quiz_id: Mapped[str] = mapped_column(ForeignKey("generated_quizzes.id", ondelete="CASCADE"), nullable=False)
    question_text: Mapped[str] = mapped_column(Text, nullable=False)
    option_a: Mapped[str] = mapped_column(Text, nullable=False)
    option_b: Mapped[str] = mapped_column(Text, nullable=False)
    option_c: Mapped[str] = mapped_column(Text, nullable=False)
    option_d: Mapped[str] = mapped_column(Text, nullable=False)
    correct_answer: Mapped[str] = mapped_column(String(1), nullable=False)
    explanation: Mapped[Optional[str]] = mapped_column(Text)
    difficulty: Mapped[QuestionDifficulty] = mapped_column(Enum(QuestionDifficulty), default=QuestionDifficulty.MEDIUM)
    topic_tags: Mapped[Optional[str]] = mapped_column(Text)          # JSON list
    competency_id: Mapped[Optional[str]] = mapped_column(ForeignKey("competencies.id", ondelete="SET NULL"))
    source_document_id: Mapped[Optional[str]] = mapped_column(ForeignKey("documents.id"))
    source_page: Mapped[Optional[int]] = mapped_column(Integer)
    sequence_order: Mapped[int] = mapped_column(Integer, default=0)
    is_validated: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    quiz: Mapped["GeneratedQuiz"] = relationship(back_populates="questions")

    def __repr__(self) -> str:
        return f"<GeneratedQuestion quiz={self.quiz_id} diff={self.difficulty}>"


class QuizAttempt(Base):
    __tablename__ = "quiz_attempts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    quiz_id: Mapped[str] = mapped_column(ForeignKey("generated_quizzes.id", ondelete="CASCADE"), nullable=False)
    learner_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    score: Mapped[Optional[float]] = mapped_column(Float)
    total_questions: Mapped[int] = mapped_column(Integer, default=0)
    correct_answers: Mapped[int] = mapped_column(Integer, default=0)
    is_complete: Mapped[bool] = mapped_column(Boolean, default=False)
    answers: Mapped[Optional[str]] = mapped_column(Text)  # JSON: {question_id: selected_answer}

    quiz: Mapped["GeneratedQuiz"] = relationship(back_populates="attempts")
    learner: Mapped["User"] = relationship(back_populates="quiz_attempts")

    def __repr__(self) -> str:
        return f"<QuizAttempt quiz={self.quiz_id} learner={self.learner_id}>"
