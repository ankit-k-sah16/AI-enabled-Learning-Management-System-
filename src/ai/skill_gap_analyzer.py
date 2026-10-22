"""
ai/skill_gap_analyzer.py — Skill Gap Analysis Module.

For each required competency, computes the gap between the learner's
current assessed proficiency and the role requirement.

Formulas (all documented):
    gap_score       = max(0.0, required_score − current_score)
    priority_score  = gap_score × importance          (raw)
    priority_score  = normalized to [0, 100]          (normalised)

Unassessed competencies are NOT treated as 0-proficiency.
They are flagged separately and recommended for assessment first.

Machine-readable JSON output is produced alongside structured dataclasses.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Optional

from src.core.config import settings


# ── Data Contracts ────────────────────────────────────────────────────────────

@dataclass
class CompetencyGapRecord:
    """
    Skill gap for a single competency.

    Attributes:
        competency_id:     Stable competency ID.
        competency_name:   Human-readable name.
        competency_category: Category (Technical, Domain, etc.)
        current_score:     Learner's assessed score (None = not assessed).
        required_score:    Required score for the role.
        gap_score:         max(0, required − current).  0 if not assessed (see is_assessed).
        importance:        Role-defined weight for this competency (default 1.0).
        priority_score:    Normalised priority 0–100 (higher = more urgent).
        priority_rank:     Integer rank (1 = highest priority).
        is_assessed:       False when current_score is None.
        proficiency_current:  Label for current score.
        proficiency_required: Label for required score.
        explanation:       Human-readable explanation.
        confidence:        Assessment confidence (0–1) from scoring engine.
    """
    competency_id: str
    competency_name: str = ""
    competency_category: str = ""
    current_score: Optional[float] = None
    required_score: float = 0.0
    gap_score: float = 0.0
    importance: float = 1.0
    priority_score: float = 0.0      # normalised 0–100
    priority_rank: Optional[int] = None
    is_assessed: bool = False
    proficiency_current: str = "Unknown"
    proficiency_required: str = "Unknown"
    explanation: str = ""
    confidence: float = 0.0


@dataclass
class SkillGapReport:
    """
    Complete skill gap analysis for a learner against a job role.

    Attributes:
        learner_id:       Learner's user ID.
        job_role_id:      Job role context.
        job_role_name:    Human-readable role name.
        analysed_at:      UTC timestamp.
        total_required:   How many competencies the role requires.
        total_assessed:   How many the learner has assessment data for.
        total_with_gap:   How many assessed competencies have gap > 0.
        total_no_gap:     How many assessed competencies have gap = 0.
        total_unassessed: How many still need assessment.
        average_gap:      Mean gap score across assessed competencies.
        role_readiness_pct: Rough readiness metric (100 = fully ready).
        competency_gaps:  Ranked list of CompetencyGapRecord.
        unassessed_competencies: List of competency IDs needing assessment.
        summary:          Plain-language summary paragraph.
        warnings:         Any data-quality notes.
    """
    learner_id: str
    job_role_id: str
    job_role_name: str = ""
    analysed_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    total_required: int = 0
    total_assessed: int = 0
    total_with_gap: int = 0
    total_no_gap: int = 0
    total_unassessed: int = 0
    average_gap: float = 0.0
    role_readiness_pct: float = 0.0
    competency_gaps: list[CompetencyGapRecord] = field(default_factory=list)
    unassessed_competencies: list[str] = field(default_factory=list)
    summary: str = ""
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["analysed_at"] = self.analysed_at.isoformat()
        return d

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), default=str, indent=2)


# ── Gap Computation ───────────────────────────────────────────────────────────

def compute_gap(
    required_score: float,
    current_score: Optional[float],
) -> float:
    """
    Compute raw skill gap.

    Formula: gap = max(0.0, required_score − current_score)
    If current_score is None (not assessed): gap = required_score
    (treated conservatively — full gap assumed, but flagged separately).
    """
    if current_score is None:
        # Do NOT silently treat unknown as zero.
        # Return required score as the conservative bound,
        # but is_assessed=False so callers can distinguish.
        return float(required_score)
    return max(0.0, required_score - current_score)


def compute_raw_priority(gap_score: float, importance: float) -> float:
    """
    Raw priority score (before normalisation).

    Formula: priority = gap_score × importance
    Both inputs are clamped to non-negative values.
    """
    return max(0.0, gap_score) * max(0.0, importance)


def _normalise_scores(
    records: list[CompetencyGapRecord],
) -> list[CompetencyGapRecord]:
    """
    Normalise raw priority scores to 0–100 across all records.

    Formula: normalised = (raw / max_raw) × 100
    If max_raw == 0, all priorities are 0.
    """
    raw_priorities = [r.priority_score for r in records]
    max_raw = max(raw_priorities) if raw_priorities else 0.0

    for rec in records:
        if max_raw > 0:
            rec.priority_score = round((rec.priority_score / max_raw) * 100.0, 2)
        else:
            rec.priority_score = 0.0

    return records


def _build_explanation(rec: CompetencyGapRecord) -> str:
    """Generate a transparent plain-language explanation for a gap record."""
    if not rec.is_assessed:
        return (
            f"'{rec.competency_name}' has not been assessed yet. "
            f"This role requires a score of {rec.required_score:.0f}/100 "
            f"({rec.proficiency_required}). "
            "Assessment is recommended before prioritising learning resources."
        )
    if rec.gap_score <= 0:
        return (
            f"No gap detected for '{rec.competency_name}'. "
            f"Current score {rec.current_score:.0f} meets or exceeds the "
            f"required score of {rec.required_score:.0f}."
        )
    return (
        f"'{rec.competency_name}' shows a gap of {rec.gap_score:.0f} points. "
        f"Current proficiency is {rec.proficiency_current} ({rec.current_score:.0f}/100); "
        f"the role requires {rec.proficiency_required} ({rec.required_score:.0f}/100). "
        f"Importance weight: {rec.importance:.2f}. "
        f"Priority score: {rec.priority_score:.1f}/100."
    )


def analyse_skill_gaps(
    learner_id: str,
    job_role_id: str,
    job_role_name: str,
    role_requirements: list[dict],
    learner_scores: dict[str, dict],
    competency_meta: Optional[dict[str, dict]] = None,
) -> SkillGapReport:
    """
    Perform skill gap analysis for one learner against one job role.

    Args:
        learner_id:       Learner's user ID.
        job_role_id:      Job role being compared against.
        job_role_name:    Human-readable name for the role.
        role_requirements: List of dicts:
            {competency_id, required_score, importance}
        learner_scores:   Dict keyed by competency_id:
            {score: float|None, confidence: float, proficiency_level: str}
        competency_meta:  Optional dict keyed by competency_id:
            {name: str, category: str}

    Returns:
        SkillGapReport with ranked gap records and summary.

    Edge cases:
    - Empty role_requirements → empty report with warning.
    - All competencies unassessed → all flagged for assessment.
    - Required score 0 → gap always 0 (no skill needed).
    - required_score > 100 → clamped with warning.
    - importance ≤ 0 → clamped to 0.01 with warning.
    """
    warnings: list[str] = []
    meta = competency_meta or {}

    if not role_requirements:
        warnings.append("No competency requirements found for this role.")
        return SkillGapReport(
            learner_id=learner_id,
            job_role_id=job_role_id,
            job_role_name=job_role_name,
            warnings=warnings,
        )

    gap_records: list[CompetencyGapRecord] = []
    unassessed: list[str] = []

    for req in role_requirements:
        cid = req.get("competency_id", "")
        if not cid:
            warnings.append("Skipped a requirement with missing competency_id.")
            continue

        required_score = float(req.get("required_score", 0.0))
        if required_score > 100.0:
            warnings.append(
                f"required_score {required_score} for {cid} exceeds 100; clamped."
            )
            required_score = 100.0

        importance = float(req.get("importance", 1.0))
        if importance <= 0:
            warnings.append(
                f"importance {importance} for {cid} is ≤ 0; clamped to 0.01."
            )
            importance = 0.01

        learner_data = learner_scores.get(cid, {})
        current_score: Optional[float] = learner_data.get("score")  # None = not assessed
        confidence: float = float(learner_data.get("confidence", 0.0))
        is_assessed = current_score is not None

        gap_score = compute_gap(required_score, current_score)
        raw_priority = compute_raw_priority(gap_score if is_assessed else 0.0, importance)
        # Unassessed competencies get a separate flag; priority is set to 0 here
        # so normalisation reflects only assessed gaps.
        # They are surfaced separately in unassessed_competencies.

        cname = meta.get(cid, {}).get("name", cid)
        ccat = meta.get(cid, {}).get("category", "")

        rec = CompetencyGapRecord(
            competency_id=cid,
            competency_name=cname,
            competency_category=ccat,
            current_score=current_score,
            required_score=required_score,
            gap_score=gap_score if is_assessed else required_score,
            importance=importance,
            priority_score=raw_priority,  # will be normalised below
            is_assessed=is_assessed,
            proficiency_current=settings.score_to_proficiency(current_score) if is_assessed else "Unknown",
            proficiency_required=settings.score_to_proficiency(required_score),
            confidence=confidence,
        )

        if not is_assessed:
            unassessed.append(cid)

        gap_records.append(rec)

    # Normalise priority scores (only across assessed competencies)
    assessed_records = [r for r in gap_records if r.is_assessed]
    _normalise_scores(assessed_records)

    # Rank assessed records by priority_score descending, then unassessed
    assessed_with_gap = sorted(
        [r for r in assessed_records if r.gap_score > 0],
        key=lambda r: r.priority_score,
        reverse=True,
    )
    assessed_no_gap = [r for r in assessed_records if r.gap_score <= 0]
    unassessed_records = [r for r in gap_records if not r.is_assessed]

    ranked = assessed_with_gap + assessed_no_gap + unassessed_records
    for i, rec in enumerate(ranked):
        rec.priority_rank = i + 1
        rec.explanation = _build_explanation(rec)

    # Summary statistics
    total_required = len(gap_records)
    total_assessed = len(assessed_records)
    total_with_gap = len(assessed_with_gap)
    total_no_gap = len(assessed_no_gap)
    total_unassessed = len(unassessed_records)
    average_gap = (
        sum(r.gap_score for r in assessed_with_gap) / len(assessed_with_gap)
        if assessed_with_gap else 0.0
    )

    # Role readiness: percentage of required competencies with no gap
    if total_required > 0:
        role_readiness_pct = round((total_no_gap / total_required) * 100.0, 1)
    else:
        role_readiness_pct = 0.0

    # Summary paragraph
    if total_unassessed > 0 and total_assessed == 0:
        summary = (
            f"No assessments found for any of the {total_required} required competencies. "
            "Complete a baseline assessment to receive personalised gap analysis."
        )
    elif total_with_gap == 0:
        summary = (
            f"All {total_assessed} assessed competencies meet the requirements for "
            f"'{job_role_name}'. Role readiness: {role_readiness_pct:.0f}%."
        )
    else:
        summary = (
            f"Analysis for role '{job_role_name}': {total_required} competencies required, "
            f"{total_assessed} assessed, {total_with_gap} with gaps. "
            f"Average gap: {average_gap:.1f} points. "
            f"Role readiness: {role_readiness_pct:.0f}%. "
            f"{total_unassessed} competency(s) still need assessment."
        )

    return SkillGapReport(
        learner_id=learner_id,
        job_role_id=job_role_id,
        job_role_name=job_role_name,
        total_required=total_required,
        total_assessed=total_assessed,
        total_with_gap=total_with_gap,
        total_no_gap=total_no_gap,
        total_unassessed=total_unassessed,
        average_gap=round(average_gap, 2),
        role_readiness_pct=role_readiness_pct,
        competency_gaps=ranked,
        unassessed_competencies=unassessed,
        summary=summary,
        warnings=warnings,
    )
