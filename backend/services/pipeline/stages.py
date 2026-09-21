# backend/services/pipeline/stages.py
"""
Stage 2-6: 要求抽出・候補タスク化・正規化・重複検出。

要求抽出(identify_requirements)と候補タスク化(extract_candidate_task)は
LLMを使うが、必ず backend.services.llm.BaseLLMClient.complete() 経由で呼ぶため、
プロバイダー固有の挙動には依存しない。

正規化(normalize_task)と重複検出(detect_duplicates)は決定的な処理のみで、
LLMを一切使わない。
"""

from __future__ import annotations

import difflib
import re
from typing import List, Optional, Tuple

from backend.services.llm import BaseLLMClient
from backend.services.pipeline.llm_json import call_llm_json
from backend.services.pipeline.schema import (
    CandidateTask,
    DocumentChunk,
    Priority,
    Requirement,
    RequirementType,
    SourceReference,
)

_VALID_REQUIREMENT_TYPES = {t.value for t in RequirementType}
_VALID_PRIORITIES = {p.value for p in Priority}

_ACTION_VERBS = [
    "実装する", "作成する", "提出する", "確認する", "検証する", "実施する",
    "テストする", "レビューする", "設計する", "登録する", "修正する", "記載する",
    "整理する", "準備する", "調整する", "指定する", "アサインする", "デプロイする",
]

_REQUIREMENT_PROMPT = """\
あなたはプロジェクト管理の専門家です。以下は仕様書本文の一区画です。
この区画から、実行可能な「要求事項」を過不足なく書き出してください。

ルール:
- 1件の要求事項には単一の内容だけを含めること（複数の作業を1件にまとめない）
- 区画に書かれていないことを推測で追加しないこと
- 要求事項が無ければ空配列を返すこと
- requirement_type は次のいずれか: explicit(明示的指示) / deadline(締切) /
  deliverable(提出物) / conditional(条件付き) / implicit(暗黙の準備) /
  prohibition(禁止事項からの逆算)

## 区画の内容
{chunk_text}

出力は必ず以下のJSON形式のみ。説明文やMarkdownは不要です。

{{"requirements": [{{"text": "要求事項の短い説明", "requirement_type": "explicit"}}]}}
"""

_CANDIDATE_TASK_PROMPT = """\
あなたはプロジェクト管理の専門家です。以下の「要求事項」を、実行可能な1件の
タスクに変換してください。

## 良い粒度の例
- 悪い例（広すぎる）: "システムを開発する"
- 悪い例（細かすぎる）: "ログインボタンの色を決める"
- 良い例: "ログインAPIを実装する"

## 要求事項（種別: {requirement_type}）
{requirement_text}

## 元の文脈（参考。ここから新しい要求を作らないこと）
{chunk_text}

以下のJSON形式のみで出力してください。確信が持てない項目は null または
"unknown" にしてください。絶対に情報を捏造しないでください。

{{
  "title": "動詞で終わる具体的なタスク名",
  "description": "何をどう完了させるかの短い説明",
  "priority": "high または medium または low または unknown",
  "estimated_hours": 数値または null,
  "required_skills": ["スキル名"] または ["unknown"],
  "acceptance_criteria": ["完了と判断できる条件"] または null
}}
"""


async def identify_requirements(
    chunk: DocumentChunk, client: BaseLLMClient
) -> Tuple[List[Requirement], Optional[str]]:
    """1チャンクから要求事項を抽出する。戻り値は (要求事項一覧, エラーメッセージ)"""
    prompt = _REQUIREMENT_PROMPT.format(chunk_text=chunk.text)
    result, error = await call_llm_json(client, prompt)

    if result is None:
        return [], f"chunk={chunk.chunk_id}: {error}"

    raw_list = result.get("requirements")
    if not isinstance(raw_list, list):
        return [], f"chunk={chunk.chunk_id}: 'requirements'が配列ではない: {result!r}"

    requirements: List[Requirement] = []
    for i, item in enumerate(raw_list):
        if not isinstance(item, dict) or not item.get("text"):
            continue
        req_type = item.get("requirement_type")
        if req_type not in _VALID_REQUIREMENT_TYPES:
            req_type = RequirementType.implicit.value  # 不明な種別は「暗黙」に丸める
        requirements.append(Requirement(
            requirement_id=f"{chunk.chunk_id}-r{i + 1}",
            chunk_id=chunk.chunk_id,
            text=str(item["text"]).strip(),
            requirement_type=RequirementType(req_type),
        ))

    return requirements, None


