# backend/tests/test_rag_embeddings.py
"""backend/services/rag/embeddings.py の単体テスト。

実際のOllamaは一切呼ばない。BaseEmbeddingClientを実装したフェイク
クライアントで、document/query prefixの分岐だけを検証する。
"""

import pytest

from backend.services.rag.embeddings import BaseEmbeddingClient


class FakeEmbeddingClient(BaseEmbeddingClient):
    """テスト用: 呼び出された(text, is_query)をそのまま記録し、
    テキストの文字コード列を決定論的な小さいベクトルとして返す。
    """

    def __init__(self):
        self.model = "fake-embedding-v1"
        self.calls: list[tuple[str, bool]] = []

    async def embed(self, text: str, *, is_query: bool = False) -> list[float]:
        self.calls.append((text, is_query))
        # 決定論的なフェイクベクトル（実際のEmbeddingモデルは呼ばない）
        return [float(ord(c) % 7) for c in text[:8]] or [0.0]


@pytest.mark.asyncio
async def test_embed_document_records_is_query_false():
    client = FakeEmbeddingClient()
    await client.embed("仕様書の本文", is_query=False)
    assert client.calls == [("仕様書の本文", False)]


@pytest.mark.asyncio
async def test_embed_query_records_is_query_true():
    client = FakeEmbeddingClient()
    await client.embed("ログイン画面とは", is_query=True)
    assert client.calls == [("ログイン画面とは", True)]


@pytest.mark.asyncio
async def test_embed_is_deterministic_for_same_text():
    client = FakeEmbeddingClient()
    v1 = await client.embed("同じテキスト", is_query=False)
    v2 = await client.embed("同じテキスト", is_query=False)
    assert v1 == v2


def test_default_embedding_model_env_var(monkeypatch):
    """OLLAMA_EMBEDDING_MODELが未設定なら既定値'nomic-embed-text'になる
    （モデル名をハードコードしていないことの確認：モジュール再import時に
    環境変数を読み直す挙動を確認する）。
    """
    monkeypatch.delenv("OLLAMA_EMBEDDING_MODEL", raising=False)
    import importlib

    import backend.services.rag.embeddings as embeddings_module

    importlib.reload(embeddings_module)
    try:
        assert embeddings_module.OLLAMA_EMBEDDING_MODEL == "nomic-embed-text"
    finally:
        importlib.reload(embeddings_module)


def test_embedding_model_overridable_via_env_var(monkeypatch):
    monkeypatch.setenv("OLLAMA_EMBEDDING_MODEL", "custom-embed-model")
    import importlib

    import backend.services.rag.embeddings as embeddings_module

    importlib.reload(embeddings_module)
    try:
        assert embeddings_module.OLLAMA_EMBEDDING_MODEL == "custom-embed-model"
    finally:
        monkeypatch.delenv("OLLAMA_EMBEDDING_MODEL", raising=False)
        importlib.reload(embeddings_module)
