# backend/pipeline/assignment/runner.py
"""
Phase 7のオーケストレーター。

Step 1 候補者フィルタリング(filters.py)
  → Step 2 決定的スコアリング(scoring.py)
  → Step 3 （任意）LLMによる補足説明(reasoning.py)
  → AssignmentResult（tasks側のdependencies情報も、未完了なら警告として反映する）

**LLMは`reasons`/`warnings`にしか影響しない。** `recommended_member_id`と
`score`はStep 2の時点で確定し、その後LLMの結果によって書き換えられることは
無い。
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, List, Optional, Set

from backend.pipeline.assignment.audit import determine_unassigned_reason, find_fallback_candidate
from backend.pipeline.assignment.deadline import AssignmentLedger, free_hours_until
from backend.pipeline.assignment.filters import filter_candidates
from backend.pipeline.assignment.reasoning import generate_llm_reasoning
from backend.pipeline.assignment.schema import AssignmentResult, AssignmentTask, ScoringWeights
from backend.pipeline.assignment.scoring import detect_close_scores, score_candidates
from backend.pipeline.assignment.workload_balancing import select_recommended_candidate
from backend.pipeline.members.schema import Member
from backend.services.llm import BaseLLMClient

OUTPUT_DIR = Path(__file__).resolve().parent / "output"


def _build_score_summary_reason(
    task: AssignmentTask, top_member: Member, top_score, is_top: bool = True,
) -> str:
    head = (
        f"{top_member.name}が最高スコア({top_score.score}点)でした" if is_top
        else f"{top_member.name}を推薦しました（スコア{top_score.score}点）"
    )
    return (
        f"{head}"
        f"（skill_match={top_score.skill_match}, workload={top_score.workload_score}, "
        f"experience={top_score.experience_score}, availability={top_score.availability_score}）"
    )


def _build_soft_constraint_warnings(member: Member) -> List[str]:
    """ハード制約ではないが人が把握すべき事項（requires_review等）を警告として拾う"""
    warnings: List[str] = []
    for c in member.constraints:
        if c.type == "requires_review":
            warnings.append(f"{member.name}には追加のレビュー要件があります: {c.value}")
    return warnings


def _build_unmet_dependency_warnings(
    task: AssignmentTask, completed_task_ids: Optional[Set[str]]
) -> List[str]:
    """タスクの前提タスクが未完了の場合の警告（completed_task_idsが渡された場合のみ判定する）"""
    if not task.dependencies or completed_task_ids is None:
        return []
    unmet = [d for d in task.dependencies if d not in completed_task_ids]
    if unmet:
        return [f"前提タスクが未完了です: {unmet}"]
    return []


def _build_deadline_reason(
    task: AssignmentTask, member: Member, ledger: Optional[AssignmentLedger]
) -> List[str]:
    """期限付きタスクの場合、期限内に完了可能と判定した根拠を理由として残す"""
    if (
        ledger is None or ledger.reference_date is None
        or task.due_date is None or task.estimated_hours is None
    ):
        return []
    available = round(free_hours_until(member, ledger.reference_date, task.due_date), 2)
    committed = round(sum(
        h for h, d in ledger.committed.get(member.id, []) if d is not None and d <= task.due_date
    ), 2)
    return [
        f"期限({task.due_date.isoformat()})までの稼働可能時間{available}hに対し、"
        f"割当済み{committed}h + このタスク{task.estimated_hours}hで期限内に完了可能です"
    ]


async def run_assignment(
    task: AssignmentTask,
    members: Iterable[Member],
    weights: Optional[ScoringWeights] = None,
    client: Optional[BaseLLMClient] = None,
    completed_task_ids: Optional[Set[str]] = None,
    member_load_errors: bool = False,
    ledger: Optional[AssignmentLedger] = None,
) -> AssignmentResult:
    """1件のタスクに対するメンバーアサインを推薦する。

    `client`を渡さない場合、Step 3（LLMによる補足説明）は完全にスキップされ、
    結果は決定的スコアリングのみに基づく（LLM呼び出しが任意であることの実装）。

    `member_load_errors`はAssignment Audit用の任意引数（既定False）。
    メンバーディレクトリの読み込み時に無効なレコードが存在したかどうかを
    伝えるだけで、フィルタリング・スコアリングの判定には一切影響しない。

    `ledger`は割当済み工数の台帳（任意、既定None＝従来と同じ判定）。
    渡された場合、割当後に負荷率が100%を超える候補と、期限までに完了できない
    候補をハード制約として除外し、残った候補の中から負荷が均一になる候補を
    推薦する（`workload_balancing.select_recommended_candidate`）。
    台帳への追記は呼び出し側が行う。
    """
    members = list(members)
    survivors, rejections = filter_candidates(task, members, ledger)

    dependency_warnings = _build_unmet_dependency_warnings(task, completed_task_ids)

    if not survivors:
        # STEP7: Fallback Assignment。availability/workload/explicit constraint
        # で拒否された候補は対象にせず、スキル不一致のみで拒否された候補の中に
        # 既存のTF-IDF skill_similarityが閾値を超える者がいる場合に限り、
        # 警告付きで候補として提示する（ハード制約を回避するものではない）。
        fallback = find_fallback_candidate(
            task, members, rejections, weights, ledger=ledger,
        )
        if fallback is not None:
            fallback_member = next(m for m in members if m.id == fallback.member_id)
            return AssignmentResult(
                task_id=task.task_id,
                recommended_member_id=fallback.member_id,
                score=fallback.score,
                candidate_scores=[fallback],
                rejected_candidates=rejections,
                reasons=[
                    f"{fallback_member.name}は必要スキルの完全一致は無いものの、"
                    f"関連スキルの類似度({fallback.skill_similarity})からFallback候補として提示します"
                ] + _build_deadline_reason(task, fallback_member, ledger),
                warnings=["REQUIRED_SKILL_NOT_EXACT_MATCH"] + dependency_warnings,
                status="recommended",
            )

        unassigned_reason = determine_unassigned_reason(
            task, members, rejections, member_load_errors=member_load_errors,
            ledger=ledger,
        )
        return AssignmentResult(
            task_id=task.task_id,
            status="no_suitable_member",
            rejected_candidates=rejections,
            warnings=["ハード制約を満たす候補者がいませんでした"] + dependency_warnings,
            unassigned_reason=unassigned_reason,
        )

    candidate_scores = score_candidates(task, survivors, weights)
    member_by_id = {m.id: m for m in survivors}

    # Part 11: スコア最上位ではなく、稼働バランスを考慮した推薦者を選ぶ。
    # `candidate_scores`自体はここでは並べ替えない（純粋なスコアランキングとして
    # そのままAssignmentResultに残す。Part 15: traceability）。
    recommended, workload_warnings = select_recommended_candidate(
        task, candidate_scores, member_by_id, ledger=ledger,
    )
    recommended_member = member_by_id[recommended.member_id]

    reasons = [_build_score_summary_reason(
        task, recommended_member, recommended, is_top=recommended is candidate_scores[0],
    )]
    reasons += _build_deadline_reason(task, recommended_member, ledger)
    warnings = _build_soft_constraint_warnings(recommended_member) + dependency_warnings + workload_warnings

    ambiguity_warning = detect_close_scores(candidate_scores)
    if ambiguity_warning:
        warnings.append(ambiguity_warning)

    if client is not None:
        llm_reasons, llm_warnings = await generate_llm_reasoning(task, candidate_scores, client)
        reasons += llm_reasons
        warnings += llm_warnings

    return AssignmentResult(
        task_id=task.task_id,
        recommended_member_id=recommended.member_id,
        score=recommended.score,
        candidate_scores=candidate_scores,
        rejected_candidates=rejections,
        reasons=reasons,
        warnings=warnings,
        status="recommended",
    )


def save_assignment_result(result: AssignmentResult, output_dir: Path = OUTPUT_DIR) -> Path:
    """AssignmentResultを保存する（中間結果の永続化）"""
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_path = output_dir / f"{result.task_id}_{timestamp}.assignment.json"
    out_path.write_text(
        json.dumps(result.model_dump(mode="json"), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return out_path


async def _main() -> None:
    import sys

    if len(sys.argv) < 3:
        print(
            "使い方: python -m backend.pipeline.assignment.runner "
            "<assignment_task.jsonのパス> <members.jsonのパス> [--llm]"
        )
        raise SystemExit(1)

    task = AssignmentTask.model_validate(json.loads(Path(sys.argv[1]).read_text(encoding="utf-8")))
    members_data = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
    members = [Member.model_validate(m) for m in members_data.get("members", members_data)]

    client = None
    if "--llm" in sys.argv:
        from backend.services.llm import get_llm_client  # 既存のプロバイダー抽象化をそのまま使う

        client = get_llm_client()

    result = await run_assignment(task, members, client=client)
    out_path = save_assignment_result(result)

    print(f"status={result.status} recommended={result.recommended_member_id} score={result.score}")
    print(f"保存先: {out_path}")


if __name__ == "__main__":
    asyncio.run(_main())
