# backend/pipeline/final_output/traceability.py
"""
依頼のTRACEABILITY節「Every task must be traceable to one or more
requirements」を検証する。

Phase 8(`backend.pipeline.validation.missing_requirements`)のCHECK 1は
「要求 -> タスク」の向き（対応するタスクが無い要求）だけを見ており、
逆向き（タスク -> 要求）は検証していない。このフェーズはRequirement->Task->
Dependency->Assignmentの連鎖全体を最終出力として保証する責務を持つため、
この逆方向のチェックを独自に追加する。完全に決定的（LLM不使用）。
"""

from __future__ import annotations

from typing import List

from backend.pipeline.final_output.schema import TraceabilityIssue
from backend.pipeline.tasks.schema import Task


def find_untraceable_tasks(tasks: List[Task]) -> List[TraceabilityIssue]:
    """requirement_idsが空の（どの要求にも遡れない）タスクを検出する"""
    return [
        TraceabilityIssue(
            code="TASK_WITHOUT_REQUIREMENT",
            message=f"タスク'{t.id}'がどの要求にも紐づいていません（requirement_idsが空）",
            task_id=t.id,
        )
        for t in tasks
        if not t.requirement_ids
    ]
