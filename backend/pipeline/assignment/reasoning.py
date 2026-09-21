# backend/pipeline/assignment/reasoning.py
"""
Step 3: LLM Reasoning（任意）。

Step 1（フィルタリング）・Step 2（スコアリング）で既に確定した上位候補
一覧について、LLMに補足説明を依頼する。**LLMが返せるのは`reasons`と
`warnings`という文字列リストだけ** —
`recommended_member_id`やスコア、候補者一覧そのものを書き換える経路は
存在しない。これにより「LLMは最終判断を単独で行わない」
「LLMはハード制約を回避できない」という要件を構造的に満たす。

`backend.services.llm.BaseLLMClient`だけに依存する（`complete()`しか呼ばない）。
プロバイダー固有の処理・モデル名は一切ハードコードしない。
"""

from __future__ import annotations

from typing import List, Tuple

from backend.pipeline.assignment.schema import AssignmentTask, CandidateScore
from backend.services.llm import BaseLLMClient
from backend.services.pipeline.llm_json import call_llm_json

TOP_N_FOR_REASONING = 3

_REASONING_PROMPT = """\
あなたはプロジェクト管理のアドバイザーです。以下のタスクに対する上位候補者
（すでに決定的なスコアリングで算出済み）について、次のことだけを行ってください:

- 候補者間の違いを説明する
- スコアだけでは見えにくい考慮事項があれば指摘する
- 判断が難しい（僅差である等）場合はその旨を明記する

## 重要な制約
- あなたは誰を割り当てるかを決定する立場にはありません
  （最終判断は既に決定的なスコアリングで確定しています）
- 候補者一覧に無いメンバーを提案してはいけません
- 一覧の候補者はすべて既にハード制約（必要スキル・稼働可否・工数上限・
  明示的な制約）を満たしています。それを覆すような発言をしないこと

## タスク
{task_title}

## 候補者（スコア降順）
{candidates}

出力は必ず以下のJSON形式のみ。説明文やMarkdownは不要です。

{{"reasons": ["短い説明"], "warnings": ["短い注意事項（無ければ空配列）"]}}
"""


def _format_candidates(candidates: List[CandidateScore]) -> str:
    return "\n".join(
        f"- {c.member_id}: score={c.score}, skill_match={c.skill_match}, "
        f"workload={c.workload_score}, experience={c.experience_score}, "
        f"availability={c.availability_score}"
        for c in candidates
    )


async def generate_llm_reasoning(
    task: AssignmentTask, candidates: List[CandidateScore], client: BaseLLMClient
) -> Tuple[List[str], List[str]]:
    """上位候補についてのLLMによる補足説明・注意事項を生成する。

    戻り値は (追加のreasons, 追加のwarnings)。呼び出し側(runner.py)は
    これらをそのまま既存のreasons/warningsに追記するだけで、
    `recommended_member_id`や`score`には一切影響しない。
    """
    if not candidates:
        return [], []

    top = candidates[:TOP_N_FOR_REASONING]
    prompt = _REASONING_PROMPT.format(
        task_title=task.title or task.task_id,
        candidates=_format_candidates(top),
    )
    result, error = await call_llm_json(client, prompt)

    if result is None:
        return [], [f"LLMによる補足説明の生成に失敗しました: {error}"]

    raw_reasons = result.get("reasons")
    raw_warnings = result.get("warnings")
    reasons = [str(r) for r in raw_reasons] if isinstance(raw_reasons, list) else []
    warnings = [str(w) for w in raw_warnings] if isinstance(raw_warnings, list) else []
    return reasons, warnings
