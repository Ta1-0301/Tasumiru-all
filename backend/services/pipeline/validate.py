# backend/services/pipeline/validate.py
"""
Stage 7: タスク検証（Task validation）

「LLMの不正な出力を黙って受け入れない」を実装する場所。
1. Pydanticで検証する
2. 失敗したら修復を試みる（LLMに元データとエラー内容を見せて直させる）
3. それでも失敗したら FailedItem として分離する（Taskとして扱わない）

NOTE: 修復プロンプトが source_reference を書き換えてしまうと、出典の非捏造という
      設計上の保証が崩れる。そのため修復後も source_reference と task_id は
      必ず元の（機械的に構築した）値で上書きする。
"""

from __future__ import annotations

import json
from typing import Optional, Tuple

from pydantic import ValidationError

from backend.services.llm import BaseLLMClient
from backend.services.pipeline.llm_json import call_llm_json
from backend.services.pipeline.schema import CandidateTask, FailedItem, Task

_REPAIR_PROMPT = """\
以下のJSONはスキーマ検証に失敗しました。検証エラーの内容を踏まえて、
正しい形式に修正したJSONのみを出力してください。分からない値は null または
"unknown" にしてください。新しい情報を作り出さないでください。

## 元のJSON
{raw_json}

## 検証エラー
{error}

## 期待されるフィールド
title(文字列), description(文字列またはnull),
priority("high"|"medium"|"low"|"unknown"),
estimated_hours(数値またはnull), required_skills(文字列の配列),
acceptance_criteria(文字列の配列またはnull)

出力は修正後のJSONオブジェクトのみ。
"""


async def validate_task(
    candidate: CandidateTask, task_id: str, client: BaseLLMClient
) -> Tuple[Optional[Task], Optional[FailedItem]]:
    raw = candidate.model_dump(mode="json")
    raw["task_id"] = task_id

    try:
        return Task.model_validate(raw), None
    except ValidationError as e:
        repaired = await _attempt_repair(raw, str(e), client)
        if repaired is not None:
            # source_reference / task_id は修復対象外（捏造防止のため必ず元の値で上書きする）
            repaired["source_reference"] = raw.get("source_reference")
            repaired["task_id"] = task_id
            try:
                return Task.model_validate(repaired), None
            except ValidationError as e2:
                return None, FailedItem(raw_data=raw, error=str(e2), stage="validate_after_repair")

        return None, FailedItem(raw_data=raw, error=str(e), stage="validate")


async def _attempt_repair(raw: dict, error: str, client: BaseLLMClient) -> Optional[dict]:
    prompt = _REPAIR_PROMPT.format(
        raw_json=json.dumps(raw, ensure_ascii=False, default=str),
        error=error,
    )
    repaired, _repair_error = await call_llm_json(client, prompt, retries=1)
    return repaired
