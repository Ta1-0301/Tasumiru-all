# backend/evaluation/runners/model_registry.py
"""
評価対象/判定者モデルのレジストリ。

「Model A / Model B / Model C を、モデル固有の評価ロジックを持たずに比較できる」
という要件を実現する部分。`ModelConfig`は設定データにすぎず、
`backend/evaluation/metrics/`・`backend/evaluation/evaluators/`は
`ModelConfig`が何であるかを一切知らない
（`backend.services.llm.BaseLLMClient.complete()`しか呼ばない）。

新しいモデルを比較対象に加えたい場合は、MODEL_REGISTRYに1エントリ追加するだけでよい。
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Dict, Optional

from backend.evaluation.runners.llm_clients import EvaluationAnthropicClient, EvaluationOllamaClient
from backend.services.llm import BaseLLMClient

# NOTE: 本番パイプラインの抽出プロンプト文面(backend/services/pipeline/stages.py)を
# 読み取り専用でインポートする。フィンガープリント計算だけに使い、値の変更は行わない。
from backend.services.pipeline import stages as _prod_stages


@dataclass(frozen=True)
class ModelConfig:
    key: str
    provider: str  # "ollama" | "anthropic"
    model: str
    model_version: Optional[str] = None
    temperature: Optional[float] = None
    notes: Optional[str] = None

    def build_client(self) -> BaseLLMClient:
        if self.provider == "ollama":
            return EvaluationOllamaClient(model=self.model, temperature=self.temperature)
        if self.provider == "anthropic":
            return EvaluationAnthropicClient(model=self.model, temperature=self.temperature)
        raise ValueError(f"未対応のprovider: {self.provider}")


# 3モデルを比較する場合の設定例。
# - model_a: 現行の本番採用モデル（Ollamaローカル推論）
# - model_b: 比較用の例。別サイズのMeta Llamaモデル（要: 対応するOllamaサーバー起動）
# - model_c: 比較用の例。将来のクラウドモデル（要: ANTHROPIC_API_KEY）
#
# 実行するには対応するサーバー/APIキーが必要。エントリの追加・変更をしても
# metrics/evaluators側のコードは一切変更不要（モデル固有の分岐を持たないことが
# このフレームワークの要件）。
MODEL_REGISTRY: Dict[str, ModelConfig] = {
    "model_a": ModelConfig(
        key="model_a",
        provider="ollama",
        model="llama3.1:8b",
        model_version="llama3.1:8b",
        temperature=0.0,
        notes="現行の本番採用モデル（Ollamaローカル推論）",
    ),
    "model_b": ModelConfig(
        key="model_b",
        provider="ollama",
        model="llama3.1:70b",
        model_version="llama3.1:70b",
        temperature=0.0,
        notes="比較用の例: Meta Llama 大サイズ版（要: ローカルOllamaに当該モデルを起動）",
    ),
    "model_c": ModelConfig(
        key="model_c",
        provider="anthropic",
        model="claude-sonnet-5",
        model_version="claude-sonnet-5",
        temperature=0.0,
        notes="比較用の例: クラウドモデル（要: ANTHROPIC_API_KEY）",
    ),
}

# LLM-as-judgeを実行する既定モデル。評価対象モデルと判定者モデルを分けることで、
# 「生成者と判定者が同一モデルである場合の自己評価バイアス」を軽減できる
# （TASK_EXTRACTION_EVALUATION.md §6参照）。
DEFAULT_JUDGE_MODEL_KEY = "model_a"


def compute_prompt_version() -> str:
    """本番パイプラインの抽出プロンプト文面から再現性フィンガープリントを計算する。

    プロンプトが1文字でも変わればこの値も変わるため、「どのバージョンの
    プロンプトで生成した結果か」を後から一意に確認できる。評価コードは
    この値を記録するだけで、本番プロンプト自体には一切手を加えない。
    """
    fingerprint_source = _prod_stages._REQUIREMENT_PROMPT + _prod_stages._CANDIDATE_TASK_PROMPT
    return hashlib.sha256(fingerprint_source.encode("utf-8")).hexdigest()[:12]
