# backend/jobs/adapters.py
"""
Phase 4の`Task`とPhase 5の`Dependency`から、Phase 7の`AssignmentTask`を
組み立てる。**新しいビジネスルールは何も無い** — 既存の2つのフェーズの
データ形状を橋渡しするだけの、純粋なデータ変換。

必要スキルの最低レベルの導出は、Phase 8で既に実装済みの
`backend.pipeline.validation.skill_mismatch.default_required_skills`を
そのまま再利用する（Task.required_skillsはレベルを持たない文字列一覧のため、
「レベル1(Beginner)以上を持っていればよい」という既存の緩い既定値に
フォールバックする、という判断をこのフェーズで新しく作らない）。
"""

from __future__ import annotations

from typing import List

from backend.pipeline.assignment.schema import AssignmentTask
from backend.pipeline.dependencies.schema import Dependency
from backend.pipeline.tasks.schema import Task
from backend.pipeline.validation.skill_mismatch import default_required_skills


def task_to_assignment_task(task: Task, dependencies: List[Dependency]) -> AssignmentTask:
    """1件のTaskを、Phase 7が必要とするAssignmentTaskに変換する。

    `dependencies`は、このタスクが後続(to_task_id)となっている辺の
    from_task_id一覧（＝前提タスクID一覧）として引き継ぐ。
    """
    prerequisite_ids = [d.from_task_id for d in dependencies if d.to_task_id == task.id]

    return AssignmentTask(
        task_id=task.id,
        title=task.title,
        required_skills=default_required_skills(task),
        estimated_hours=task.estimated_hours,
        priority=task.priority,
        dependencies=prerequisite_ids,
    )
