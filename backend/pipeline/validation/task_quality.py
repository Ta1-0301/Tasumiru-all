# backend/pipeline/validation/task_quality.py
"""
CHECK 7: Task Data Quality。

完全に決定的（LLM不使用）。プロジェクト計画全体の検証(Phase 8)に、
タスク単体の品質シグナルを反映する。

  - タスクがPhase 4(`backend.pipeline.tasks.validator`)で既に
    `needs_review=True`と判定されている場合（依頼Part 14の
    "missing source references"・"invalid estimated effort"はここに含まれる
    ——Phase 4で既に検出済みの問題を、Phase 8のValidationReportでも
    見落とさず反映するだけであり、判定ロジックを重複実装しない）。
  - タスクの`required_skills`が未特定("unknown"のみ)の場合
    （依頼Part 14の"missing required skills"）。
"""

from __future__ import annotations

from typing import List

from backend.pipeline.tasks.schema import Task
from backend.pipeline.validation.schema import TaskQualityIssue

UNKNOWN_SKILL_SENTINEL = "unknown"


def check_needs_review_tasks(tasks: List[Task]) -> List[TaskQualityIssue]:
    """Phase 4で既にneeds_review=Trueと判定済みのタスクを報告する（再検証はしない）"""
    issues: List[TaskQualityIssue] = []
    for t in tasks:
        if not t.needs_review:
            continue
        reasons = t.review_reasons or ["理由不明（review_reasonsが空）"]
        for reason in reasons:
            issues.append(TaskQualityIssue(task_id=t.id, code="NEEDS_REVIEW", message=reason))
    return issues


def check_missing_required_skills(tasks: List[Task]) -> List[TaskQualityIssue]:
    """必要スキルが特定できていない（'unknown'のみ、または空）タスクを検出する。

    このようなタスクはassignmentのスキルマッチング（Phase 7/Part 5）が
    実質的に機能しない（誰でもマッチしてしまう）ため、明示的に可視化する。
    """
    issues: List[TaskQualityIssue] = []
    for t in tasks:
        skills = t.required_skills or []
        if not skills or all(s.strip().lower() == UNKNOWN_SKILL_SENTINEL for s in skills):
            issues.append(TaskQualityIssue(
                task_id=t.id, code="MISSING_REQUIRED_SKILLS",
                message="このタスクの必要スキルが特定できていません（'unknown'）。担当者選定の精度が下がる可能性があります",
            ))
    return issues


def check_task_quality(tasks: List[Task]) -> List[TaskQualityIssue]:
    """CHECK 7の全チェックをまとめて実行する"""
    issues: List[TaskQualityIssue] = []
    issues += check_needs_review_tasks(tasks)
    issues += check_missing_required_skills(tasks)
    return issues
