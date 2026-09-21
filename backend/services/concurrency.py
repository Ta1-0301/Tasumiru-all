# backend/services/concurrency.py
"""
Part 3: Safe Parallelization。

独立した非同期処理を、設定可能な最大同時実行数で走らせるための汎用ヘルパー。
特定のパイプラインステージやLLMプロバイダーには依存しない。

**同時実行数の既定値は1（＝現在と完全に同じ逐次実行）。** ローカルの単一
ワーカーOllamaに対して並列呼び出しを行うと、かえって遅くなる可能性がある
という依頼の警告に対応し、実測なしに積極的な並列度をデフォルトにはしない
（"Do not hardcode aggressive concurrency"への対応）。並列度を上げたい場合は
`OLLAMA_MAX_CONCURRENCY`環境変数で明示的に設定する。
"""

from __future__ import annotations

import asyncio
import os
from typing import Awaitable, Callable, List, TypeVar

T = TypeVar("T")

DEFAULT_MAX_CONCURRENCY = 1


def get_max_concurrency(env_var: str = "OLLAMA_MAX_CONCURRENCY", default: int = DEFAULT_MAX_CONCURRENCY) -> int:
    """環境変数から最大同時実行数を読む。未設定/不正な値は保守的な既定値にフォールバックする。"""
    raw = os.environ.get(env_var)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return value if value >= 1 else default


async def gather_with_concurrency(
    factories: List[Callable[[], Awaitable[T]]], max_concurrency: int
) -> List[T]:
    """`factories`（各要素は呼び出すとcoroutineを返す関数）を、最大`max_concurrency`
    件まで同時に実行する。結果は入力順を保持する（`asyncio.gather`と同じ契約）。

    coroutineオブジェクトそのものではなく「呼び出すとcoroutineを作る関数」を
    受け取る設計にしているのは、セマフォ獲得前にcoroutineが生成される
    （＝実行開始してしまう）ことを避けるため。
    """
    if max_concurrency < 1:
        max_concurrency = 1
    semaphore = asyncio.Semaphore(max_concurrency)

    async def _run(factory: Callable[[], Awaitable[T]]) -> T:
        async with semaphore:
            return await factory()

    return await asyncio.gather(*(_run(f) for f in factories))
