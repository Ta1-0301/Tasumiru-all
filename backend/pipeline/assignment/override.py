# backend/pipeline/assignment/override.py
"""
Human Override。

AIの推薦(`AssignmentResult`)と、最終的な人間の割り当て決定(`FinalAssignment`)
を常に分離して保持する。マネージャーは推薦をそのまま採用することも、
別のメンバーに（あるいは誰にも割り当てない、という決定に）上書きすることも
できる。

AIは自分の判断でハード制約を回避できないが、**人間による上書きには
そのような制限を課さない** —
最終的な決定権は常に人間にある、という要件をそのまま反映している。
"""

from __future__ import annotations

from typing import Optional

from backend.pipeline.assignment.schema import AssignmentResult, FinalAssignment


def accept_recommendation(recommendation: AssignmentResult) -> FinalAssignment:
    """AIの推薦をそのまま最終決定として採用する（人間が確認して承認した想定）。

    `recommendation.status == "no_suitable_member"`の場合は
    `assigned_member_id=None`のまま、「まだ誰にも割り当てない」という
    決定になる（強制的な割り当てはしない）。
    """
    return FinalAssignment(
        task_id=recommendation.task_id,
        assigned_member_id=recommendation.recommended_member_id,
        decided_by="ai",
        overridden=False,
        ai_recommendation=recommendation,
    )


def override_recommendation(
    recommendation: AssignmentResult,
    member_id: Optional[str],
    reason: str,
) -> FinalAssignment:
    """マネージャーがAIの推薦を上書きする。

    `member_id=None`は「（AIの推薦の有無にかかわらず）誰にも割り当てない」
    という明示的な人間の決定を表す。AIの推薦(`ai_recommendation`)は
    変更されずそのまま保持される。
    """
    overridden = member_id != recommendation.recommended_member_id
    return FinalAssignment(
        task_id=recommendation.task_id,
        assigned_member_id=member_id,
        decided_by="human",
        overridden=overridden,
        override_reason=reason,
        ai_recommendation=recommendation,
    )
