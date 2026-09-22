# backend/pipeline/validation/runner.py
"""
Phase 8のオーケストレーター。

requirements + tasks + dependencies + members + assignments
  → CHECK 1-6（すべて決定的。CHECK 2のみ任意でLLM検証を追加できる）
  → ValidationReport（検証結果。フロントエンドが警告として表示する）

**検証で見つかった問題は一切修復しない。** このモジュールは常に
全チェックを実行し、見つかった問題をすべて`ValidationReport`に含める
（"Validation errors must not be silently ignored"への対応）。
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from backend.pipeline.assignment.schema import FinalAssignment, RequiredSkill
from backend.pipeline.dependencies.schema import Dependency
from backend.pipeline.members.schema import Member
from backend.pipeline.requirements.schema import Requirement
from backend.pipeline.tasks.schema import Task
from backend.pipeline.validation.constraints import check_assignment_constraints
from backend.pipeline.validation.dependencies import check_dependencies
from backend.pipeline.validation.duplicates import find_duplicate_candidates, verify_duplicates_with_llm
from backend.pipeline.validation.missing_requirements import find_missing_requirements
from backend.pipeline.validation.schema import ValidationReport
from backend.pipeline.validation.score_anomaly import check_assignment_score_anomalies
from backend.pipeline.validation.skill_mismatch import check_skill_mismatches
from backend.pipeline.validation.task_quality import check_task_quality
from backend.pipeline.validation.unassigned import check_unassigned_tasks
from backend.pipeline.validation.workload import check_workload
from backend.services.llm import BaseLLMClient

OUTPUT_DIR = Path(__file__).resolve().parent / "output"


def assignments_from_final(final_assignments: List[FinalAssignment]) -> Dict[str, str]:
    """Phase 7のFinalAssignment一覧から、task_id -> member_idのマッピングを作る
    （未割り当て(assigned_member_id=None)のタスクは含めない）。
    """
    return {
        fa.task_id: fa.assigned_member_id
        for fa in final_assignments
        if fa.assigned_member_id is not None
    }


def validate_project_plan(
    requirements: List[Requirement],
    tasks: List[Task],
    dependencies: List[Dependency],
    members: List[Member],
    assignments: Dict[str, str],
    required_skill_levels: Optional[Dict[str, List[RequiredSkill]]] = None,
    duplicate_similarity_threshold: float = 0.7,
    final_assignments: Optional[List[FinalAssignment]] = None,
) -> ValidationReport:
    """CHECK 1-9を実行し、ValidationReportを構築する（決定的、LLM不使用）。

    `final_assignments`はPhase 11 Part 14で追加されたCHECK 8
    （割り当てスコアの異常検出）と、Assignment未割当調査で追加されたCHECK 9
    （未割当タスクの検出）にのみ使う任意の引数。渡されなければCHECK 8/9は
    スキップされる（スコア情報を持たない呼び出し元との後方互換性、Part 20）。
    """
    valid_task_ids = [t.id for t in tasks]

    missing_requirements = find_missing_requirements(requirements, tasks)
    duplicate_tasks = find_duplicate_candidates(tasks, threshold=duplicate_similarity_threshold)
    dependency_errors = check_dependencies(dependencies, valid_task_ids, assignments)
    workload_summaries, workload_warnings = check_workload(members, tasks, assignments)
    skill_mismatches = check_skill_mismatches(tasks, members, assignments, required_skill_levels)
    constraint_violations = check_assignment_constraints(tasks, members, assignments, required_skill_levels)
    task_quality_issues = check_task_quality(tasks)
    assignment_score_anomalies = (
        check_assignment_score_anomalies(final_assignments) if final_assignments is not None else []
    )
    unassigned_tasks = (
        check_unassigned_tasks(final_assignments) if final_assignments is not None else []
    )

    valid = not any([
        missing_requirements,
        duplicate_tasks,
        dependency_errors,
        workload_warnings,
        skill_mismatches,
        constraint_violations,
        assignment_score_anomalies,
        unassigned_tasks,
        # task_quality_issuesは意図的にvalid判定から除外する: NEEDS_REVIEWは
        # Phase 4時点で既にレビュー対象として明示されている既知の問題であり、
        # ここで二重にプロジェクト全体を"invalid"扱いにすると、Phase 4段階の
        # 個別タスクレビューが常にプロジェクト全体をブロックしてしまう。
        # 既存のCHECK 1-6・CHECK 8とは異なり、フロントエンドに「参考情報」
        # として表示するための項目として位置づける。
    ])

    return ValidationReport(
        valid=valid,
        missing_requirements=missing_requirements,
        duplicate_tasks=duplicate_tasks,
        dependency_errors=dependency_errors,
        workload_warnings=workload_warnings,
        workload_summaries=workload_summaries,
        skill_mismatches=skill_mismatches,
        constraint_violations=constraint_violations,
        task_quality_issues=task_quality_issues,
        assignment_score_anomalies=assignment_score_anomalies,
        unassigned_tasks=unassigned_tasks,
        generated_at=datetime.now(timezone.utc).isoformat(),
    )


async def validate_project_plan_with_llm_verification(
    requirements: List[Requirement],
    tasks: List[Task],
    dependencies: List[Dependency],
    members: List[Member],
    assignments: Dict[str, str],
    client: Optional[BaseLLMClient] = None,
    required_skill_levels: Optional[Dict[str, List[RequiredSkill]]] = None,
    duplicate_similarity_threshold: float = 0.7,
    final_assignments: Optional[List[FinalAssignment]] = None,
) -> ValidationReport:
    """`validate_project_plan`を実行した上で、`client`が渡された場合のみ、
    CHECK 2の重複候補についてLLMによる意味的検証を追加する（任意）。

    LLM検証は既に決定的に見つかった候補の`method`/`reason`を更新するだけで、
    候補の追加・削除は一切行わない（重複候補の個数は変化しない）。
    """
    report = validate_project_plan(
        requirements, tasks, dependencies, members, assignments,
        required_skill_levels=required_skill_levels,
        duplicate_similarity_threshold=duplicate_similarity_threshold,
        final_assignments=final_assignments,
    )

    if client is not None and report.duplicate_tasks:
        tasks_by_id = {t.id: t for t in tasks}
        verified = await verify_duplicates_with_llm(tasks_by_id, report.duplicate_tasks, client)
        report = report.model_copy(update={"duplicate_tasks": verified})

    return report


def save_validation_report(report: ValidationReport, output_dir: Path = OUTPUT_DIR) -> Path:
    """検証レポートを保存する（中間結果の永続化）"""
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_path = output_dir / f"validation_{timestamp}.json"
    out_path.write_text(
        json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return out_path


async def _main() -> None:
    import sys

    if len(sys.argv) < 6:
        print(
            "使い方: python -m backend.pipeline.validation.runner "
            "<requirements.json> <tasks.json> <dependencies.json> <members.json> <assignments.json> [--llm]"
        )
        raise SystemExit(1)

    from backend.pipeline.dependencies.schema import DependencyDocument
    from backend.pipeline.members.schema import MemberDirectory
    from backend.pipeline.requirements.schema import RequirementDocument
    from backend.pipeline.tasks.schema import TaskDocument

    req_doc = RequirementDocument.model_validate(json.loads(Path(sys.argv[1]).read_text(encoding="utf-8")))
    task_doc = TaskDocument.model_validate(json.loads(Path(sys.argv[2]).read_text(encoding="utf-8")))
    dep_doc = DependencyDocument.model_validate(json.loads(Path(sys.argv[3]).read_text(encoding="utf-8")))
    member_dir = MemberDirectory.model_validate(json.loads(Path(sys.argv[4]).read_text(encoding="utf-8")))
    assignments = json.loads(Path(sys.argv[5]).read_text(encoding="utf-8"))

    client = None
    if "--llm" in sys.argv:
        from backend.services.llm import get_llm_client  # 既存のプロバイダー抽象化をそのまま使う

        client = get_llm_client()

    report = await validate_project_plan_with_llm_verification(
        req_doc.requirements, task_doc.tasks, dep_doc.dependencies, member_dir.members,
        assignments, client=client,
    )
    out_path = save_validation_report(report)

    print(f"valid={report.valid}")
    print(f"保存先: {out_path}")


if __name__ == "__main__":
    asyncio.run(_main())
