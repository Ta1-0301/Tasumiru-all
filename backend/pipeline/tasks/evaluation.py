# backend/pipeline/tasks/evaluation.py
"""
評価支援（Evaluation support）。

生成されたタスクが、依頼のGOAL節に書かれた「良いタスク」の条件を
どれだけ満たしているかを、決定的（ルールベース、LLM不使用）に採点する。

  - has one clear objective        -> score_clear_objective
  - is actionable                  -> score_actionability
  - has a clear outcome            -> score_clear_outcome
  - is not too broad                )
  - is not unnecessarily small      } -> score_granularity
  - retains source traceability    -> score_traceability

（"can be assigned to one or more appropriate members"はPhase 4の範囲外
  = メンバー割り当てをまだ行わないため、ここでは採点しない）

採点は0-5の6段階（`backend/evaluation/schemas/rubric.py`と同じスケール）。
これは`backend/evaluation/`（Phase 2、別のタスク分解パイプラインの出力を
評価するフレームワーク）とは独立した、tasks.json単体を素早く自己点検する
ための軽量なサポート機能として提供する。
"""

from __future__ import annotations

from typing import Dict, List, Tuple

from backend.pipeline.tasks.schema import Task, TaskDocument
from backend.pipeline.tasks.validator import BROAD_KEYWORDS, CONJUNCTION_MARKERS

ACTION_VERBS = [
    "実装する", "作成する", "提出する", "確認する", "検証する", "実施する",
    "テストする", "レビューする", "設計する", "登録する", "修正する", "記載する",
    "整理する", "準備する", "調整する", "デプロイする",
]


def score_clear_objective(task: Task) -> Tuple[int, List[str]]:
    """1つの明確な目的を持つか（複数の目的が束ねられていないか）"""
    issues: List[str] = []
    text = f"{task.title} {task.description}"

    if any(k in text for k in BROAD_KEYWORDS):
        issues.append("システム全体を指す表現があり、単一の目的とは言えない")
        return 0, issues

    verb_count = sum(task.title.count(v) for v in ACTION_VERBS)
    if verb_count >= 2 or any(m in task.title for m in CONJUNCTION_MARKERS):
        issues.append("タイトルに複数の目的が束ねられている可能性がある")
        return 1, issues

    if not task.description:
        issues.append("descriptionが無く、目的が1つに絞られているか判断しづらい")
        return 3, issues

    return 5, issues


def score_actionability(task: Task) -> Tuple[int, List[str]]:
    """着手可能か（明確な行動動詞を持つか）"""
    issues: List[str] = []
    verb_hits = [v for v in ACTION_VERBS if v in task.title]

    if not verb_hits:
        issues.append("行動を表す動詞が見当たらない")
        return 1, issues

    if len(task.title) < 6:
        issues.append("タイトルが短すぎて何をすべきか分かりづらい")
        return 2, issues

    return 5, issues


def score_clear_outcome(task: Task) -> Tuple[int, List[str]]:
    """完了したかどうかを明確に判断できるか（acceptance_criteriaの有無で判定）"""
    issues: List[str] = []
    if not task.acceptance_criteria:
        issues.append("acceptance_criteriaが無く、完了判断の基準が明確でない")
        return 1, issues
    if len(task.acceptance_criteria) == 1:
        return 4, issues
    return 5, issues


def score_granularity(task: Task) -> Tuple[int, List[str]]:
    """広すぎず、不必要に細かすぎないか"""
    issues: List[str] = []
    text = f"{task.title} {task.description}"

    if any(k in text for k in BROAD_KEYWORDS):
        issues.append("広すぎるタスクの可能性がある（システム全体を指す表現）")
        return 0, issues

    if any(m in task.title for m in CONJUNCTION_MARKERS):
        issues.append("複数の作業が1タスクに束ねられている可能性がある")
        return 1, issues

    if len(task.title) > 80:
        issues.append("タイトルが非常に長く、複数の要素を含んでいる可能性がある")
        return 2, issues

    return 5, issues


def score_traceability(task: Task) -> Tuple[int, List[str]]:
    """出典が保持されているか（Requirementから引き継がれたsource_referenceの有無）"""
    issues: List[str] = []
    ref = task.source_reference

    if ref is None or not ref.source_text or not ref.source_text.strip():
        issues.append("出典(source_reference.source_text)が設定されていない")
        return 0, issues

    if not task.requirement_ids:
        issues.append("requirement_idsが空で、どの要求から来たタスクかを追跡できない")
        return 2, issues

    if ref.section:
        return 5, issues
    return 4, issues


def evaluate_task(task: Task) -> Dict[str, object]:
    """1件のタスクを5つの観点で採点する"""
    scores: Dict[str, int] = {}
    issues: List[str] = []

    for name, fn in (
        ("clear_objective", score_clear_objective),
        ("actionability", score_actionability),
        ("clear_outcome", score_clear_outcome),
        ("granularity", score_granularity),
        ("traceability", score_traceability),
    ):
        score, item_issues = fn(task)
        scores[name] = score
        issues += item_issues

    overall = round(sum(scores.values()) / len(scores), 2)
    return {"task_id": task.id, "scores": scores, "overall_score": overall, "issues": issues}


def evaluate_task_document(doc: TaskDocument) -> Dict[str, object]:
    """タスクドキュメント全体を評価する（各タスクの評価 + ドキュメント単位の集計）"""
    per_task = [evaluate_task(t) for t in doc.tasks]
    overall_scores = [e["overall_score"] for e in per_task]
    document_overall = round(sum(overall_scores) / len(overall_scores), 2) if overall_scores else None

    return {
        "document_id": doc.document_id,
        "task_count": len(doc.tasks),
        "needs_review_count": sum(1 for t in doc.tasks if t.needs_review),
        "per_task": per_task,
        "document_overall_score": document_overall,
    }
