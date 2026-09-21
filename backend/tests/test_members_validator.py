# backend/tests/test_members_validator.py
"""backend/pipeline/members/validator.py の単体テスト。LLMは使わない。

依頼された5つの検証カテゴリ（invalid skill levels / negative hours /
workload above capacity / duplicate skills / invalid constraints）を
すべてカバーする。
"""

from backend.pipeline.members.schema import Availability, Constraint, Member, Skill
from backend.pipeline.members.validator import (
    check_duplicate_skills,
    check_invalid_constraints,
    check_invalid_skill_levels,
    check_negative_hours,
    check_workload_above_capacity,
    validate_members,
)


def _member(**overrides) -> Member:
    defaults = dict(
        id="M-001",
        name="山田太郎",
        skills=[Skill(skill="Python", level=5, experience_years=3)],
        availability=Availability(available_hours_per_week=40, working_days=["Monday"], current_assigned_hours=10),
        constraints=[],
    )
    defaults.update(overrides)
    return Member(**defaults)


# --- invalid skill levels ---

def test_invalid_skill_level_too_high_is_flagged():
    member = _member(skills=[Skill(skill="Python", level=9)])
    issues = check_invalid_skill_levels([member])
    assert any(i.code == "INVALID_SKILL_LEVEL" for i in issues)


def test_invalid_skill_level_zero_is_flagged():
    member = _member(skills=[Skill(skill="Python", level=0)])
    issues = check_invalid_skill_levels([member])
    assert any(i.code == "INVALID_SKILL_LEVEL" for i in issues)


def test_valid_skill_levels_are_not_flagged():
    member = _member(skills=[Skill(skill="Python", level=1), Skill(skill="Go", level=5)])
    assert check_invalid_skill_levels([member]) == []


# --- negative hours ---

def test_negative_available_hours_is_flagged():
    member = _member(availability=Availability(available_hours_per_week=-5, current_assigned_hours=0))
    issues = check_negative_hours([member])
    assert any(i.code == "NEGATIVE_HOURS" for i in issues)


def test_negative_current_assigned_hours_is_flagged():
    member = _member(availability=Availability(available_hours_per_week=40, current_assigned_hours=-1))
    issues = check_negative_hours([member])
    assert any(i.code == "NEGATIVE_HOURS" for i in issues)


def test_negative_skill_experience_years_is_flagged():
    member = _member(skills=[Skill(skill="Python", level=3, experience_years=-2)])
    issues = check_negative_hours([member])
    assert any(i.code == "NEGATIVE_HOURS" for i in issues)


def test_negative_constraint_max_hours_is_flagged():
    member = _member(constraints=[Constraint(type="max_hours_per_week", max_hours=-8)])
    issues = check_negative_hours([member])
    assert any(i.code == "NEGATIVE_HOURS" for i in issues)


def test_non_negative_hours_are_not_flagged():
    assert check_negative_hours([_member()]) == []


# --- workload above capacity ---

def test_workload_above_capacity_is_flagged():
    member = _member(availability=Availability(available_hours_per_week=20, current_assigned_hours=30))
    issues = check_workload_above_capacity([member])
    assert any(i.code == "WORKLOAD_ABOVE_CAPACITY" for i in issues)


def test_workload_exactly_at_capacity_is_not_flagged():
    member = _member(availability=Availability(available_hours_per_week=20, current_assigned_hours=20))
    assert check_workload_above_capacity([member]) == []


def test_workload_below_capacity_is_not_flagged():
    assert check_workload_above_capacity([_member()]) == []


# --- duplicate skills ---

def test_duplicate_skill_same_case_is_flagged():
    member = _member(skills=[Skill(skill="Python", level=3), Skill(skill="Python", level=5)])
    issues = check_duplicate_skills([member])
    assert any(i.code == "DUPLICATE_SKILL" for i in issues)


def test_duplicate_skill_different_case_is_flagged():
    member = _member(skills=[Skill(skill="python", level=3), Skill(skill="Python", level=5)])
    issues = check_duplicate_skills([member])
    assert any(i.code == "DUPLICATE_SKILL" for i in issues)


def test_distinct_skills_are_not_flagged_as_duplicate():
    member = _member(skills=[Skill(skill="Python", level=3), Skill(skill="Go", level=2)])
    assert check_duplicate_skills([member]) == []


# --- invalid constraints ---

def test_unknown_constraint_type_is_flagged():
    member = _member(constraints=[Constraint(type="mind_reading", value="x")])
    issues = check_invalid_constraints([member])
    assert any(i.code == "INVALID_CONSTRAINT" for i in issues)


def test_day_unavailable_with_invalid_day_is_flagged():
    member = _member(constraints=[Constraint(type="day_unavailable", value="Blursday")])
    issues = check_invalid_constraints([member])
    assert any(i.code == "INVALID_CONSTRAINT" for i in issues)


def test_day_unavailable_with_valid_day_is_not_flagged():
    member = _member(constraints=[Constraint(type="day_unavailable", value="Monday")])
    assert check_invalid_constraints([member]) == []


def test_max_hours_per_week_without_value_is_flagged():
    member = _member(constraints=[Constraint(type="max_hours_per_week")])
    issues = check_invalid_constraints([member])
    assert any(i.code == "INVALID_CONSTRAINT" for i in issues)


def test_max_hours_per_week_with_value_is_not_flagged():
    member = _member(constraints=[Constraint(type="max_hours_per_week", max_hours=8)])
    assert check_invalid_constraints([member]) == []


def test_scope_restriction_without_value_is_flagged():
    member = _member(constraints=[Constraint(type="scope_restriction")])
    issues = check_invalid_constraints([member])
    assert any(i.code == "INVALID_CONSTRAINT" for i in issues)


def test_scope_restriction_with_value_is_not_flagged():
    member = _member(constraints=[Constraint(type="scope_restriction", value="frontend")])
    assert check_invalid_constraints([member]) == []


def test_requires_review_without_value_is_flagged():
    member = _member(constraints=[Constraint(type="requires_review")])
    issues = check_invalid_constraints([member])
    assert any(i.code == "INVALID_CONSTRAINT" for i in issues)


def test_requires_review_with_value_is_not_flagged():
    member = _member(constraints=[Constraint(type="requires_review", value="senior member")])
    assert check_invalid_constraints([member]) == []


# --- validate_members aggregation ---

def test_validate_members_aggregates_all_checks():
    broken = _member(
        skills=[Skill(skill="Python", level=99)],
        availability=Availability(available_hours_per_week=10, current_assigned_hours=20),
        constraints=[Constraint(type="day_unavailable", value="Blursday")],
    )
    issues = validate_members([broken])
    codes = {i.code for i in issues}
    assert "INVALID_SKILL_LEVEL" in codes
    assert "WORKLOAD_ABOVE_CAPACITY" in codes
    assert "INVALID_CONSTRAINT" in codes


def test_validate_members_clean_member_has_no_issues():
    assert validate_members([_member()]) == []