async def extract_candidate_task(
    requirement: Requirement, chunk: DocumentChunk, client: BaseLLMClient
) -> Tuple[Optional[CandidateTask], Optional[str]]:
    """1件の要求事項から候補タスクを1件生成する。戻り値は (候補タスク, エラーメッセージ)"""
    prompt = _CANDIDATE_TASK_PROMPT.format(
        requirement_type=requirement.requirement_type.value,
        requirement_text=requirement.text,
        chunk_text=chunk.text,
    )
    result, error = await call_llm_json(client, prompt)

    if result is None:
        return None, f"requirement={requirement.requirement_id}: {error}"
    if not result.get("title"):
        return None, f"requirement={requirement.requirement_id}: LLM出力にtitleが含まれていない: {result!r}"

    priority_raw = result.get("priority")
    priority = Priority(priority_raw) if priority_raw in _VALID_PRIORITIES else Priority.unknown

    estimated_hours = result.get("estimated_hours")
    if not isinstance(estimated_hours, (int, float)):
        estimated_hours = None

    required_skills = result.get("required_skills")
    if not isinstance(required_skills, list) or not required_skills:
        required_skills = ["unknown"]
    else:
        required_skills = [str(s) for s in required_skills]

    acceptance_criteria = result.get("acceptance_criteria")
    if not isinstance(acceptance_criteria, list) or not acceptance_criteria:
        acceptance_criteria = None
    else:
        acceptance_criteria = [str(c) for c in acceptance_criteria]

    # source_referenceはLLMには書かせず、必ずchunkの実データから機械的に組み立てる
    source_reference = SourceReference(chunk_id=chunk.chunk_id, excerpt=chunk.text)

    candidate = CandidateTask(
        title=str(result["title"]).strip(),
        description=(str(result.get("description")).strip() if result.get("description") else None),
        priority=priority,
        estimated_hours=float(estimated_hours) if estimated_hours is not None else None,
        required_skills=required_skills,
        source_reference=source_reference,
        acceptance_criteria=acceptance_criteria,
    )
    return candidate, None


def normalize_task(candidate: CandidateTask) -> CandidateTask:
    """決定的な正規化: 型の補正・粒度チェック・欠損値のunknown化"""
    reasons: List[str] = []

    title = (candidate.title or "").strip()
    if not title:
        title = "(タイトル不明)"
        reasons.append("タイトルが空だったため要確認")

    if candidate.estimated_hours is not None and not (0 < candidate.estimated_hours <= 500):
        reasons.append(f"estimated_hoursが非現実的な値 ({candidate.estimated_hours}) のためnull化")
        candidate = candidate.model_copy(update={"estimated_hours": None})

    verb_hits = sum(title.count(v) for v in _ACTION_VERBS)
    has_conjunction = any(c in title for c in ["、また", "および", "かつ", "、そして"])
    if verb_hits >= 2 or has_conjunction:
        reasons.append("複数の作業が1タスクに束ねられている可能性（粒度が広すぎる）")

    if not re.search(r"(する|すること)$", title) and not any(v in title for v in _ACTION_VERBS):
        reasons.append("行動を表す動詞が見当たらない")

    if candidate.source_reference is None:
        reasons.append("出典が特定できないため要レビュー")

    needs_review = bool(reasons) or candidate.source_reference is None
    review_reason = "; ".join(reasons) if reasons else None

    return candidate.model_copy(update={
        "title": title,
        "needs_review": needs_review,
        "review_reason": review_reason,
    })


def detect_duplicates(
    tasks: List[CandidateTask], threshold: float = 0.7
) -> Tuple[List[CandidateTask], List[str]]:
    """タイトルの類似度が高いタスクを重複とみなし、情報量が多い方を残す"""
    if not tasks:
        return [], []

    def _completeness(t: CandidateTask) -> int:
        score = 0
        score += 1 if t.description else 0
        score += 1 if t.estimated_hours is not None else 0
        score += 1 if t.required_skills and t.required_skills != ["unknown"] else 0
        score += 1 if t.acceptance_criteria else 0
        return score

    kept: List[CandidateTask] = []
    dropped_titles: List[str] = []

    for task in tasks:
        duplicate_of_idx = None
        for i, existing in enumerate(kept):
            ratio = difflib.SequenceMatcher(None, task.title, existing.title).ratio()
            if ratio >= threshold:
                duplicate_of_idx = i
                break

        if duplicate_of_idx is None:
            kept.append(task)
            continue

        existing = kept[duplicate_of_idx]
        if _completeness(task) > _completeness(existing):
            kept[duplicate_of_idx] = task
            dropped_titles.append(existing.title)
        else:
            dropped_titles.append(task.title)

    return kept, dropped_titles
