# backend/pipeline/assignment/workload_balancing.py
"""
Part 8/9/11: Workload Calculation + Load Balancing。

完全に決定的（LLM不使用）。Step 2(`scoring.py`)は各候補者を独立にスコア
リングするだけで、「誰を実際に推薦するか」を決めるロジックはこのモジュール
に分離している。

依頼のPart 11の具体例に対応する:

    Member A: skill similarity = 0.95, load = 95%
    Member B: skill similarity = 0.82, load = 40%
    -> Aに自動的に割り当てない。Bがスキル要件の閾値を満たすなら
       バランスの取れた割り当てを優先する。

**スコアそのもの（`candidate_scores`）は一切書き換えない・並べ替えない。**
フロントエンドには常に「決定的スコアリングによる純粋なランキング」を
そのまま見せる（Part 15: traceability）。このモジュールが決めるのは
「その中のどれを`recommended_member_id`として選ぶか」だけであり、
選択の理由は`warnings`に人間が読める形で残す
——依頼全体を貫く「黙って修復しない・理由を記録する」方針に沿う。
"""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from backend.pipeline.assignment.schema import AssignmentTask, CandidateScore
from backend.pipeline.members.schema import Member

# Part 11: 「まだ許容範囲」と「明らかに過負荷」を分ける2段階の閾値。
# 環境ごとに変えたい場合はこのモジュールの定数を差し替える（決定的であることが
# 重要なため、環境変数化はせずコード上の設定値とする）。
WORKLOAD_WARNING_PERCENTAGE = 80.0
MAX_WORKLOAD_PERCENTAGE = 100.0


def compute_projected_workload_percentage(task: AssignmentTask, member: Member) -> float:
    """このタスクを割り当てた"後"の、メンバーの稼働率(%)を計算する。

    `backend.pipeline.validation.workload.compute_workload_summary`と同じ
    「available_hours_per_week <= 0」の扱い（0除算を避け、稼働時間があれば
    100%、無ければ0%とする）を踏襲し、指標の意味を全フェーズで揃える。
    """
    available = member.availability.available_hours_per_week
    projected_hours = member.availability.current_assigned_hours + (task.estimated_hours or 0.0)

    if available > 0:
        return round((projected_hours / available) * 100, 2)
    return 100.0 if projected_hours > 0 else 0.0


def select_recommended_candidate(
    task: AssignmentTask,
    candidate_scores: List[CandidateScore],
    members_by_id: Dict[str, Member],
    warning_threshold: float = WORKLOAD_WARNING_PERCENTAGE,
) -> Tuple[Optional[CandidateScore], List[str]]:
    """スコア降順の候補者一覧から、稼働バランスを考慮して推薦者を1人選ぶ。

    戻り値は (選ばれた候補 または 候補が無ければNone, 追加のwarnings一覧)。

    ロジック:
      1. スコア最上位の候補の、割当後の稼働率が閾値以下なら、そのまま推薦する
         （追加の警告は無い — これが最も一般的なケース）。
      2. 閾値を超える場合、それより下位の候補の中に、閾値以下に収まる候補が
         いれば、その中でスコアが最も高い候補に切り替える（load balancing）。
         切り替えた理由を警告として記録する。
      3. 生存者全員が閾値を超える場合、元のスコア最上位候補をそのまま推薦し、
         「全候補が過負荷」という警告を記録する（依頼Part 11:
         "still allow assignment if necessary, mark it as an overload warning"）。
    """
    if not candidate_scores:
        return None, []

    projected = {
        c.member_id: compute_projected_workload_percentage(task, members_by_id[c.member_id])
        for c in candidate_scores
    }

    top = candidate_scores[0]
    if projected[top.member_id] <= warning_threshold:
        return top, []

    for alternative in candidate_scores[1:]:
        if projected[alternative.member_id] <= warning_threshold:
            note = (
                f"稼働バランスのため、スコア最上位候補({top.member_id}: "
                f"割当後稼働率{projected[top.member_id]}%)ではなく、"
                f"稼働率{projected[alternative.member_id]}%の{alternative.member_id}"
                f"(スコア{alternative.score}点)を推薦しました（load balancing）"
            )
            return alternative, [note]

    note = (
        f"すべての候補者の割当後稼働率が{warning_threshold}%を超えています"
        f"（最上位候補{top.member_id}: {projected[top.member_id]}%）。"
        "過負荷になる可能性があります。"
    )
    return top, [note]
