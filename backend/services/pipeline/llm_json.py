# backend/services/pipeline/llm_json.py
"""
LLMにJSON出力を要求し、パースするための共通ヘルパー。
プロバイダー固有の挙動（Ollamaのformat="json"等）は backend.services.llm 側に
閉じ込め、ここでは BaseLLMClient.complete() のみを使う（抽象化を壊さない）。

「不正なLLM出力を黙って受け入れない」を徹底するため、パースに失敗したら
リトライし、それでも失敗したら None を返して呼び出し側に判断させる
（勝手にNoneを既定のタスクとして扱ったりしない）。
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, Optional

from fastapi import HTTPException

from backend.services.llm import BaseLLMClient

MAX_RETRIES = 2


def _strip_code_fence(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
    return text.strip()


def _extract_json_object(text: str) -> str:
    """テキスト中に前置き等が混ざっていても、最初の { ... } または [ ... ] を抜き出す"""
    text = _strip_code_fence(text)
    match = re.search(r"(\{.*\}|\[.*\])", text, re.DOTALL)
    return match.group(1) if match else text


async def call_llm_json(
    client: BaseLLMClient, prompt: str, *, retries: int = MAX_RETRIES
) -> tuple[Optional[Dict[str, Any]], Optional[str]]:
    """
    LLMにJSON出力を要求し、dictとしてパースする。
    戻り値は (パース結果 または None, 失敗理由の文字列 または None)。

    診断のため、失敗理由を「タイムアウト/通信エラー」「JSON解析エラー」を
    区別して呼び出し側に返す（実機での原因切り分けに使うため、握りつぶさない）。

    NOTE: complete()が投げるHTTPException（タイムアウト等の通信エラー）も
          ここで捕捉してリトライ対象にする。実機のOllama（単一ワーカーで推論を
          直列処理するローカルLLM）で実際にタイムアウトが発生することを確認しており、
          これを無視して例外を伝播させるとパイプライン全体がクラッシュしてしまう。
          1件のステージ呼び出しの失敗は、そのステージの失敗として記録されるべきであり、
          リクエスト全体を巻き込むべきではない。
    """
    last_error: Optional[str] = None

    for attempt in range(retries + 1):
        try:
            raw_text = await client.complete(prompt, json_mode=True)
            parsed = json.loads(_extract_json_object(raw_text))
            if isinstance(parsed, dict):
                return parsed, None
            # 配列が返ってきた場合は最初の要素を採用する（1要求→1タスクの契約を守るため、
            # 万一LLMが配列で返してもここで吸収する。ただしトップレベルが配列だった、
            # という事実は呼び出し側でログできるよう例外にはしない）
            if isinstance(parsed, list) and parsed and isinstance(parsed[0], dict):
                return parsed[0], None
            last_error = f"予期しないJSON構造: {type(parsed).__name__}"
        except (json.JSONDecodeError, ValueError) as e:
            last_error = f"JSON解析エラー: {e}"
        except HTTPException as e:
            last_error = f"通信エラー: {e.detail}"

    return None, last_error
