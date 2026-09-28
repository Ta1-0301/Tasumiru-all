# backend/pipeline/validation/unassigned.py
"""
CHECK 9: Unassigned Task Detection。

完全に決定的（LLM不使用）。これまで未割当タスクは`assignments_from_final()`/
`_run_validation`のマッピング構築時点で除外され、CHECK 1-8のどこからも
一切見えなかった（`member_id is None`のタスクは各CHECKが`continue`する）。
このモジュールは`final_assignments`（CHECK 8向けに既に引数として存在する）
を直接走査し、未割当タスクだけを対象にする——他のCHECKの判定結果には
一切影響しない。

理由の分類は`backend.pipeline.assignment.audit`で既に計算済みの
`AssignmentResult.unassigned_reason`をそのまま使う（ここで判定ロジックを
再実装しない）。
"""

from __future__ import annotations

from typing import List

from backend.pipeline.assignment.schema import FinalAssignment
from backend.pipeline.validation.schema import UnassignedTaskIssue

_REASON_MESSAGES = {
    "NO_CANDIDATE": "メンバーが1人も登録されていません",
    "HARD_CONSTRAINT": "明示的な制約（scope_restriction/max_hours_per_week等）を満たす候補者がいませんでした",
    "NO_REQUIRED_SKILL": "必要スキルを持つ候補者がいませんでした",
    "NO_AVAILABILITY": "稼働可能な候補者がいませんでした",
    "WORKLOAD_TOO_HIGH": "見積り工数が全候補者の残りキャパシティを超えていました",
    "DEADLINE_INFEASIBLE": "期限までに完了できる稼働時間を持つ候補者がいませんでした",
    "INVALID_MEMBER_DATA": "メンバーデータの読み込みエラーにより候補者が存在しませんでした",
    "UNKNOWN": "未割当の理由を特定できませんでした",
}


def check_unassigned_tasks(final_assignments: List[FinalAssignment]) -> List[UnassignedTaskIssue]:
    """`final_assignments`のうち、担当者が割り当てられなかったタスクを報告する。"""
    issues: List[UnassignedTaskIssue] = []
    for fa in final_assignments:
        if fa.assigned_member_id is not None:
            continue
        reason = fa.ai_recommendation.unassigned_reason or "UNKNOWN"
        message = _REASON_MESSAGES.get(reason, _REASON_MESSAGES["UNKNOWN"])
        issues.append(UnassignedTaskIssue(task_id=fa.task_id, reason=reason, message=message))
    return issues
