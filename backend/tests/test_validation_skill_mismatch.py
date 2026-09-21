# backend/tests/test_validation_skill_mismatch.py
"""backend/pipeline/validation/skill_mismatch.py の単体テスト（CHECK 5）。"""

from backend.pipeline.assignment.schema import RequiredSkill
from backend.pipeline.members.schema import Member, Skill
from backend.pipeline.members.schema import Availability
from backend.pipeline.tasks.schema import Task
from backend.pipeline.validation.skill_mismatch import check_skill_mismatches, default_required_skills


def _member(id="M-001", skills=None) -> Member:
    return Member(
        id=id, name=id, skills=skills or [],
        availability=Availability(available_hours_per_week=40),
    )


def _task(id, required_skills) -> Task:
    return Task(
        id=id, title="タスク", description="説明",
        required_skills=required_skills, confidence=0.9,
    )


def test_member_with_matching_skill_produces_no_mismatch():
    task = _task("TASK-001", ["Python"])
    member = _member(skills=[Skill(skill="Python", level=3)])
    assert check_skill_mismatches([task], [member], {"TASK-001": "M-001"}) == []


def test_member_missing_skill_entirely_is_flagged():
    task = _task("TASK-001", ["Python"])
    member = _member(skills=[Skill(skill="Go", level=5)])
    mismatches = check_skill_mismatches([task], [member], {"TASK-001": "M-001"})
    assert len(mismatches) == 1
    assert mismatches[0].member_level == 0
    assert mismatches[0].skill == "Python"


def test_unassigned_task_is_not_checked():
    task = _task("TASK-001", ["Python"])
    member = _member(skills=[])
    assert check_skill_mismatches([task], [member], {}) == []


def test_unknown_skill_sentinel_is_not_treated_as_a_real_requirement():
    task = _task("TASK-001", ["unknown"])
    member = _member(skills=[])
    assert check_skill_mismatches([task], [member], {"TASK-001": "M-001"}) == []


def test_default_required_skills_assumes_minimum_level_one():
    task = _task("TASK-001", ["Python"])
    required = default_required_skills(task)
    assert required == [RequiredSkill(skill="Python", min_level=1)]


def test_custom_required_skill_levels_are_used_when_provided():
    task = _task("TASK-001", ["Python"])  # required_skillsに無い、より厳しいレベル要求を渡す
    member = _member(skills=[Skill(skill="Python", level=2)])
    required_skill_levels = {"TASK-001": [RequiredSkill(skill="Python", min_level=4)]}

    mismatches = check_skill_mismatches(
        [task], [member], {"TASK-001": "M-001"}, required_skill_levels=required_skill_levels
    )
    assert len(mismatches) == 1
    assert mismatches[0].required_level == 4
    assert mismatches[0].member_level == 2


def test_reference_to_unknown_member_is_skipped_not_crashed():
    task = _task("TASK-001", ["Python"])
    assert check_skill_mismatches([task], [], {"TASK-001": "M-nonexistent"}) == []
