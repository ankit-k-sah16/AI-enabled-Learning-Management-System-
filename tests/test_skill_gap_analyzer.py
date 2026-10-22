"""
tests/test_skill_gap_analyzer.py — Unit tests for the skill gap analysis module.
"""

from __future__ import annotations

import pytest
from src.ai.skill_gap_analyzer import (
    compute_gap,
    compute_raw_priority,
    analyse_skill_gaps,
    SkillGapReport,
    CompetencyGapRecord,
)


# ── compute_gap ───────────────────────────────────────────────────────────────

class TestComputeGap:
    def test_gap_when_below_requirement(self):
        assert compute_gap(70.0, 40.0) == pytest.approx(30.0)

    def test_no_gap_when_meets_requirement(self):
        assert compute_gap(70.0, 70.0) == pytest.approx(0.0)

    def test_no_gap_when_exceeds_requirement(self):
        assert compute_gap(70.0, 90.0) == pytest.approx(0.0)

    def test_not_assessed_returns_required_score(self):
        gap = compute_gap(70.0, None)
        assert gap == pytest.approx(70.0)

    def test_zero_requirement_no_gap(self):
        assert compute_gap(0.0, 50.0) == pytest.approx(0.0)


# ── compute_raw_priority ──────────────────────────────────────────────────────

class TestComputeRawPriority:
    def test_basic_priority(self):
        assert compute_raw_priority(30.0, 2.0) == pytest.approx(60.0)

    def test_zero_gap_zero_priority(self):
        assert compute_raw_priority(0.0, 2.0) == pytest.approx(0.0)

    def test_negative_inputs_clamped(self):
        assert compute_raw_priority(-10.0, -5.0) == pytest.approx(0.0)


# ── analyse_skill_gaps ────────────────────────────────────────────────────────

ROLE_REQS = [
    {"competency_id": "C1", "required_score": 70.0, "importance": 1.5},
    {"competency_id": "C2", "required_score": 60.0, "importance": 1.0},
    {"competency_id": "C3", "required_score": 80.0, "importance": 2.0},
]

COMP_META = {
    "C1": {"name": "Survey Design", "category": "Technical"},
    "C2": {"name": "Data Quality", "category": "Technical"},
    "C3": {"name": "Statistical Inference", "category": "Technical"},
}


class TestAnalyseSkillGaps:
    def _scores(self, c1=40.0, c2=65.0, c3=50.0):
        return {
            "C1": {"score": c1, "confidence": 0.8, "proficiency_level": "Beginner"},
            "C2": {"score": c2, "confidence": 0.9, "proficiency_level": "Intermediate"},
            "C3": {"score": c3, "confidence": 0.7, "proficiency_level": "Beginner"},
        }

    def test_returns_report(self):
        report = analyse_skill_gaps(
            "learner1", "R1", "Test Role", ROLE_REQS, self._scores()
        )
        assert isinstance(report, SkillGapReport)

    def test_correct_gap_count(self):
        report = analyse_skill_gaps(
            "learner1", "R1", "Test Role", ROLE_REQS, self._scores()
        )
        # C1: gap=30, C2: gap=0, C3: gap=30
        assert report.total_with_gap == 2
        assert report.total_no_gap == 1

    def test_no_gaps_when_all_met(self):
        scores = {
            "C1": {"score": 80.0, "confidence": 1.0},
            "C2": {"score": 80.0, "confidence": 1.0},
            "C3": {"score": 90.0, "confidence": 1.0},
        }
        report = analyse_skill_gaps("learner1", "R1", "Test Role", ROLE_REQS, scores)
        assert report.total_with_gap == 0
        assert report.role_readiness_pct == pytest.approx(100.0)

    def test_all_unassessed(self):
        scores: dict = {}
        report = analyse_skill_gaps("learner1", "R1", "Test Role", ROLE_REQS, scores)
        assert report.total_unassessed == 3
        assert report.total_assessed == 0
        assert len(report.unassessed_competencies) == 3

    def test_partial_assessment(self):
        scores = {"C1": {"score": 40.0, "confidence": 0.8}}
        report = analyse_skill_gaps("learner1", "R1", "Test Role", ROLE_REQS, scores)
        assert report.total_assessed == 1
        assert report.total_unassessed == 2

    def test_priority_ranking_ordered(self):
        report = analyse_skill_gaps(
            "learner1", "R1", "Test Role", ROLE_REQS, self._scores(),
            competency_meta=COMP_META,
        )
        assessed_with_gaps = [r for r in report.competency_gaps if r.is_assessed and r.gap_score > 0]
        if len(assessed_with_gaps) > 1:
            for i in range(len(assessed_with_gaps) - 1):
                assert assessed_with_gaps[i].priority_rank <= assessed_with_gaps[i + 1].priority_rank

    def test_priority_scores_normalised_to_100(self):
        report = analyse_skill_gaps(
            "learner1", "R1", "Test Role", ROLE_REQS, self._scores(),
        )
        assessed_with_gaps = [r for r in report.competency_gaps if r.is_assessed and r.gap_score > 0]
        if assessed_with_gaps:
            max_priority = max(r.priority_score for r in assessed_with_gaps)
            assert max_priority == pytest.approx(100.0, abs=0.1)

    def test_explanation_set_for_each_record(self):
        report = analyse_skill_gaps(
            "learner1", "R1", "Test Role", ROLE_REQS, self._scores(),
            competency_meta=COMP_META,
        )
        for rec in report.competency_gaps:
            assert rec.explanation, f"Missing explanation for {rec.competency_id}"

    def test_empty_requirements(self):
        report = analyse_skill_gaps("learner1", "R1", "Test Role", [], {})
        assert report.total_required == 0
        assert len(report.warnings) > 0

    def test_required_score_above_100_clamped(self):
        reqs = [{"competency_id": "C1", "required_score": 150.0, "importance": 1.0}]
        scores = {"C1": {"score": 50.0, "confidence": 0.8}}
        report = analyse_skill_gaps("learner1", "R1", "Test Role", reqs, scores)
        rec = report.competency_gaps[0]
        assert rec.required_score == pytest.approx(100.0)
        assert any("clamped" in w for w in report.warnings)

    def test_json_serialisation(self):
        report = analyse_skill_gaps(
            "learner1", "R1", "Test Role", ROLE_REQS, self._scores()
        )
        import json
        data = json.loads(report.to_json())
        assert data["learner_id"] == "learner1"
        assert "competency_gaps" in data

    def test_readiness_pct_correct(self):
        scores = {
            "C1": {"score": 80.0, "confidence": 1.0},
            "C2": {"score": 80.0, "confidence": 1.0},
            "C3": {"score": 50.0, "confidence": 1.0},  # gap
        }
        report = analyse_skill_gaps("learner1", "R1", "Test Role", ROLE_REQS, scores)
        # 2 of 3 met → 66.7%
        assert report.role_readiness_pct == pytest.approx(66.7, abs=0.2)

    def test_competency_meta_applied(self):
        report = analyse_skill_gaps(
            "learner1", "R1", "Test Role", ROLE_REQS, self._scores(),
            competency_meta=COMP_META,
        )
        c1_rec = next(r for r in report.competency_gaps if r.competency_id == "C1")
        assert c1_rec.competency_name == "Survey Design"
