# backend/tests/test_assignment_filters.py
"""backend/pipeline/assignment/filters.py の単体テスト（Step 1、決定的）。"""

from backend.pipeline.assignment.filters import filter_candidates
from backend.pipeline.assignment.schema import AssignmentTask, RequiredSkill
from backend.pipeline.members.schema import Availability, Constraint, Member, Skill


def _member(**overrides) -> Member:
    defaults = dict(
        id="M-001",
        name="山田太郎",
        skills=[Skill(skill="Python", level=5, experience_years=3)],
        availability=Availability(available_hours_per_week=40, working_days=["Monday", "Tuesday"], current_assigned_hours=10),
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


# --- insufficient required skill ---

def test_member_missing_required_skill_is_rejected():
    member = _member(skills=[Skill(skill="Go", level=5)])
    survivors, rejections = filter_candidates(_task(), [member])
    assert survivors == []
    assert "必要スキル" in rejections[0].reasons[0]


def test_member_with_skill_below_required_level_is_rejected():
    member = _member(skills=[Skill(skill="Python", level=1)])
    survivors, rejections = filter_candidates(_task(), [member])
    assert survivors == []
    assert any("レベルが不足" in r for r in rejections[0].reasons)


def test_member_with_sufficient_skill_passes():
    member = _member(skills=[Skill(skill="Python", level=3)])
    survivors, rejections = filter_candidates(_task(), [member])
    assert len(survivors) == 1
    assert rejections == []


# --- unavailable ---

def test_member_with_zero_remaining_capacity_is_rejected_as_unavailable():
    member = _member(availability=Availability(available_hours_per_week=40, current_assigned_hours=40))
    survivors, rejections = filter_candidates(_task(), [member])
    assert survivors == []
    assert any("unavailable" in r for r in rejections[0].reasons)


def test_member_with_negative_remaining_capacity_is_rejected_as_unavailable():
    member = _member(availability=Availability(available_hours_per_week=40, current_assigned_hours=50))
    survivors, rejections = filter_candidates(_task(), [member])
    assert survivors == []
    assert any("unavailable" in r for r in rejections[0].reasons)


# --- workload exceeds maximum ---

def test_task_exceeding_remaining_capacity_is_rejected_as_overloaded():
    member = _member(availability=Availability(available_hours_per_week=40, current_assigned_hours=35))
    survivors, rejections = filter_candidates(_task(estimated_hours=10), [member])
    assert survivors == []
    assert any("workload exceeds maximum" in r for r in rejections[0].reasons)


def test_task_fitting_within_remaining_capacity_passes():
    member = _member(availability=Availability(available_hours_per_week=40, current_assigned_hours=35))
    survivors, rejections = filter_candidates(_task(estimated_hours=5), [member])
    assert len(survivors) == 1


# --- explicit assignment restriction (constraint violation) ---

def test_scope_restriction_mismatch_is_rejected():
    member = _member(constraints=[Constraint(type="scope_restriction", value="frontend")])
    survivors, rejections = filter_candidates(_task(domain="backend"), [member])
    assert survivors == []
    assert any("対象領域" in r for r in rejections[0].reasons)


def test_scope_restriction_match_passes():
    member = _member(constraints=[Constraint(type="scope_restriction", value="backend")])
    survivors, rejections = filter_candidates(_task(domain="backend"), [member])
    assert len(survivors) == 1


def test_scope_restriction_is_ignored_when_task_has_no_domain():
    member = _member(constraints=[Constraint(type="scope_restriction", value="frontend")])
    survivors, rejections = filter_candidates(_task(domain=None), [member])
    assert len(survivors) == 1


def test_max_hours_per_week_constraint_violation_is_rejected():
    member = _member(
        availability=Availability(available_hours_per_week=40, current_assigned_hours=2),
        constraints=[Constraint(type="max_hours_per_week", max_hours=8)],
    )
    survivors, rejections = filter_candidates(_task(estimated_hours=10), [member])
    assert survivors == []
    assert any("週あたり工数上限" in r for r in rejections[0].reasons)


def test_requires_review_constraint_is_soft_and_does_not_reject():
    """requires_reviewはハード制約ではない（アサイン自体は可能、警告はrunner.py側の責務）"""
    member = _member(constraints=[Constraint(type="requires_review", value="senior member")])
    survivors, rejections = filter_candidates(_task(), [member])
    assert len(survivors) == 1
    assert rejections == []


# --- multiple hard-constraint failures on one member ---

def test_member_can_fail_multiple_checks_at_once():
    member = _member(
        skills=[],
        availability=Availability(available_hours_per_week=40, current_assigned_hours=40),
    )
    survivors, rejections = filter_candidates(_task(), [member])
    assert survivors == []
    assert len(rejections[0].reasons) >= 2
