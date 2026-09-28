# backend/pipeline/final_output/assembler.py
"""
Phase 9のコア: 検証済みの中間結果から最終出力を組み立てる。

**新しい情報は一切生成しない。** requirements/tasks/dependencies/members/
assignmentsはPhase 3-7の出力からそのまま転記する。新規に計算するのは
タイムスタンプ・プロンプトのフィンガープリント・valid/warning/errorの
分類ラベルのみで、いずれも既存データからの機械的な導出。

元の仕様書（原文テキスト）は入力として受け取らず、一切参照・変更しない
（依頼の"Do not modify the original source document"に対応）。
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import List, Optional

from backend.pipeline.assignment.schema import FinalAssignment
from backend.pipeline.dependencies.schema import DependencyDocument
from backend.pipeline.final_output.metadata import PIPELINE_VERSION, compute_prompt_versions, resolve_model_info
from backend.pipeline.final_output.schema import FinalProjectOutput, ProjectInfo, ProjectMetadata
from backend.pipeline.final_output.validation_summary import build_validation_summary
from backend.pipeline.members.schema import MemberDirectory
from backend.pipeline.requirements.schema import RequirementDocument
from backend.pipeline.tasks.schema import TaskDocument
from backend.pipeline.validation.schema import ValidationReport


class CriticalValidationError(Exception):
    """重大な検証エラーがある出力を、確認なしに完成品として扱おうとした場合に投げる"""


def assemble_final_output(
    requirement_document: RequirementDocument,
    task_document: TaskDocument,
    dependency_document: DependencyDocument,
    member_directory: MemberDirectory,
    assignments: List[FinalAssignment],
    validation_report: ValidationReport,
    project_name: Optional[str] = None,
    start_date: Optional[date] = None,
    due_date: Optional[date] = None,
    planning_reference_date: Optional[date] = None,
) -> FinalProjectOutput:
    """検証済みの中間結果だけから、最終的な構造化プロジェクト出力を組み立てる。

    `validation_report.valid`がFalse、あるいは組み立て後の
    `status=="error"`であっても、この関数自体は組み立てを拒否しない
    ——検証結果を隠さず常に完全な形で報告するのがこの関数の役目であり、
    「問題無い完成品として扱ってよいか」を確認するのは
    `ensure_safe_to_publish()`を呼び出す側の責任。
    """
    model, model_version, models_by_phase = resolve_model_info(
        requirement_document, task_document, dependency_document
    )

    generated_at = datetime.now(timezone.utc).isoformat()

    metadata = ProjectMetadata(
        generated_at=generated_at,
        pipeline_version=PIPELINE_VERSION,
        model=model,
        model_version=model_version,
        prompt_versions=compute_prompt_versions(),
        document_id=requirement_document.document_id,
        models_by_phase=models_by_phase,
    )

    validation_summary = build_validation_summary(validation_report, task_document.tasks)

    project = ProjectInfo(
        document_id=requirement_document.document_id,
        name=project_name,
        exported_at=generated_at,
        start_date=start_date,
        due_date=due_date,
        planning_reference_date=planning_reference_date,
    )

    return FinalProjectOutput(
        project=project,
        requirements=requirement_document.requirements,
        tasks=task_document.tasks,
        dependencies=dependency_document.dependencies,
        members=member_directory.members,
        assignments=assignments,
        validation=validation_summary,
        metadata=metadata,
    )


def ensure_safe_to_publish(output: FinalProjectOutput) -> None:
    """`output.validation.status == "error"`の場合に`CriticalValidationError`
    を投げる。依頼の"Do not output an apparently valid project if
    validation contains critical errors"を、これを呼び出す側（例:
    エクスポートAPI・フロントエンドへの配信処理）で強制するためのゲート。
    """
    if output.validation.status == "error":
        raise CriticalValidationError(
            f"重大な検証エラーが{output.validation.critical_issue_count}件あるため、"
            "この出力を確定済みの成果物として扱うことはできません。"
        )
