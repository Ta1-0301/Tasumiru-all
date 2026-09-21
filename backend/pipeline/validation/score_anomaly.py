# backend/pipeline/validation/score_anomaly.py
"""
CHECK 8: Assignment Score Anomaly。

完全に決定的（LLM不使用）。決定的スコアリング(Phase 7/Part 9)の結果、
実際に割り当てられたメンバーのスコアが著しく低い場合を検出する。

**`FinalAssignment.ai_recommendation.score`をそのまま使わない。**
それはAIの推薦(`recommended_member_id`)のスコアであり、人間が
Override(`assigned_member_id` != `recommended_member_id`)した場合は
別人のスコアになってしまう。実際に割り当てられたメンバーのスコアは、
`ai_recommendation.candidate_scores`（ハード制約を通過した全候補者の
スコア一覧）から`assigned_member_id`を引いて求める。

そこに存在しない（＝一度もスコアリング対象にならなかった）メンバーへの
割り当てについては、スコアの捏造を避けるためこのチェックでは何も報告
しない——それがハード制約違反であれば、既存のCHECK 6
(`backend.pipeline.validation.constraints`)が別途検出する。
"""

from __future__ import annotations

from typing import List, Optional

from backend.pipeline.assignment.schema import FinalAssignment
from backend.pipeline.validation.schema import AssignmentScoreAnomaly

DEFAULT_LOW_SCORE_THRESHOLD = 40.0


def _score_for_assigned_member(final_assignment: FinalAssignment) -> Optional[float]:
    for candidate in final_assignment.ai_recommendation.candidate_scores:
        if candidate.member_id == final_assignment.assigned_member_id:
            return candidate.score
    return None


def check_assignment_score_anomalies(
    final_assignments: List[FinalAssignment],
    threshold: float = DEFAULT_LOW_SCORE_THRESHOLD,
) -> List[AssignmentScoreAnomaly]:
    anomalies: List[AssignmentScoreAnomaly] = []
    for fa in final_assignments:
        if fa.assigned_member_id is None:
            continue

        score = _score_for_assigned_member(fa)
        if score is None or score >= threshold:
            continue

        anomalies.append(AssignmentScoreAnomaly(
            task_id=fa.task_id,
            member_id=fa.assigned_member_id,
            score=score,
            threshold=threshold,
            message=(
                f"タスク'{fa.task_id}'への割り当て({fa.assigned_member_id})のスコアが"
                f"{score}点と低く（閾値{threshold}点未満）、十分に適合する担当者が"
                "いなかった可能性があります"
            ),
        ))
    return anomalies
