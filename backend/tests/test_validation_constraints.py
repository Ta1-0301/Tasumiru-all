# backend/tests/test_validation_constraints.py
"""backend/pipeline/validation/constraints.py の単体テスト（CHECK 6）。

Phase 7のfilters.pyを再利用しているため、ここでは「確定した割り当て」に対して
その再確認が機能することと、Phase 7には無い「存在しないメンバーへの割り当て」
検出を確認する。
"""

from backend.pipeline.assignment.schema import RequiredSkill
from backend.pipeline.members.schema import Availability, Constraint, Member, Skill
from backend.pipeline.tasks.schema import Task
from backend.pipeline.validation.constraints import check_assignment_constraints


def _member(id="M-001", skills=None, available=40, current=0, constraints=None) -> Member:
    return Member(
        id=id, name=id, skills=skills or [],
        availability=Availability(available_hours_per_week=available, current_assigned_hours=current),
        constraints=constraints or [],
    )


def _task(id="TASK-001", required_skills=None, estimated_hours=8) -> Task:
    return Task(
        id=id, title="タスク", description="説明",
        required_skills=required_skills or [], estimated_hours=estimated_hours, confidence=0.9,
    )


def test_assignment_respecting_all_constraints_produces_no_violation():
    task = _task(required_skills=["Python"])
    member = _member(skills=[Skill(skill="Python", level=5)])
    violations = check_assignment_constraints([task], [member], {"TASK-001": "M-001"})
    assert violations == []


def test_assignment_with_insufficient_skill_is_flagged():
    """Human Overrideがハード制約(必要スキル)を無視して割り当てたケースを再検出する"""
    task = _task(required_skills=["Python"])
    member = _member(skills=[])  # 必要スキルを持たないメンバーに強引に割り当てられた想定
    violations = check_assignment_constraints([task], [member], {"TASK-001": "M-001"})
    assert any(v.code == "HARD_CONSTRAINT_VIOLATED" for v in violations)


def test_assignment_exceeding_workload_is_flagged():
    task = _task(estimated_hours=20)
    member = _member(available=40, current=35)  # 残り5hしかないのに20hを割り当てられた想定
    violations = check_assignment_constraints([task], [member], {"TASK-001": "M-001"})
    assert any(v.code == "HARD_CONSTRAINT_VIOLATED" for v in violations)


def test_assignment_violating_explicit_constraint_is_flagged():
    task = _task(estimated_hours=10)
    member = _member(constraints=[Constraint(type="max_hours_per_week", max_hours=5)])
    violations = check_assignment_constraints([task], [member], {"TASK-001": "M-001"})
    assert any(v.code == "HARD_CONSTRAINT_VIOLATED" for v in violations)


def test_assignment_to_nonexistent_member_is_flagged():
    task = _task()
    violations = check_assignment_constraints([task], [], {"TASK-001": "M-ghost"})
    assert len(violations) == 1
    assert violations[0].code == "UNKNOWN_MEMBER"


def test_unassigned_task_is_not_checked():
    task = _task()
    member = _member(skills=[])
    assert check_assignment_constraints([task], [member], {}) == []


def test_custom_required_skill_levels_are_honored():
    task = _task(required_skills=["Python"])
    member = _member(skills=[Skill(skill="Python", level=2)])
    required_skill_levels = {"TASK-001": [RequiredSkill(skill="Python", min_level=5)]}

    violations = check_assignment_constraints(
        [task], [member], {"TASK-001": "M-001"}, required_skill_levels=required_skill_levels
    )
    assert any(v.code == "HARD_CONSTRAINT_VIOLATED" for v in violations)
