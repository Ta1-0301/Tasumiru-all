# backend/pipeline/validation/workload.py
"""
CHECK 4: Workload。

完全に決定的（LLM不使用）。メンバーごとに、実際の割り当て(assignments)から
再計算した合計時間を基準に稼働状況を算出する
（Phase 6の`Member.availability.current_assigned_hours`は割り当て前の
スナップショットである可能性があるため、このフェーズでは`assignments`と
`tasks`から新たに集計し直す）。

納期考慮（`reference_date`が渡され、期限付きのタスクが1件以上ある場合のみ）:
  分子は従来と同じ（割り当てられたタスクの見積り合計）。分母だけを
  「1週間」から「計画期間（基準日〜最も遅い期限）の稼働可能時間」に変える
  （`backend.pipeline.assignment.deadline.period_hours`）。さらに、計画期間の
  終わりより前の各期限について、その期限までに完了が必要な工数の累積が
  その期限までの稼働可能時間を超えていないかを確認する（DEADLINE_OVERLOAD）。
  期限付きのタスクが無ければ、従来と完全に同じ計算になる。
"""

from __future__ import annotations

from datetime import date
from typing import Dict, List, Optional, Tuple

from backend.pipeline.assignment.deadline import period_hours
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


def effective_due_date(task: Task, default_due_date: Optional[date]) -> Optional[date]:
    """タスク個別の期限を優先し、無ければプロジェクトの納期を使う（jobs/adapters.pyと同じ規則）"""
    return task.due_date or default_due_date


def _percentage(hours: float, available: float) -> float:
    if available > 0:
        return round((hours / available) * 100, 2)
    return 100.0 if hours > 0 else 0.0


def compute_period_workload_summary(
    member: Member,
    tasks: List[Task],
    assignments: Dict[str, str],
    period_start: date,
    period_end: date,
) -> WorkloadSummary:
    """`compute_workload_summary`の分母を、計画期間内の稼働可能時間に置き換えたもの。"""
    assigned_hours = sum(
        (t.estimated_hours or 0.0) for t in tasks if assignments.get(t.id) == member.id
    )
    weekly = member.availability.available_hours_per_week
    available_hours = round(period_hours(member, period_start, period_end, weekly), 2)

    return WorkloadSummary(
        member_id=member.id,
        assigned_hours=round(assigned_hours, 2),
        available_hours=available_hours,
        remaining_capacity=round(available_hours - assigned_hours, 2),
        workload_percentage=_percentage(assigned_hours, available_hours),
        basis="period",
        weekly_available_hours=weekly,
        period_start=period_start,
        period_end=period_end,
    )


def find_deadline_overload(
    member: Member,
    tasks: List[Task],
    assignments: Dict[str, str],
    period_start: date,
    period_end: date,
    default_due_date: Optional[date],
) -> Optional[Tuple[date, float, float]]:
    """計画期間の終わりより前の期限のうち、累積工数が稼働可能時間を最も大きく
    超える期限を返す (期限, 累積工数, 稼働可能時間)。超えていなければNone。

    計画期間の終わり(period_end)自体は、サマリーのOVERLOAD判定と同じ内容に
    なるため対象にしない（同じ事実を2重に警告しない）。
    """
    dated = [
        (t.estimated_hours or 0.0, effective_due_date(t, default_due_date))
        for t in tasks if assignments.get(t.id) == member.id
    ]
    dated = [(h, d) for h, d in dated if d is not None]
    weekly = member.availability.available_hours_per_week

    worst: Optional[Tuple[date, float, float]] = None
    worst_ratio = 1.0
    for d in sorted({d for _, d in dated if d < period_end}):
        required = sum(h for h, due in dated if due <= d)
        available = period_hours(member, period_start, d, weekly)
        if required <= available + 1e-9:
            continue
        ratio = required / available if available > 0 else float("inf")
        if ratio > worst_ratio:
            worst_ratio = ratio
            worst = (d, round(required, 2), round(available, 2))
    return worst


def check_workload(
    members: List[Member],
    tasks: List[Task],
    assignments: Dict[str, str],
    overload_threshold: float = OVERLOAD_THRESHOLD_PERCENTAGE,
    *,
    reference_date: Optional[date] = None,
    default_due_date: Optional[date] = None,
) -> Tuple[List[WorkloadSummary], List[WorkloadWarning]]:
    """全メンバーの稼働状況を計算し、過負荷を検出する。

    戻り値は (全メンバーのサマリー, 過負荷の警告のみ)。サマリーは問題の有無に
    関わらず全員分を含む（フロントエンドが常に稼働状況を表示できるように）。

    `reference_date`（計画の基準日）が渡され、期限付きのタスク（個別の
    `due_date`、または`default_due_date`＝プロジェクト納期）が1件以上ある
    場合のみ、計画期間ベースで計算する。それ以外は従来と同じ週ベース。
    """
    summaries: List[WorkloadSummary] = []
    warnings: List[WorkloadWarning] = []

    period_end: Optional[date] = None
    if reference_date is not None:
        dues = [d for d in (effective_due_date(t, default_due_date) for t in tasks) if d is not None]
        if dues:
            period_end = max(dues)

    for m in members:
        if period_end is None:
            summary = compute_workload_summary(m, tasks, assignments)
        else:
            summary = compute_period_workload_summary(m, tasks, assignments, reference_date, period_end)
        summaries.append(summary)

        if period_end is not None:
            overload = find_deadline_overload(
                m, tasks, assignments, reference_date, period_end, default_due_date,
            )
            if overload is not None:
                d, required, available = overload
                pct = _percentage(required, available)
                warnings.append(WorkloadWarning(
                    member_id=m.id,
                    assigned_hours=required,
                    available_hours=available,
                    remaining_capacity=round(available - required, 2),
                    workload_percentage=pct,
                    code="DEADLINE_OVERLOAD",
                    message=(
                        f"{m.name}は期限{d.isoformat()}までに{required}hの作業がありますが、"
                        f"その期限までの稼働可能時間は{available}hです（{pct}%）"
                    ),
                ))

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
