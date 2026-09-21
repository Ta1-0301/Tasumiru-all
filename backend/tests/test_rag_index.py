# backend/tests/test_rag_index.py
"""backend/services/rag/index.py の単体テスト。

・chunk化は既存のdecompose_document()をそのまま再利用していること
・chunkのmetadata(chunk_id/heading/text)がEmbeddedChunkに保持されること
・同一document_textの再構築はキャッシュヒットしてEmbedding APIを呼び直さないこと
・異なるdocument_textはキャッシュミスして再Embeddingすること
を検証する。実際のOllamaは一切呼ばない。
"""

import pytest

from backend.services.pipeline.structure import decompose_document
from backend.services.rag.embeddings import BaseEmbeddingClient
from backend.services.rag.index import (
    build_spec_index,
    chunk_document,
    document_hash,
    load_cached_index,
)


class FakeEmbeddingClient(BaseEmbeddingClient):
    def __init__(self):
        self.model = "fake-embedding-v1"
        self.calls: list[str] = []

    async def embed(self, text: str, *, is_query: bool = False) -> list[float]:
        self.calls.append(text)
        return [float(len(text) % 5), 1.0, 0.0]


DOC_TEXT = "第1条(目的)\nこのシステムはタスク管理を行う。\n\n第2条(範囲)\nログイン機能を含む。"


@pytest.mark.asyncio
async def test_build_spec_index_reuses_existing_chunking_logic(tmp_path):
    """新しいchunkingロジックを作らず、既存のdecompose_document()の
    出力とchunk_idが一致することを確認する。"""
    expected_chunks = decompose_document(DOC_TEXT)
    client = FakeEmbeddingClient()

    index = await build_spec_index("doc_1", DOC_TEXT, client, cache_dir=tmp_path)

    assert [c.chunk_id for c in index.chunks] == [c.chunk_id for c in expected_chunks]
    assert chunk_document(DOC_TEXT) == expected_chunks


@pytest.mark.asyncio
async def test_build_spec_index_preserves_chunk_metadata(tmp_path):
    client = FakeEmbeddingClient()
    index = await build_spec_index("doc_1", DOC_TEXT, client, cache_dir=tmp_path)

    expected_chunks = decompose_document(DOC_TEXT)
    for embedded, original in zip(index.chunks, expected_chunks):
        assert embedded.text == original.text  # 実在の部分文字列がそのまま保持される
        assert embedded.heading == original.heading
        assert len(embedded.vector) > 0


@pytest.mark.asyncio
async def test_build_spec_index_cache_hit_skips_reembedding(tmp_path):
    client = FakeEmbeddingClient()
    await build_spec_index("doc_1", DOC_TEXT, client, cache_dir=tmp_path)
    calls_after_first_build = len(client.calls)
    assert calls_after_first_build > 0

    await build_spec_index("doc_1", DOC_TEXT, client, cache_dir=tmp_path)
    assert len(client.calls) == calls_after_first_build  # 2回目はEmbedding APIを呼ばない


@pytest.mark.asyncio
async def test_build_spec_index_cache_miss_for_different_text(tmp_path):
    client = FakeEmbeddingClient()
    await build_spec_index("doc_1", DOC_TEXT, client, cache_dir=tmp_path)
    calls_after_first = len(client.calls)

    await build_spec_index("doc_1", DOC_TEXT + "\n\n第3条(追加)\n追加の条項。", client, cache_dir=tmp_path)
    assert len(client.calls) > calls_after_first  # 異なるテキストは再Embeddingされる


@pytest.mark.asyncio
async def test_build_spec_index_persists_to_cache_dir(tmp_path):
    client = FakeEmbeddingClient()
    index = await build_spec_index("doc_1", DOC_TEXT, client, cache_dir=tmp_path)

    cached = load_cached_index(document_hash(DOC_TEXT), cache_dir=tmp_path)
    assert cached is not None
    assert cached.document_hash == index.document_hash
    assert len(cached.chunks) == len(index.chunks)


def test_document_hash_is_deterministic_and_content_sensitive():
    assert document_hash("同じテキスト") == document_hash("同じテキスト")
    assert document_hash("テキストA") != document_hash("テキストB")


@pytest.mark.asyncio
async def test_build_spec_index_empty_document_returns_empty_index(tmp_path):
    client = FakeEmbeddingClient()
    index = await build_spec_index("doc_1", "", client, cache_dir=tmp_path)
    assert index.chunks == []
    assert client.calls == []
