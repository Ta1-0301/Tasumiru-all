# backend/pipeline/tasks/validator.py
"""
Stage: Task Validation。

決定的（ルールベース）に完結させ、LLMを使わない。同じ入力に対して常に同じ
結果になる（再現性がある）。

重要: **無効な結果を黙って修復しない。** 検出した問題は`ValidationIssue`と
して記録し、`apply_review_flags()`で該当タスクに`needs_review=True`と
`review_reasons`を付けるだけで、タスクのどのフィールドも書き換えない。

検出対象は依頼の7項目:
  - tasks without requirements
  - duplicate tasks
  - overly broad tasks
  - overly granular tasks
  - missing source references
  - missing acceptance criteria
  - invalid estimated hours
"""

from __future__ import annotations

import difflib
from collections import defaultdict
from typing import Dict, List, Optional

from backend.pipeline.requirements.schema import Requirement
from backend.pipeline.tasks.schema import Task, ValidationIssue

DUPLICATE_TITLE_SIMILARITY_THRESHOLD = 0.85
MAX_PLAUSIBLE_HOURS = 500

# 「システム全体」的な、明らかに広すぎるタスクを示す語
BROAD_KEYWORDS = ["システム全体", "全機能", "すべての機能", "アプリ全体", "プロジェクト全体", "一式"]

# 接続詞的な表現。複数の作業が1タスクに束ねられている可能性のシグナル
CONJUNCTION_MARKERS = ["、また", "および", "かつ", "、そして", "とともに"]

# 依頼の例（「アップロードボタンの色を変える」）が示すような、明示的な言及が
# 無い限り作るべきでない、些末なUI微調整を示す語
TRIVIAL_UI_KEYWORDS = [
    "色を変える", "色を変更する", "文言を修正する", "テキストを変更する",
    "フォントを変更する", "ラベルを変更する", "余白を調整する", "配置を微調整する",
]


def check_tasks_without_requirements(tasks: List[Task]) -> List[ValidationIssue]:
    """requirement_idsが空の（どの要求にも紐づいていない）タスクを検出する"""
    issues: List[ValidationIssue] = []
    for t in tasks:
        if not t.requirement_ids:
            issues.append(ValidationIssue(
                code="TASK_WITHOUT_REQUIREMENT",
                message="requirement_idsが空です（どの要求にも紐づいていません）",
                task_ids=[t.id],
            ))
    return issues


def check_duplicate_tasks(
    tasks: List[Task], threshold: float = DUPLICATE_TITLE_SIMILARITY_THRESHOLD
) -> List[ValidationIssue]:
    """タイトルの類似度が高いタスクの組を重複の疑いとして検出する"""
    issues: List[ValidationIssue] = []
    for i in range(len(tasks)):
        for j in range(i + 1, len(tasks)):
            a, b = tasks[i], tasks[j]
            ratio = difflib.SequenceMatcher(None, a.title, b.title).ratio()
            if ratio >= threshold:
                issues.append(ValidationIssue(
                    code="DUPLICATE_TASK",
                    message=f"タイトルの類似度が高く重複の疑いがあります（類似度{ratio:.2f}）",
                    task_ids=[a.id, b.id],
                ))
    return issues


def check_overly_broad_tasks(tasks: List[Task]) -> List[ValidationIssue]:
    """「システム全体を実装する」のような、広すぎるタスクを検出する簡易ヒューリスティック"""
    issues: List[ValidationIssue] = []
    for t in tasks:
        text = f"{t.title} {t.description}"
        if any(k in text for k in BROAD_KEYWORDS):
            issues.append(ValidationIssue(
                code="OVERLY_BROAD_TASK",
                message="タスクが広すぎる可能性があります（システム全体を指す表現を含む）",
                task_ids=[t.id],
            ))
            continue
        if any(m in t.title for m in CONJUNCTION_MARKERS):
            issues.append(ValidationIssue(
                code="OVERLY_BROAD_TASK",
                message="複数の作業が1つのタスクに束ねられている可能性があります",
                task_ids=[t.id],
            ))
            continue
        if len(t.title) > 80:
            issues.append(ValidationIssue(
                code="OVERLY_BROAD_TASK",
                message="タイトルが非常に長く、複数の要素を含んでいる可能性があります",
                task_ids=[t.id],
            ))
    return issues


def check_overly_granular_tasks(
    tasks: List[Task], requirements_by_id: Optional[Dict[str, Requirement]] = None
) -> List[ValidationIssue]:
    """不必要に細かすぎるタスク（依頼の例: ボタンの色変更）を検出する簡易ヒューリスティック。

    要求(requirement)本文にその些末な変更が明記されている場合は許容する
    （依頼の"unless explicitly required"に対応）。
    """
    issues: List[ValidationIssue] = []
    for t in tasks:
        text = f"{t.title} {t.description}"
        matched_keyword = next((k for k in TRIVIAL_UI_KEYWORDS if k in text), None)
        if matched_keyword is None:
            continue

        explicitly_required = False
        if requirements_by_id:
            for req_id in t.requirement_ids:
                requirement = requirements_by_id.get(req_id)
                if requirement and matched_keyword in requirement.description:
                    explicitly_required = True
                    break

        if not explicitly_required:
            issues.append(ValidationIssue(
                code="OVERLY_GRANULAR_TASK",
                message=f"要求に明記されていない些末な変更（'{matched_keyword}'）の可能性があります",
                task_ids=[t.id],
            ))
    return issues


