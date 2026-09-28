# backend/pipeline/assignment/audit.py
"""
Assignment Audit: 未割当タスクの理由を構造化して分類する。

既存の`filters.py`の4つのハード制約チェック関数(`check_skill_requirements`/
`check_availability`/`check_workload`/`check_explicit_constraints`)は
一切変更しない。ここではそれらを個別に呼び直し、「どのチェックが
引っかかったか」をコードに変換するだけの、完全に副作用の無い診断層。

`filter_candidates()`自体の戻り値(生存者・除外理由の集約方法)も変更しない
——この監査層は`AssignmentResult`が既に持っている情報を後から分類し直す
だけで、フィルタリング・スコアリング・workload balancingの判定結果には
一切影響を与えない。
"""

from __future__ import annotations

from collections import Counter
from typing import Dict, List, Literal, Optional

from pydantic import BaseModel, Field

from backend.pipeline.assignment.deadline import AssignmentLedger, check_cumulative_workload, check_deadline
from backend.pipeline.assignment.filters import (
    check_availability,
    check_explicit_constraints,
    check_skill_requirements,
    check_workload,
)
from backend.pipeline.assignment.schema import (
    AssignmentTask,
    CandidateRejection,
    CandidateScore,
    FinalAssignment,
    ScoringWeights,
)
from backend.pipeline.assignment.scoring import score_candidate
from backend.pipeline.members.schema import Member

# STEP7: Fallback Assignment。NO_REQUIRED_SKILLのみで除外された候補
# （availability/workload/explicit constraintは絶対に緩和しない）に限り、
# 既存のTF-IDF skill_similarity（Phase 11、scoring.pyで既に計算済み）が
# この閾値以上なら「警告付きの候補」として提示する。この値は実データ
# （backend/evaluation/datasets/specs.pyのSPEC_B + 実5人メンバー）で
# 具体的な一致例が見つからなかったため暫定値であり、将来実データが
# 増えた際に見直すことを想定している。
FALLBACK_SKILL_SIMILARITY_THRESHOLD = 0.3

UnassignedReason = Literal[
    "NO_CANDIDATE",
    "HARD_CONSTRAINT",
    "NO_REQUIRED_SKILL",
    "NO_AVAILABILITY",
    "WORKLOAD_TOO_HIGH",
    "DEADLINE_INFEASIBLE",
    "INVALID_MEMBER_DATA",
    "UNKNOWN",
]

# 複数の理由が同数で並んだ場合の優先順位（実際の判定結果に基づく分類を
# 一意に決めるための決定的なタイブレークであり、推測でUNKNOWNに逃げない）
_REASON_PRIORITY: List[str] = [
    "NO_REQUIRED_SKILL",
    "NO_AVAILABILITY",
    "WORKLOAD_TOO_HIGH",
    "DEADLINE_INFEASIBLE",
    "HARD_CONSTRAINT",
]


def classify_member_rejection(
    task: AssignmentTask, member: Member, ledger: Optional[AssignmentLedger] = None,
) -> List[str]:
    """1候補者がハード制約のどのチェックで除外されたかをコード化する。

    `filters.py`の各チェック関数をそのまま個別に呼ぶだけで、判定ロジック
    自体は一切再実装しない。1人が複数チェックに引っかかることもある。
    """
    codes: List[str] = []
    if check_skill_requirements(task, member):
        codes.append("NO_REQUIRED_SKILL")
    if check_availability(task, member):
        codes.append("NO_AVAILABILITY")
    if check_workload(task, member) or check_cumulative_workload(task, member, ledger):
        codes.append("WORKLOAD_TOO_HIGH")
    if check_explicit_constraints(task, member):
        codes.append("HARD_CONSTRAINT")
    if check_deadline(task, member, ledger):
        codes.append("DEADLINE_INFEASIBLE")
    return codes


