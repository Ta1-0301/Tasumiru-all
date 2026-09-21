# backend/jobs/timing.py
"""
Phase 10 STEP 9: 構造化タイミングログ。

既存のPhase 3-9のコード(extractor.py/decomposer.py/proposer.py/reasoning.py/
services/llm.py)は一切変更しない。かわりに:

  - `pipeline_stage(...)`: 各ステージ(requirements/tasks/...)の開始・終了を
    ログするコンテキストマネージャ。ジョブオーケストレーション層
    (backend/jobs/manager.py)がステージ関数を呼ぶ箇所を囲むだけ。
  - `TimingLLMClient`: 既存の`BaseLLMClient`をそのまま委譲するラッパー。
    `complete()`の呼び出しだけを計測してログに残し、実際の処理
    （プロンプト内容・レスポンス内容含む）には一切手を加えない。
  - `TimingEmbeddingClient`: 実験的RAG機能用。`BaseEmbeddingClient`版の
    `TimingLLMClient`。呼び出し回数・累積所要時間をRAG導入前後の性能比較
    (STEP 18)に使えるよう`call_count`/`total_duration`として保持する。

**仕様書の内容やプロンプト全文はログに一切出力しない**（依頼の
"Do NOT log sensitive document contents or full prompts"に対応）。
記録するのはステージ名・モデル名・開始/終了時刻・所要時間・成否のみ。
"""

from __future__ import annotations

import logging
import time
from contextlib import contextmanager
from typing import Iterator, List, Optional

from backend.services.llm import BaseLLMClient
from backend.services.rag.embeddings import BaseEmbeddingClient

logger = logging.getLogger("tasumiru.pipeline")


@contextmanager
def pipeline_stage(stage: str) -> Iterator[None]:
    """1つのパイプラインステージ全体の所要時間を計測してログに残す。

    例:
        with pipeline_stage("requirements"):
            req_doc = await run_requirements_pipeline(...)

    ログ例:
        [PIPELINE] requirements start
        [PIPELINE] requirements completed duration=43.10s
    """
    logger.info("[PIPELINE] %s start", stage)
    start = time.monotonic()
    try:
        yield
    except Exception:
        duration = time.monotonic() - start
        logger.warning("[PIPELINE] %s failed duration=%.2fs", stage, duration)
        raise
    else:
        duration = time.monotonic() - start
        logger.info("[PIPELINE] %s completed duration=%.2fs", stage, duration)


class TimingLLMClient(BaseLLMClient):
    """既存のBaseLLMClient実装を透過的にラップし、`complete()`呼び出し
    ごとにモデル名・所要時間だけをログに残す。プロンプト・レスポンスの
    内容は一切ログしない。実際の呼び出しは`inner`にそのまま委譲するため、
    既存のLLMクライアント実装(backend/services/llm.py)は無変更のまま使える。
    """

    def __init__(self, inner: BaseLLMClient, stage: str):
        self._inner = inner
        self._stage = stage
        # 既存コード(backend/pipeline/*/runner.py)は client.model を読んで
        # ReproducibilityRecord等に記録するため、透過的に転送する
        self.model = getattr(inner, "model", None)
        # RAG導入前後の性能比較(STEP 18)用: 呼び出し回数・累積所要時間
        self.call_count: int = 0
        self.total_duration: float = 0.0

    async def complete(self, prompt: str, *, json_mode: bool = False) -> str:
        model_name = getattr(self._inner, "model", None) or "unknown"
        logger.info("[LLM] %s start model=%s", self._stage, model_name)
        start = time.monotonic()
        try:
            result = await self._inner.complete(prompt, json_mode=json_mode)
        except Exception as e:
            duration = time.monotonic() - start
            self.call_count += 1
            self.total_duration += duration
            logger.warning(
                "[LLM] %s failed model=%s duration=%.2fs error=%s",
                self._stage, model_name, duration, type(e).__name__,
            )
            raise
        else:
            duration = time.monotonic() - start
            self.call_count += 1
            self.total_duration += duration
            logger.info(
                "[LLM] %s completed model=%s duration=%.2fs",
                self._stage, model_name, duration,
            )
            return result


def timed_client(inner: BaseLLMClient, stage: str) -> TimingLLMClient:
    """`inner`をそのステージ用のタイミング計測クライアントでラップする。"""
    return TimingLLMClient(inner, stage)


class TimingEmbeddingClient(BaseEmbeddingClient):
    """`TimingLLMClient`のEmbedding版。既存の`BaseEmbeddingClient`実装を
    透過的にラップし、`embed()`呼び出しごとの所要時間・累積回数だけを記録する。
    テキスト内容(仕様書本文・query文)は一切ログしない。
    """

    def __init__(self, inner: BaseEmbeddingClient, stage: str = "embedding"):
        self._inner = inner
        self._stage = stage
        self.model = getattr(inner, "model", None)
        self.call_count: int = 0
        self.total_duration: float = 0.0

    async def embed(self, text: str, *, is_query: bool = False) -> List[float]:
        model_name = getattr(self._inner, "model", None) or "unknown"
        kind = "query" if is_query else "document"
        logger.info("[EMBEDDING] %s start model=%s kind=%s", self._stage, model_name, kind)
        start = time.monotonic()
        try:
            result = await self._inner.embed(text, is_query=is_query)
        except Exception as e:
            duration = time.monotonic() - start
            self.call_count += 1
            self.total_duration += duration
            logger.warning(
                "[EMBEDDING] %s failed model=%s duration=%.2fs error=%s",
                self._stage, model_name, duration, type(e).__name__,
            )
            raise
        else:
            duration = time.monotonic() - start
            self.call_count += 1
            self.total_duration += duration
            logger.info(
                "[EMBEDDING] %s completed model=%s duration=%.2fs",
                self._stage, model_name, duration,
            )
            return result


def timed_embedding_client(inner: BaseEmbeddingClient, stage: str = "embedding") -> TimingEmbeddingClient:
    """`inner`をそのステージ用のタイミング計測Embeddingクライアントでラップする。"""
    return TimingEmbeddingClient(inner, stage)