def check_missing_source_references(tasks: List[Task]) -> List[ValidationIssue]:
    """source_reference（特にsource_text）が設定されているかを確認する"""
    issues: List[ValidationIssue] = []
    for t in tasks:
        ref = t.source_reference
        if ref is None or not ref.source_text or not ref.source_text.strip():
            issues.append(ValidationIssue(
                code="MISSING_SOURCE_REFERENCE",
                message="出典(source_reference.source_text)が設定されていません",
                task_ids=[t.id],
            ))
    return issues


def check_source_text_matches_document(
    tasks: List[Task], document_text: str
) -> List[ValidationIssue]:
    """出典が元の仕様書に実在するかを再確認する（防御的な二重チェック）。

    タスクの出典は常にRequirementから機械的に引き継がれるため通常は必ず一致
    するはずだが、将来的な変更でその保証が崩れた場合に検出できるようにする
    ための最終防衛線。「元の仕様書を直接パースし直さない」という方針の
    唯一の例外（出典の再検証）に対応する任意のチェック。
    """
    issues: List[ValidationIssue] = []
    for t in tasks:
        ref = t.source_reference
        if ref and ref.source_text and ref.source_text not in document_text:
            issues.append(ValidationIssue(
                code="SOURCE_NOT_FOUND",
                message="出典が元の仕様書本文に見つかりません（捏造の疑い）",
                task_ids=[t.id],
            ))
    return issues


def check_missing_acceptance_criteria(tasks: List[Task]) -> List[ValidationIssue]:
    """acceptance_criteriaが空でないかを確認する（完了判断の基準が無いタスクを検出）"""
    issues: List[ValidationIssue] = []
    for t in tasks:
        if not t.acceptance_criteria:
            issues.append(ValidationIssue(
                code="MISSING_ACCEPTANCE_CRITERIA",
                message="acceptance_criteriaが空です（完了判断の基準がありません）",
                task_ids=[t.id],
            ))
    return issues


def check_invalid_estimated_hours(
    tasks: List[Task], max_plausible_hours: float = MAX_PLAUSIBLE_HOURS
) -> List[ValidationIssue]:
    """見積り工数が設定されている場合、その値が現実的かを確認する。

    見積りが未設定(None)であること自体は「不明」の正直な申告であり、
    それ単体は無効とはみなさない。
    """
    issues: List[ValidationIssue] = []
    for t in tasks:
        if t.estimated_hours is None:
            continue
        if t.estimated_hours <= 0 or t.estimated_hours > max_plausible_hours:
            issues.append(ValidationIssue(
                code="INVALID_ESTIMATED_HOURS",
                message=f"estimated_hoursの値が非現実的です（{t.estimated_hours}）",
                task_ids=[t.id],
            ))
    return issues


def validate_tasks(
    tasks: List[Task],
    requirements_by_id: Optional[Dict[str, Requirement]] = None,
    source_document_text: Optional[str] = None,
) -> List[ValidationIssue]:
    """依頼された7種類の検証すべてを実行し、検出された問題点を1つのリストにまとめる"""
    issues: List[ValidationIssue] = []
    issues += check_tasks_without_requirements(tasks)
    issues += check_duplicate_tasks(tasks)
    issues += check_overly_broad_tasks(tasks)
    issues += check_overly_granular_tasks(tasks, requirements_by_id=requirements_by_id)
    issues += check_missing_source_references(tasks)
    issues += check_missing_acceptance_criteria(tasks)
    issues += check_invalid_estimated_hours(tasks)
    if source_document_text is not None:
        issues += check_source_text_matches_document(tasks, source_document_text)
    return issues


def apply_review_flags(tasks: List[Task], issues: List[ValidationIssue]) -> List[Task]:
    """検証で検出した問題を、該当タスクの`needs_review`/`review_reasons`として
    印を付けるだけの関数。**どのタスクのフィールドも書き換えない**
    （依頼の"Do not silently fix invalid results. Mark them for review."に対応）。
    """
    reasons_by_id: Dict[str, List[str]] = defaultdict(list)
    for issue in issues:
        for task_id in issue.task_ids:
            reasons_by_id[task_id].append(f"{issue.code}: {issue.message}")

    updated: List[Task] = []
    for t in tasks:
        reasons = reasons_by_id.get(t.id)
        if reasons:
            updated.append(t.model_copy(update={"needs_review": True, "review_reasons": reasons}))
        else:
            updated.append(t)
    return updated
