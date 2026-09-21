# backend/tests/test_skill_matching.py
"""backend/services/skill_matching.py の単体テスト（Part 5/7/17、決定的）。

依頼のPart 17に明記された観点をカバーする:
  exact skill match / partial match / no match / multiple members /
  missing skills / deterministic results
"""

from backend.pipeline.members.schema import Availability, Member
from backend.services.skill_matching import match_task_to_members, skill_similarity


def _member(id: str, skills):
    return Member(
        id=id, name=id, skills=[{"skill": s, "level": 3} for s in skills],
        availability=Availability(available_hours_per_week=40, working_days=["Monday"]),
    )


# --- exact match ---

def test_identical_skill_sets_score_high():
    score = skill_similarity(["Python", "FastAPI"], ["Python", "FastAPI"])
    assert score > 0.9


# --- partial match ---

def test_partial_overlap_scores_between_zero_and_one():
    score = skill_similarity(["Python", "FastAPI", "REST API"], ["Python", "FastAPI", "SQL"])
    assert 0.0 < score < 1.0


def test_partial_overlap_scores_higher_than_no_overlap():
    partial = skill_similarity(["Python", "FastAPI"], ["Python", "SQL"])
    none = skill_similarity(["Python", "FastAPI"], ["Photoshop", "Illustrator"])
    assert partial > none


# --- no match ---

def test_disjoint_skill_sets_score_zero():
    score = skill_similarity(["Python", "FastAPI"], ["Photoshop", "Illustrator"])
    assert score == 0.0


# --- missing skills ---

def test_no_required_skills_scores_full_because_no_constraint():
    assert skill_similarity([], ["Python"]) == 1.0


def test_member_with_no_skills_scores_zero_when_task_requires_skills():
    assert skill_similarity(["Python"], []) == 0.0


# --- normalization is applied before comparison ---

def test_name_variants_are_recognized_as_matching():
    score = skill_similarity(["Python3", "REST API"], ["python", "RESTful API"])
    assert score > 0.9


# --- multiple members / ranking ---

def test_match_task_to_members_ranks_best_match_first():
    strong = _member("M-strong", ["Python", "FastAPI"])
    weak = _member("M-weak", ["Photoshop", "Illustrator"])

    results = match_task_to_members(["Python", "FastAPI", "REST API"], [weak, strong])

    assert results[0].member_id == "M-strong"
    assert results[0].skill_similarity > results[1].skill_similarity


def test_match_task_to_members_handles_empty_member_list():
    assert match_task_to_members(["Python"], []) == []


# --- deterministic results ---

def test_results_are_deterministic_across_calls():
    a = skill_similarity(["Python", "FastAPI"], ["Python", "SQL"])
    b = skill_similarity(["Python", "FastAPI"], ["Python", "SQL"])
    assert a == b

    members = [_member("M-1", ["Python"]), _member("M-2", ["Go"])]
    first = match_task_to_members(["Python"], members)
    second = match_task_to_members(["Python"], members)
    assert [(r.member_id, r.skill_similarity) for r in first] == [(r.member_id, r.skill_similarity) for r in second]


# --- sklearn internals must not leak ---

def test_return_types_are_plain_python():
    score = skill_similarity(["Python"], ["Python"])
    assert isinstance(score, float)

    results = match_task_to_members(["Python"], [_member("M-1", ["Python"])])
    assert isinstance(results[0].skill_similarity, float)
