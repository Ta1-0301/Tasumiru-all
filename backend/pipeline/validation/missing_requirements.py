# backend/pipeline/validation/missing_requirements.py
"""
CHECK 1: Missing Requirements。

完全に決定的（LLM不使用）。各要求(Requirement)が、少なくとも1つの
タスク(Task.requirement_ids)から参照されているかを確認する。
"""

from __future__ import annotations

from typing import List

from backend.pipeline.requirements.schema import Requirement
from backend.pipeline.tasks.schema import Task
from backend.pipeline.validation.schema import MissingRequirement


def find_missing_requirements(
    requirements: List[Requirement], tasks: List[Task]
) -> List[MissingRequirement]:
    """対応するタスクが1つも無い要求を見つける"""
    covered = set()
    for t in tasks:
        covered.update(t.requirement_ids)

    return [
        MissingRequirement(
            requirement_id=r.id,
            message=f"要求'{r.title}'({r.id})に対応するタスクがありません",
        )
        for r in requirements
        if r.id not in covered
    ]
