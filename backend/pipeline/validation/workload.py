# backend/pipeline/validation/workload.py
"""
CHECK 4: Workload。

完全に決定的（LLM不使用）。メンバーごとに、実際の割り当て(assignments)から
再計算した合計時間を基準に稼働状況を算出する
（Phase 6の`Member.availability.current_assigned_hours`は割り当て前の
スナップショットである可能性があるため、このフェーズでは`assignments`と
`tasks`から新たに集計し直す）。
"""

from __future__ import annotations

from typing import Dict, List, Tuple

from backend.pipeline.members.schema import Member
from backend.pipeline.tasks.schema import Task
from backend.pipeline.validation.schema import WorkloadSummary, WorkloadWarning

OVERLOAD_THRESHOLD_PERCENTAGE = 100.0


def compute_workload_summary(
    member: Member, tasks: List[Task], assignments: Dict[str, str]
) -> WorkloadSummary:
    assigned_hours = sum(
        (t.estimated_hours or 0.0) for t in tasks if assignments.get(t.id) == member.id
    )
    available_hours = member.availability.available_hours_per_week
    remaining_capacity = available_hours - assigned_hours

    if available_hours > 0:
        workload_percentage = round((assigned_hours / available_hours) * 100, 2)
    else:
        workload_percentage = 100.0 if assigned_hours > 0 else 0.0

    return WorkloadSummary(
        member_id=member.id,
        assigned_hours=round(assigned_hours, 2),
        available_hours=available_hours,
        remaining_capacity=round(remaining_capacity, 2),
        workload_percentage=workload_percentage,
    )


def check_workload(
    members: List[Member],
    tasks: List[Task],
    assignments: Dict[str, str],
    overload_threshold: float = OVERLOAD_THRESHOLD_PERCENTAGE,
) -> Tuple[List[WorkloadSummary], List[WorkloadWarning]]:
    """全メンバーの稼働状況を計算し、過負荷を検出する。

    戻り値は (全メンバーのサマリー, 過負荷の警告のみ)。サマリーは問題の有無に
    関わらず全員分を含む（フロントエンドが常に稼働状況を表示できるように）。
    """
    summaries: List[WorkloadSummary] = []
    warnings: List[WorkloadWarning] = []

    for m in members:
        summary = compute_workload_summary(m, tasks, assignments)
        summaries.append(summary)

        if summary.workload_percentage > overload_threshold:
            warnings.append(WorkloadWarning(
                member_id=summary.member_id,
                assigned_hours=summary.assigned_hours,
                available_hours=summary.available_hours,
                remaining_capacity=summary.remaining_capacity,
                workload_percentage=summary.workload_percentage,
                code="OVERLOAD",
                message=(
                    f"{m.name}の稼働率が{summary.workload_percentage}%で、"
                    f"上限({overload_threshold}%)を超えています"
                ),
            ))

    return summaries, warnings
