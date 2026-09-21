# backend/tests/test_evaluation_registry.py
"""
backend/evaluation/runners/model_registry.py の単体テスト。

- MODEL_REGISTRY の各エントリからクライアントを構築できること
  （ネットワーク呼び出しはしない。construct時にHTTPリクエストは飛ばない）
- compute_prompt_version() が本番プロンプト文面に対して決定的であること
  （再現性の要件。同じプロンプトなら常に同じ値になる）
"""

from backend.evaluation.runners.llm_clients import EvaluationOllamaClient
from backend.evaluation.runners.model_registry import MODEL_REGISTRY, compute_prompt_version


def test_model_registry_has_three_example_models():
    assert {"model_a", "model_b", "model_c"} <= set(MODEL_REGISTRY)


def test_ollama_model_config_builds_client_without_network_call():
    config = MODEL_REGISTRY["model_a"]
    client = config.build_client()
    assert isinstance(client, EvaluationOllamaClient)
    assert client.model == config.model
    assert client.temperature == config.temperature


def test_compute_prompt_version_is_deterministic():
    assert compute_prompt_version() == compute_prompt_version()


def test_compute_prompt_version_is_a_short_hex_fingerprint():
    version = compute_prompt_version()
    assert len(version) == 12
    int(version, 16)  # 16進数として解釈できること
