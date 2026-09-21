# backend/pipeline/validation/constraints.py
"""
CHECK 6: Assignment Constraints。

完全に決定的（LLM不使用）。Phase 7(`backend.pipeline.assignment.filters`)の
ハード制約チェックをそのまま再利用し、重複実装しない。

これが特に重要な理由: Phase 7のHuman Override(`override.py`)は、
マネージャーがAIの推薦を無視して別のメンバーを割り当てることを明示的に
許可している。その上書きがハード制約（必要スキル・稼働可否・工数上限・
明示的な制約）に違反していないかは、Phase 7自身では再確認されない
（人間の最終決定を制限しないという設計）。CHECK 6は、確定した割り当て
一覧に対してその確認をやり直す、最後の安全網である
（違反があっても割り当てを取り消したりはせず、警告として報告するだけ）。
"""

from __future__ import annotations

from typing import Dict, List, Optional

from backend.pipeline.assignment.filters import (
    check_availability,
    check_explicit_constraints,
    check_skill_requirements,
)
from backend.pipeline.assignment.filters import check_workload as check_hard_workload
from backend.pipeline.assignment.schema import AssignmentTask, RequiredSkill
from backend.pipeline.members.schema import Member
from backend.pipeline.tasks.schema import Task
from backend.pipeline.validation.schema import ConstraintViolation
from backend.pipeline.validation.skill_mismatch import default_required_skills


def _to_assignment_task(task: Task, required_skills: List[RequiredSkill]) -> AssignmentTask:
    return AssignmentTask(
        task_id=task.id,
        title=task.title,
        required_skills=required_skills,
        estimated_hours=task.estimated_hours,
        priority=task.priority,
    )


def check_assignment_constraints(
    tasks: List[Task],
    members: List[Member],
    assignments: Dict[str, str],
    required_skill_levels: Optional[Dict[str, List[RequiredSkill]]] = None,
) -> List[ConstraintViolation]:
    member_by_id = {m.id: m for m in members}
    violations: List[ConstraintViolation] = []

    for t in tasks:
        member_id = assignments.get(t.id)
        if member_id is None:
            continue

        member = member_by_id.get(member_id)
        if member is None:
            violations.append(ConstraintViolation(
                task_id=t.id, member_id=member_id, code="UNKNOWN_MEMBER",
                message=f"タスク'{t.id}'が存在しないメンバー'{member_id}'に割り当てられています",
            ))
            continue

        required = (required_skill_levels or {}).get(t.id)
        if required is None:
            required = default_required_skills(t)
        assignment_task = _to_assignment_task(t, required)

        reasons = (
            check_skill_requirements(assignment_task, member)
            + check_availability(assignment_task, member)
            + check_hard_workload(assignment_task, member)
            + check_explicit_constraints(assignment_task, member)
        )
        for reason in reasons:
            violations.append(ConstraintViolation(
                task_id=t.id, member_id=member_id, code="HARD_CONSTRAINT_VIOLATED", message=reason,
            ))

    return violations