def determine_unassigned_reason(
    task: AssignmentTask,
    members: List[Member],
    rejected_candidates: List[CandidateRejection],
    *,
    member_load_errors: bool = False,
    ledger: Optional[AssignmentLedger] = None,
) -> str:
    """未割当タスク1件の代表理由を1つ決める。

    候補者ごとの詳細は`rejected_candidates`(既存フィールド)にそのまま
    残っているため、ここでの1つの代表値は「タスク一覧を一目で分類する」
    ためのサマリーであり、詳細を隠すものではない。
    """
    try:
        if not members:
            return "NO_CANDIDATE"

        if member_load_errors and not rejected_candidates:
            # メンバーは渡されたが、読み込みエラーで実質的に候補が
            # 存在しなかった場合（本来のハード制約とは区別する）
            return "INVALID_MEMBER_DATA"

        if not rejected_candidates:
            # membersはいるが誰も除外されていない＝この関数の前提
            # （生存者0人）と矛盾するデータなので、推測せずUNKNOWNとする
            return "UNKNOWN"

        member_by_id = {m.id: m for m in members}
        tally: Counter = Counter()
        for rejection in rejected_candidates:
            member = member_by_id.get(rejection.member_id)
            if member is None:
                continue
            for code in classify_member_rejection(task, member, ledger):
                tally[code] += 1

        if not tally:
            return "UNKNOWN"

        max_count = max(tally.values())
        top_codes = {code for code, count in tally.items() if count == max_count}
        for candidate in _REASON_PRIORITY:
            if candidate in top_codes:
                return candidate
        return "UNKNOWN"
    except Exception:
        # 分類処理自体が想定外の例外を起こした場合のみ（実データに基づかない
        # 推測を返すのではなく、「分類できなかった」ことを明示する）
        return "UNKNOWN"


def find_fallback_candidate(
    task: AssignmentTask,
    members: List[Member],
    rejected_candidates: List[CandidateRejection],
    weights: Optional[ScoringWeights] = None,
    ledger: Optional[AssignmentLedger] = None,
) -> Optional[CandidateScore]:
    """ハード制約で拒否された候補の中から、Fallback候補を1人だけ探す。

    対象になるのは「NO_REQUIRED_SKILLだけ」で拒否された候補に限る
    ——availability/workload/explicit constraint/deadlineのいずれかで拒否された
    候補は、その制約が満たせていないという事実自体は変わらないため、
    絶対にFallback対象にしない。

    既存の`scoring.py::score_candidate`（TF-IDF skill_similarity含む）を
    そのまま呼ぶだけで、新しい類似度計算は行わない。閾値
    (`FALLBACK_SKILL_SIMILARITY_THRESHOLD`)を超える候補が無ければNoneを返す
    （＝Fallbackも見つからずUNASSIGNEDのまま）。

    必要スキルを持つメンバーが存在し、そのメンバーが負荷・納期などスキル以外の
    ハード制約だけで除外された場合も、Fallbackは探さない（Noneを返す）。
    Fallbackは「必要スキルを持つ人がいない」ときの救済であり、スキルを持つ人が
    空いていないときに別スキルの人へ回すためのものではないため。
    """
    member_by_id = {m.id: m for m in members}
    codes_by_member = {
        r.member_id: classify_member_rejection(task, member_by_id[r.member_id], ledger)
        for r in rejected_candidates if r.member_id in member_by_id
    }
    if any(codes and "NO_REQUIRED_SKILL" not in codes for codes in codes_by_member.values()):
        return None

    best: Optional[CandidateScore] = None

    for rejection in rejected_candidates:
        member = member_by_id.get(rejection.member_id)
        if member is None:
            continue
        if codes_by_member[rejection.member_id] != ["NO_REQUIRED_SKILL"]:
            continue

        candidate_score = score_candidate(task, member, weights)
        if candidate_score.skill_similarity < FALLBACK_SKILL_SIMILARITY_THRESHOLD:
            continue
        if best is None or candidate_score.skill_similarity > best.skill_similarity:
            best = candidate_score

    return best


class AssignmentAuditSummary(BaseModel):
    """ジョブ1回分のAssignment結果の集計（STEP5/13の実測に使う）"""

    total_tasks: int
    assigned_tasks: int
    unassigned_tasks: int
    success_rate: float
    unassigned_by_reason: Dict[str, int] = Field(default_factory=dict)


def summarize_assignment_audit(final_assignments: List[FinalAssignment]) -> AssignmentAuditSummary:
    """既存の`FinalAssignment`一覧から、Total/Assigned/Unassigned/理由別件数を集計する。

    実測値のみを扱う純粋な集計関数（推測・補完は行わない）。
    """
    total = len(final_assignments)
    assigned = sum(1 for fa in final_assignments if fa.assigned_member_id is not None)
    unassigned = total - assigned

    reason_counts: Counter = Counter()
    for fa in final_assignments:
        if fa.assigned_member_id is not None:
            continue
        reason: Optional[str] = fa.ai_recommendation.unassigned_reason
        reason_counts[reason or "UNKNOWN"] += 1

    success_rate = round((assigned / total) * 100, 2) if total > 0 else 0.0

    return AssignmentAuditSummary(
        total_tasks=total,
        assigned_tasks=assigned,
        unassigned_tasks=unassigned,
        success_rate=success_rate,
        unassigned_by_reason=dict(reason_counts),
    )
