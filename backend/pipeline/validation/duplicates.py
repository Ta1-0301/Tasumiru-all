# backend/pipeline/validation/duplicates.py
"""
CHECK 2: Duplicates。

決定的な文字列類似度(difflib)でタスクの重複候補を検出する
（"Use deterministic similarity where possible"）。LLMは、その候補が
本当に意味的な重複かどうかを検証する目的でのみ、任意で使える
（"LLM may be used for semantic verification"）。

**重複候補を自動で削除することはない。** LLM検証の結果が「重複ではない」
だったとしても、候補をレポートから取り除いたりはしない
——`method`と`reason`に検証結果を追記するだけで、常にレビュー対象として
残す（"Do not automatically delete duplicates. Mark them for review."）。
"""

from __future__ import annotations

import difflib
from typing import Dict, List, Optional

from backend.pipeline.tasks.schema import Task
from backend.pipeline.validation.schema import DuplicateTaskGroup
from backend.services.concurrency import gather_with_concurrency, get_max_concurrency
from backend.services.llm import BaseLLMClient
from backend.services.pipeline.llm_json import call_llm_json

DEFAULT_SIMILARITY_THRESHOLD = 0.7

_VERIFICATION_PROMPT = """\
以下の2つのタスクは、タイトルの文字列としては似ていますが、
実際に同じ作業を指す重複タスクかどうかを判定してください。

## タスクA
{title_a}
{description_a}

## タスクB
{title_b}
{description_b}

出力は必ず以下のJSON形式のみ。

{{"duplicate": true または false, "explanation": "短い理由"}}
"""


def find_duplicate_candidates(
    tasks: List[Task], threshold: float = DEFAULT_SIMILARITY_THRESHOLD
) -> List[DuplicateTaskGroup]:
    """タイトルの類似度が高いタスクの組を、決定的に重複候補として検出する"""
    groups: List[DuplicateTaskGroup] = []
    for i in range(len(tasks)):
        for j in range(i + 1, len(tasks)):
            ratio = difflib.SequenceMatcher(None, tasks[i].title, tasks[j].title).ratio()
            if ratio >= threshold:
                groups.append(DuplicateTaskGroup(
                    task_ids=[tasks[i].id, tasks[j].id],
                    similarity=round(ratio, 3),
                    method="rule",
                    reason=f"タイトルの類似度が高い（{ratio:.2f}）",
                ))
    return groups


async def verify_duplicate_with_llm(
    task_a: Task, task_b: Task, client: BaseLLMClient
) -> Optional[bool]:
    """1組の重複候補について、LLMに意味的な重複かどうかを確認させる。

    戻り値は True(重複)/False(重複ではない)/None(判定に失敗)。
    呼び出し側はこの結果でレポートからの削除を行わない
    （このモジュールのdocstring参照）。
    """
    prompt = _VERIFICATION_PROMPT.format(
        title_a=task_a.title, description_a=task_a.description or "(説明なし)",
        title_b=task_b.title, description_b=task_b.description or "(説明なし)",
    )
    result, error = await call_llm_json(client, prompt)
    if result is None or "duplicate" not in result or not isinstance(result["duplicate"], bool):
        return None
    return result["duplicate"]


async def verify_duplicates_with_llm(
    tasks_by_id: Dict[str, Task],
    candidates: List[DuplicateTaskGroup],
    client: BaseLLMClient,
) -> List[DuplicateTaskGroup]:
    """決定的に見つかった重複候補すべてをLLMで検証し、method/reasonを更新した
    新しいリストを返す（候補の削除・追加は一切行わない。件数は常に一致する）。
    """
    # Part 3: 候補の組ごとのLLM検証は互いに独立している（前の組の判定を
    # 参照しない）ため、安全に並列化できる。既定値1（逐次実行のまま）・
    # 同じOLLAMA_MAX_CONCURRENCYで制御する。
    async def _verify_one(group: DuplicateTaskGroup) -> DuplicateTaskGroup:
        if len(group.task_ids) != 2:
            return group

        task_a = tasks_by_id.get(group.task_ids[0])
        task_b = tasks_by_id.get(group.task_ids[1])
        if task_a is None or task_b is None:
            return group

        is_duplicate = await verify_duplicate_with_llm(task_a, task_b, client)
        if is_duplicate is None:
            note = "LLM検証: 判定に失敗しました"
        elif is_duplicate:
            note = "LLM検証: 意味的にも重複の可能性が高いと判定"
        else:
            note = "LLM検証: タイトルは似ていますが、内容は異なる可能性があると判定（引き続きレビュー対象として保持）"

        return group.model_copy(update={
            "method": "hybrid",
            "reason": f"{group.reason} / {note}",
        })

    max_concurrency = get_max_concurrency()
    return await gather_with_concurrency(
        [(lambda g=group: _verify_one(g)) for group in candidates],
        max_concurrency,
    )
