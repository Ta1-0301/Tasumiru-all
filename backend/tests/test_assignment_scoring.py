# backend/tests/test_assignment_scoring.py
"""backend/pipeline/assignment/scoring.py の単体テスト（Step 2、決定的）。"""

import pytest

from backend.pipeline.assignment.schema import AssignmentTask, RequiredSkill, ScoringWeights
from backend.pipeline.assignment.scoring import (
    detect_close_scores,
    score_availability,
    score_candidate,
    score_candidates,
    score_experience,
    score_skill_match,
    score_workload,
)
from backend.pipeline.members.schema import Availability, Member, Skill


def _member(**overrides) -> Member:
    defaults = dict(
        id="M-001",
        name="山田太郎",
        skills=[Skill(skill="Python", level=5, experience_years=5)],
        experience_years=8,
        availability=Availability(available_hours_per_week=40, working_days=["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"], current_assigned_hours=10),
        constraints=[],
    )
    defaults.update(overrides)
    return Member(**defaults)


def _task(**overrides) -> AssignmentTask:
    defaults = dict(
        task_id="TASK-001",
        title="バックエンドAPIを実装する",
        required_skills=[RequiredSkill(skill="Python", min_level=3)],
        estimated_hours=8,
    )
    defaults.update(overrides)
    return AssignmentTask(**defaults)


# --- perfect match vs partial match ---

def test_skill_match_is_perfect_for_expert_level():
    member = _member(skills=[Skill(skill="Python", level=5)])
    assert score_skill_match(_task(), member) == 1.0


def test_skill_match_is_partial_for_bare_minimum_level():
    task = _task(required_skills=[RequiredSkill(skill="Python", min_level=3)])
    member = _member(skills=[Skill(skill="Python", level=3)])
    score = score_skill_match(task, member)
    assert 0 < score < 1.0


def test_skill_match_with_no_required_skills_is_full_score():
    assert score_skill_match(_task(required_skills=[]), _member()) == 1.0


def test_perfect_match_scores_higher_than_partial_match():
    task = _task(required_skills=[RequiredSkill(skill="Python", min_level=3)])
    expert = score_candidate(task, _member(id="M-expert", skills=[Skill(skill="Python", level=5, experience_years=5)]))
    minimal = score_candidate(task, _member(id="M-minimal", skills=[Skill(skill="Python", level=3, experience_years=1)]))
    assert expert.score > minimal.score


# --- workload ---

def test_workload_score_favors_more_remaining_capacity():
    task = _task(estimated_hours=8)
    loaded = score_workload(task, _member(availability=Availability(available_hours_per_week=40, current_assigned_hours=30)))
    free = score_workload(task, _member(availability=Availability(available_hours_per_week=40, current_assigned_hours=5)))
    assert free > loaded


def test_workload_score_is_zero_when_available_hours_is_zero():
    member = _member(availability=Availability(available_hours_per_week=0, current_assigned_hours=0))
    assert score_workload(_task(), member) == 0.0


# --- experience ---

def test_experience_score_uses_skill_specific_years_when_present():
    member = _member(skills=[Skill(skill="Python", level=5, experience_years=5)])
    assert score_experience(_task(), member) == pytest.approx(1.0)


def test_experience_score_falls_back_to_overall_when_skill_years_missing():
    member = _member(skills=[Skill(skill="Python", level=5, experience_years=None)], experience_years=5)
    assert score_experience(_task(), member) == pytest.approx(0.5)


def test_experience_score_is_neutral_when_no_experience_data_at_all():
    member = _member(skills=[Skill(skill="Python", level=5, experience_years=None)], experience_years=None)
    assert score_experience(_task(), member) == 0.5


# --- availability ---

def test_availability_score_scales_with_working_days():
    full_week = _member(availability=Availability(available_hours_per_week=40, working_days=["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]))
    part_time = _member(id="M-002", availability=Availability(available_hours_per_week=40, working_days=["Monday"]))
    assert score_availability(full_week) > score_availability(part_time)


# --- configurable weights ---

def test_custom_weights_change_the_final_score():
    task = _task()
    member = _member()
    default_score = score_candidate(task, member).score
    skill_heavy_score = score_candidate(
        task, member, ScoringWeights(skill_match=1.0, workload=0.0, experience=0.0, availability=0.0)
    ).score
    assert default_score != skill_heavy_score


# --- multiple candidates / equal candidates ---

def test_score_candidates_orders_by_score_descending():
    task = _task()
    strong = _member(id="M-strong", skills=[Skill(skill="Python", level=5, experience_years=5)])
    weak = _member(id="M-weak", skills=[Skill(skill="Python", level=3, experience_years=0)])
    scores = score_candidates(task, [weak, strong])
    assert [s.member_id for s in scores] == ["M-strong", "M-weak"]


def test_detect_close_scores_flags_near_tie():
    from backend.pipeline.assignment.schema import CandidateScore

    a = CandidateScore(member_id="M-001", skill_match=1, workload_score=1, experience_score=1, availability_score=1, score=90.0)
    b = CandidateScore(member_id="M-002", skill_match=1, workload_score=1, experience_score=1, availability_score=1, score=89.0)
    warning = detect_close_scores([a, b], margin=2.0)
    assert warning is not None
    assert "M-001" in warning and "M-002" in warning


def test_detect_close_scores_returns_none_for_clear_winner():
    from backend.pipeline.assignment.schema import CandidateScore

    a = CandidateScore(member_id="M-001", skill_match=1, workload_score=1, experience_score=1, availability_score=1, score=95.0)
    b = CandidateScore(member_id="M-002", skill_match=1, workload_score=1, experience_score=1, availability_score=1, score=60.0)
    assert detect_close_scores([a, b], margin=2.0) is None


def test_detect_close_scores_returns_none_for_single_candidate():
    from backend.pipeline.assignment.schema import CandidateScore

    a = CandidateScore(member_id="M-001", skill_match=1, workload_score=1, experience_score=1, availability_score=1, score=95.0)
    assert detect_close_scores([a]) is None
