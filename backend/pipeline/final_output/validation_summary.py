# backend/pipeline/final_output/validation_summary.py
"""
Phase 8の`ValidationReport`（bool一本の`valid`のみ）を、依頼の
"Clearly distinguish: valid / warning / error"に対応する3段階に分類する。

完全に決定的。分類ルールを変えたい場合は`CRITICAL_DEPENDENCY_CODES`と
本モジュールの集計ロジックだけを変更すればよい（アプリ全体に分類基準を
ハードコードしない）。
"""

from __future__ import annotations

from typing import List

from backend.pipeline.final_output.schema import ValidationSummary
from backend.pipeline.final_output.traceability import find_untraceable_tasks
from backend.pipeline.tasks.schema import Task
from backend.pipeline.validation.schema import ValidationReport

# dependency_errorsのうち、計画として実行不可能なほど重大なもの。
# ASSIGNED_BEFORE_DEPENDENCY（順序の注意事項）はここに含めず、warning側とする。
CRITICAL_DEPENDENCY_CODES = {
    "CIRCULAR_DEPENDENCY",
    "IMPOSSIBLE_ORDERING",
    "MISSING_DEPENDENCY_REFERENCE",
}


def build_validation_summary(report: ValidationReport, tasks: List[Task]) -> ValidationSummary:
    """critical（error）に分類する項目:
      - missing_requirements（要求が1つもタスク化されていない）
      - constraint_violations（ハード制約違反）
      - dependency_errorsのうちCRITICAL_DEPENDENCY_CODES
      - タスク -> 要求のトレーサビリティ欠落（このフェーズ独自の検証）

    warningに分類する項目:
      - duplicate_tasks（レビュー対象。削除・強制はしない）
      - dependency_errorsのうちASSIGNED_BEFORE_DEPENDENCY
      - workload_warnings
      - skill_mismatches
      - task_quality_issues（Phase 11 Part 14: CHECK 7。個々のタスクの
        品質シグナルであり、計画全体を実行不可能にするものではないためwarning扱い）
      - assignment_score_anomalies（Phase 11 Part 14: CHECK 8。スコアが低い
        割り当てであり、それ自体はハード制約違反ではないためwarning扱い）

    critical>0なら"error"、critical==0かつwarning>0なら"warning"、
    どちらも0なら"valid"。
    """
    traceability_errors = find_untraceable_tasks(tasks)

    critical = (
        len(report.missing_requirements)
        + len(report.constraint_violations)
        + sum(1 for e in report.dependency_errors if e.code in CRITICAL_DEPENDENCY_CODES)
        + len(traceability_errors)
    )
    warning = (
        len(report.duplicate_tasks)
        + sum(1 for e in report.dependency_errors if e.code not in CRITICAL_DEPENDENCY_CODES)
        + len(report.workload_warnings)
        + len(report.skill_mismatches)
        + len(report.task_quality_issues)
        + len(report.assignment_score_anomalies)
    )

    if critical > 0:
        status = "error"
    elif warning > 0:
        status = "warning"
    else:
        status = "valid"

    return ValidationSummary(
        status=status,
        critical_issue_count=critical,
        warning_issue_count=warning,
        traceability_errors=traceability_errors,
        report=report,
    )
