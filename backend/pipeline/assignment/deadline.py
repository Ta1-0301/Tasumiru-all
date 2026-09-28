# backend/pipeline/assignment/deadline.py
"""
納期（due_date）を考慮した稼働可能時間の計算と、期限内完了可能性のチェック。

完全に決定的（LLM不使用）。`AssignmentLedger`（割当済み工数の台帳）は
JobManagerがAssignmentを逐次実行する際に使う。台帳が渡されない限り
`filters.py`は従来と完全に同じ判定を行う。

稼働可能時間の定義は、既存の`Availability`の意味（週あたり稼働可能時間 +
稼働曜日）をそのまま期間に引き延ばしたものであり、新しい稼働時間の概念は
作らない:

    期間内の稼働可能時間
      = 週あたり稼働可能時間 / 週の稼働日数 × 期間内の稼働日数

  - 期間は開始日・期限日の両端を含む（期限日当日も作業できる）。
  - `working_days`が空、または曜日名として解釈できない場合は、暦日ベース
    （週あたり稼働可能時間 × 暦日数 / 7）にフォールバックする。
  - `max_hours_per_week`制約がある場合、週あたりの時間はその上限で頭打ちにする
    （既存のハード制約の意味を期間にも適用するだけで、緩めることはない）。

期限内完了可能性は、EDF（期限の早い順）の考え方で「各期限dまでに完了が必要な
工数の累積 <= 期限dまでの稼働可能時間」がすべての期限について成り立つかで
判定する。タスクを1件追加すると、そのタスクの期限以降のすべての期限の
累積負荷が増えるため、その全期限を確認する。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Dict, List, Optional, Set, Tuple

from backend.pipeline.members.schema import Member

# "Monday"/"Mon"/"mon" などを同じ曜日として扱う（members.jsonには両方の表記が存在する）
_WEEKDAY_INDEX = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}


def working_weekdays(member: Member) -> Set[int]:
    """メンバーの稼働曜日（0=月曜 … 6=日曜）。解釈できない曜日名は無視する。"""
    days: Set[int] = set()
    for name in member.availability.working_days:
        idx = _WEEKDAY_INDEX.get(name.strip().lower()[:3])
        if idx is not None:
            days.add(idx)
    return days


def weekly_hours_cap(member: Member) -> float:
    """週あたりの稼働可能時間。`max_hours_per_week`制約があればその上限で頭打ちにする。"""
    hours = member.availability.available_hours_per_week
    for c in member.constraints:
        if c.type == "max_hours_per_week" and c.max_hours is not None:
            hours = min(hours, c.max_hours)
    return hours


def period_hours(member: Member, start: date, end: date, weekly_hours: float) -> float:
    """`start`〜`end`（両端を含む）の期間に、週あたり`weekly_hours`で稼働した場合の時間。"""
    if end < start or weekly_hours <= 0:
        return 0.0
    total_days = (end - start).days + 1
    weekdays = working_weekdays(member)
    if not weekdays:
        return weekly_hours * total_days / 7

    per_day = weekly_hours / len(weekdays)
    full_weeks, rest = divmod(total_days, 7)
    days = full_weeks * len(weekdays)
    for offset in range(rest):
        if (start + timedelta(days=full_weeks * 7 + offset)).weekday() in weekdays:
            days += 1
    return per_day * days


def free_hours_until(member: Member, start: date, end: date) -> float:
    """期限までにこのプロジェクトへ使える時間（既存業務`current_assigned_hours`を
    週あたりの稼働時間から差し引いた、`remaining_capacity`と同じ考え方）。"""
    weekly_free = max(0.0, weekly_hours_cap(member) - member.availability.current_assigned_hours)
    return period_hours(member, start, end, weekly_free)


@dataclass
class AssignmentLedger:
    """Assignmentを逐次実行する際の、割当済み工数の台帳と負荷の基準。

    - `period_end`が無い（納期情報が無い）場合: 負荷の基準は従来と同じ1週間
      （`available_hours_per_week`）。
    - `period_end`がある場合: 基準日(`reference_date`)〜`period_end`の計画期間。

    負荷率はValidation(CHECK 4)・フロントエンドと同じ定義
    （(既存業務 + 割当済み + このタスク) / 稼働可能時間）で計算する。
    """

    reference_date: Optional[date] = None
    period_end: Optional[date] = None
    committed: Dict[str, List[Tuple[float, Optional[date]]]] = field(default_factory=dict)

    @property
    def is_period(self) -> bool:
        return self.reference_date is not None and self.period_end is not None

    def commit(self, member_id: str, hours: Optional[float], due_date: Optional[date]) -> None:
        if not hours:
            return
        self.committed.setdefault(member_id, []).append((hours, due_date))

    def committed_hours(self, member_id: str) -> float:
        return sum(h for h, _ in self.committed.get(member_id, []))

    def free_capacity(self, member: Member) -> float:
        """このプロジェクトに使える時間の上限（既存業務を差し引き、max_hours_per_weekで頭打ち）"""
        if self.is_period:
            return free_hours_until(member, self.reference_date, self.period_end)
        return max(0.0, weekly_hours_cap(member) - member.availability.current_assigned_hours)

    def projected_percentage(self, member: Member, hours: Optional[float]) -> float:
        """このタスク(hours)を追加した後の負荷率(%)"""
        weekly = member.availability.available_hours_per_week
        existing = member.availability.current_assigned_hours
        if self.is_period:
            basis = period_hours(member, self.reference_date, self.period_end, weekly)
            existing = period_hours(member, self.reference_date, self.period_end, existing)
        else:
            basis = weekly
        total = existing + self.committed_hours(member.id) + (hours or 0.0)
        if basis > 0:
            return round(total / basis * 100, 2)
        return 100.0 if total > 0 else 0.0


def evaluate_deadline(
    member: Member, hours: float, due_date: date, ledger: AssignmentLedger
) -> Optional[Tuple[date, float, float]]:
    """このタスクを追加した場合に、期限を守れなくなる最初の期限を返す。

    戻り値は (破綻する期限, その期限までに必要な工数, その期限までの稼働可能時間)。
    全期限を満たせるならNone。
    """
    committed = [(h, d) for h, d in ledger.committed.get(member.id, []) if d is not None]
    checkpoints = sorted({due_date} | {d for _, d in committed if d > due_date})
    for d in checkpoints:
        required = hours + sum(h for h, cd in committed if cd <= d)
        available = free_hours_until(member, ledger.reference_date, d)
        if required > available + 1e-9:
            return d, round(required, 2), round(available, 2)
    return None


def check_deadline(task, member: Member, ledger: Optional[AssignmentLedger]) -> List[str]:
    """期限までにこのタスク（と割当済みの期限付きタスク）を完了できるかを確認する。

    期限・見積り工数・基準日のいずれかが無い、または台帳が無い場合は判定しない
    （`check_workload`が見積り工数の無いタスクを判定しないのと同じ扱い）。
    """
    if (
        ledger is None or ledger.reference_date is None
        or task.due_date is None or task.estimated_hours is None
    ):
        return []
    violation = evaluate_deadline(member, task.estimated_hours, task.due_date, ledger)
    if violation is None:
        return []
    d, required, available = violation
    return [
        f"期限({d.isoformat()})までの稼働可能時間({available}h)が、"
        f"期限までに完了が必要な工数({required}h = 割当済み"
        f"{round(required - task.estimated_hours, 2)}h + このタスク{task.estimated_hours}h)に"
        "足りません（deadline infeasible）"
    ]


def check_cumulative_workload(task, member: Member, ledger: Optional[AssignmentLedger]) -> List[str]:
    """割当済みの工数にこのタスクを加えると、負荷率が100%を超えないかを確認する。

    `filters.check_workload`（このタスク単体が残りキャパシティに収まるか）の
    累積版。見積り工数の無いタスク、または台帳が無い場合は判定しない。
    """
    if ledger is None or task.estimated_hours is None:
        return []
    committed = ledger.committed_hours(member.id)
    capacity = ledger.free_capacity(member)
    if committed + task.estimated_hours <= capacity + 1e-9:
        return []
    return [
        f"このタスクを加えると負荷率が{ledger.projected_percentage(member, task.estimated_hours)}%になり"
        f"100%を超えます（割当済み{round(committed, 2)}h + このタスク{task.estimated_hours}h > "
        f"稼働可能{round(capacity, 2)}h）（workload exceeds maximum）"
    ]
