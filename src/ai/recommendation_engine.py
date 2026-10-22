"""
ai/recommendation_engine.py — Hybrid Personalized Recommendation Engine.

Strategy (in priority order):
1. Competency-to-resource mapping (explicit catalog linkage).
2. Semantic similarity via local sentence-transformer embeddings.
3. Role relevance, difficulty alignment, prerequisite awareness.
4. Completion history (avoids re-recommending finished resources).

The engine produces scored, ranked, explainable recommendations.
It does NOT require Groq — the baseline works entirely locally.
Groq integration is planned for narrative pathway summaries (Phase 4).

Embedding model: all-MiniLM-L6-v2 (local, ~80 MB, CPU-friendly).
Fallback: if sentence-transformers unavailable, use metadata-only ranking.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field, asdict
from typing import Optional

from src.core.config import settings
from src.ai.skill_gap_analyzer import CompetencyGapRecord


# ── Embedding Helper ──────────────────────────────────────────────────────────

_embedding_model = None
_embedding_available = False


def _get_embedding_model():
    """Lazy-load the sentence transformer model."""
    global _embedding_model, _embedding_available
    if _embedding_model is not None:
        return _embedding_model
    try:
        from sentence_transformers import SentenceTransformer
        _embedding_model = SentenceTransformer(settings.embedding_model)
        _embedding_available = True
        return _embedding_model
    except Exception:
        _embedding_available = False
        return None


def _cosine_similarity(vec_a: list[float], vec_b: list[float]) -> float:
    """Compute cosine similarity between two vectors."""
    dot = sum(a * b for a, b in zip(vec_a, vec_b))
    norm_a = math.sqrt(sum(a * a for a in vec_a))
    norm_b = math.sqrt(sum(b * b for b in vec_b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def _embed_text(text: str) -> Optional[list[float]]:
    """Generate embedding for a text string. Returns None if unavailable."""
    model = _get_embedding_model()
    if model is None:
        return None
    try:
        vec = model.encode(text, show_progress_bar=False)
        return vec.tolist()
    except Exception:
        return None


# ── Data Contracts ────────────────────────────────────────────────────────────

@dataclass
class ResourceCandidate:
    """
    A learning resource being evaluated for recommendation.

    Populated from the database / catalog.
    """
    resource_id: str
    title: str
    provider: str = ""
    source_url: str = ""
    resource_type: str = "Course"
    difficulty: str = "Beginner"
    description: str = ""
    duration_hours: Optional[float] = None
    language: str = "en"
    prerequisites: list[str] = field(default_factory=list)   # list of resource IDs
    tags: list[str] = field(default_factory=list)
    mapped_competency_ids: list[str] = field(default_factory=list)
    is_verified: bool = False
    data_source: str = ""


@dataclass
class Recommendation:
    """
    A ranked, explainable learning resource recommendation.

    Score components (all 0–1 before weighting):
        competency_match_score:  Catalog mapping (1 if directly mapped, else 0)
        semantic_score:          Cosine similarity between competency and resource descriptions
        difficulty_match_score:  Alignment between gap severity and resource difficulty
        role_relevance_score:    Proportion of role's competencies this resource addresses
        completion_penalty:      0 if completed, 1 if not (penalises re-recommendation)

    Final score:
        score = w1*competency_match + w2*semantic + w3*difficulty + w4*role_relevance
                × completion_penalty
    """
    resource_id: str
    title: str
    provider: str = ""
    source_url: str = ""
    resource_type: str = "Course"
    difficulty: str = "Beginner"
    description: str = ""
    duration_hours: Optional[float] = None
    language: str = "en"
    relevant_competency_ids: list[str] = field(default_factory=list)
    gap_competency_id: str = ""        # primary gap this addresses
    recommendation_score: float = 0.0  # 0–100
    competency_match_score: float = 0.0
    semantic_score: float = 0.0
    difficulty_match_score: float = 0.0
    role_relevance_score: float = 0.0
    explanation: str = ""
    is_completed: bool = False
    data_source: str = ""
    is_verified: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


# ── Scoring Weights (configurable) ───────────────────────────────────────────

DEFAULT_WEIGHTS = {
    "competency_match": 0.40,
    "semantic":         0.30,
    "difficulty":       0.15,
    "role_relevance":   0.15,
}

DIFFICULTY_ORDER = ["Beginner", "Intermediate", "Advanced", "Expert"]


def _difficulty_to_int(d: str) -> int:
    try:
        return DIFFICULTY_ORDER.index(d)
    except ValueError:
        return 0


def _gap_to_difficulty(gap_score: float) -> str:
    """Suggest appropriate resource difficulty level based on gap size."""
    if gap_score >= 60:
        return "Beginner"
    if gap_score >= 40:
        return "Intermediate"
    if gap_score >= 20:
        return "Advanced"
    return "Expert"


def _difficulty_match(resource_difficulty: str, suggested_difficulty: str) -> float:
    """
    Score how well resource difficulty aligns with learner's need.

    Returns 1.0 for exact match, decreasing linearly with distance in difficulty levels.
    """
    rd = _difficulty_to_int(resource_difficulty)
    sd = _difficulty_to_int(suggested_difficulty)
    max_dist = len(DIFFICULTY_ORDER) - 1
    dist = abs(rd - sd)
    return max(0.0, 1.0 - dist / max_dist)


def _build_recommendation_explanation(
    rec: Recommendation,
    gap: CompetencyGapRecord,
    weights: dict,
) -> str:
    """Build a plain-language explanation for a recommendation."""
    parts = []
    parts.append(f"Recommended to address the gap in '{gap.competency_name}'")

    if gap.is_assessed:
        parts.append(
            f"(current: {gap.current_score:.0f}/100, "
            f"required: {gap.required_score:.0f}/100, "
            f"gap: {gap.gap_score:.0f} points)"
        )
    else:
        parts.append("(competency not yet assessed)")

    score_parts = []
    if rec.competency_match_score > 0:
        score_parts.append(f"directly mapped to competency ({rec.competency_match_score:.2f})")
    if rec.semantic_score > 0:
        score_parts.append(f"semantically relevant ({rec.semantic_score:.2f})")
    if rec.difficulty_match_score > 0:
        score_parts.append(f"difficulty alignment ({rec.difficulty_match_score:.2f})")
    if score_parts:
        parts.append(". Score factors: " + ", ".join(score_parts) + ".")
    if not rec.is_verified:
        parts.append(" [Illustrative: not an official verified resource.]")
    return " ".join(parts)


# ── Main Recommendation Function ──────────────────────────────────────────────

def generate_recommendations(
    learner_id: str,
    skill_gaps: list[CompetencyGapRecord],
    resource_catalog: list[ResourceCandidate],
    completed_resource_ids: Optional[set[str]] = None,
    competency_descriptions: Optional[dict[str, str]] = None,
    role_competency_ids: Optional[list[str]] = None,
    max_recommendations: int = 15,
    weights: Optional[dict] = None,
) -> list[Recommendation]:
    """
    Generate personalised, ranked learning resource recommendations.

    Args:
        learner_id:             Learner context (for logging).
        skill_gaps:             Ranked list of CompetencyGapRecord (Phase 2 output).
        resource_catalog:       Available ResourceCandidate list.
        completed_resource_ids: Set of resource IDs already completed.
        competency_descriptions: Optional {competency_id: description} for semantic scoring.
        role_competency_ids:    All competency IDs required by the role (for role_relevance).
        max_recommendations:    Cap on returned recommendations.
        weights:                Score component weights (overrides DEFAULT_WEIGHTS).

    Returns:
        List of Recommendation sorted by recommendation_score desc.
    """
    w = {**DEFAULT_WEIGHTS, **(weights or {})}
    completed = completed_resource_ids or set()
    role_comp_set = set(role_competency_ids or [])
    comp_descs = competency_descriptions or {}

    # Pre-compute embeddings for gap competency descriptions
    gap_embeddings: dict[str, Optional[list[float]]] = {}
    for gap in skill_gaps:
        if gap.competency_id not in gap_embeddings:
            desc = comp_descs.get(gap.competency_id, gap.competency_name)
            gap_embeddings[gap.competency_id] = _embed_text(desc) if desc else None

    # Pre-compute resource embeddings
    resource_embeddings: dict[str, Optional[list[float]]] = {}
    for res in resource_catalog:
        text = f"{res.title}. {res.description}"
        resource_embeddings[res.resource_id] = _embed_text(text)

    recommendations: dict[str, Recommendation] = {}   # resource_id → best rec so far

    # Iterate over gaps (already ordered by priority)
    for gap in skill_gaps:
        if not gap.is_assessed and gap.gap_score <= 0:
            continue  # skip trivial records

        suggested_difficulty = _gap_to_difficulty(gap.gap_score if gap.is_assessed else 50.0)

        for res in resource_catalog:
            is_completed = res.resource_id in completed

            # ── 1. Competency match ──────────────────────────────────
            comp_match = 1.0 if gap.competency_id in res.mapped_competency_ids else 0.0

            # ── 2. Semantic similarity ───────────────────────────────
            sem_score = 0.0
            g_emb = gap_embeddings.get(gap.competency_id)
            r_emb = resource_embeddings.get(res.resource_id)
            if g_emb and r_emb:
                sem_score = max(0.0, _cosine_similarity(g_emb, r_emb))

            # ── 3. Difficulty match ──────────────────────────────────
            diff_match = _difficulty_match(res.difficulty, suggested_difficulty)

            # ── 4. Role relevance ────────────────────────────────────
            if role_comp_set and res.mapped_competency_ids:
                role_rel = len(
                    set(res.mapped_competency_ids) & role_comp_set
                ) / len(role_comp_set)
            else:
                role_rel = 0.0

            # ── Weighted score ───────────────────────────────────────
            raw_score = (
                w["competency_match"] * comp_match
                + w["semantic"] * sem_score
                + w["difficulty"] * diff_match
                + w["role_relevance"] * role_rel
            )

            # Penalise completed resources (but don't fully remove them)
            if is_completed:
                raw_score *= 0.2

            final_score = round(raw_score * 100.0, 2)

            # Keep only the best score per resource (it may address multiple gaps)
            existing = recommendations.get(res.resource_id)
            if existing is None or final_score > existing.recommendation_score:
                rec = Recommendation(
                    resource_id=res.resource_id,
                    title=res.title,
                    provider=res.provider,
                    source_url=res.source_url,
                    resource_type=res.resource_type,
                    difficulty=res.difficulty,
                    description=res.description,
                    duration_hours=res.duration_hours,
                    language=res.language,
                    relevant_competency_ids=res.mapped_competency_ids,
                    gap_competency_id=gap.competency_id,
                    recommendation_score=final_score,
                    competency_match_score=round(comp_match, 4),
                    semantic_score=round(sem_score, 4),
                    difficulty_match_score=round(diff_match, 4),
                    role_relevance_score=round(role_rel, 4),
                    is_completed=is_completed,
                    data_source=res.data_source,
                    is_verified=res.is_verified,
                )
                recommendations[res.resource_id] = rec

    # Attach explanations and sort
    all_recs = sorted(recommendations.values(), key=lambda r: r.recommendation_score, reverse=True)

    # Attach explanation using the gap context of the best-scoring gap
    gap_by_id = {g.competency_id: g for g in skill_gaps}
    for rec in all_recs:
        primary_gap = gap_by_id.get(rec.gap_competency_id)
        if primary_gap:
            rec.explanation = _build_recommendation_explanation(rec, primary_gap, w)

    return all_recs[:max_recommendations]
