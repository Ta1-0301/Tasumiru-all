# backend/tests/test_rag_search.py
"""backend/services/rag/search.py の単体テスト。

既存のTF-IDF skill matching(backend/services/skill_matching.py)とは完全に別の
コードパスであることを前提に、Embeddingベクトル同士のCosine Similarityによる
検索だけを検証する。出典(page/section)は常に実在のchunk metadataから返され、
存在しないpage/sectionを生成しないことを重点的に確認する。
"""

import math

import pytest

from backend.services.rag.embeddings import BaseEmbeddingClient
from backend.services.rag.schema import EmbeddedChunk, SpecIndex
from backend.services.rag.search import cosine_similarity, embed_query, retrieve_related_sources, top_k


class FakeEmbeddingClient(BaseEmbeddingClient):
    def __init__(self, vector: list[float]):
        self.model = "fake-embedding-v1"
        self._vector = vector
        self.calls: list[tuple[str, bool]] = []

    async def embed(self, text: str, *, is_query: bool = False) -> list[float]:
        self.calls.append((text, is_query))
        return self._vector


def _index(chunks: list[EmbeddedChunk]) -> SpecIndex:
    return SpecIndex(document_id="doc_1", document_hash="hash123", model="fake", chunks=chunks)


def test_cosine_similarity_identical_vectors_is_one():
    a = [1.0, 2.0, 3.0]
    assert math.isclose(cosine_similarity_np(a, a), 1.0, rel_tol=1e-6)


def test_cosine_similarity_orthogonal_vectors_is_zero():
    assert math.isclose(cosine_similarity_np([1.0, 0.0], [0.0, 1.0]), 0.0, abs_tol=1e-9)


def test_cosine_similarity_zero_vector_returns_zero_not_error():
    assert cosine_similarity_np([0.0, 0.0], [1.0, 1.0]) == 0.0


def cosine_similarity_np(a, b):
    import numpy as np

    return cosine_similarity(np.asarray(a, dtype=float), np.asarray(b, dtype=float))


def test_top_k_orders_by_similarity_descending():
    index = _index([
        EmbeddedChunk(chunk_id="chunk_1", text="ログイン機能について", heading="3. ログイン機能", vector=[1.0, 0.0]),
        EmbeddedChunk(chunk_id="chunk_2", text="無関係な内容", heading="9. 付録", vector=[0.0, 1.0]),
        EmbeddedChunk(chunk_id="chunk_3", text="ログイン画面の詳細", heading="3.1 ログイン画面", vector=[0.9, 0.1]),
    ])

    results = top_k(index, query_vector=[1.0, 0.0], k=2)

    assert [r.chunk_id for r in results] == ["chunk_1", "chunk_3"]
    assert results[0].similarity >= results[1].similarity


def test_top_k_returns_only_real_chunk_metadata_no_fabrication():
    """page/sectionは常に実在のEmbeddedChunk.headingから来ており、
    それ以外の値(存在しないページ番号や節番号)が混入しないことを確認する。"""
    index = _index([
        EmbeddedChunk(chunk_id="chunk_1", text="本文", heading="3. ログイン機能", vector=[1.0, 0.0]),
    ])
    results = top_k(index, query_vector=[1.0, 0.0], k=3)

    assert len(results) == 1
    assert results[0].chunk_id == "chunk_1"
    assert results[0].section == "3. ログイン機能"
    assert results[0].page is None  # プレーンテキスト仕様書にページの概念は無く、常にNone
    assert results[0].document_id == "doc_1"


def test_top_k_with_no_heading_returns_section_none_not_fabricated():
    index = _index([EmbeddedChunk(chunk_id="chunk_1", text="見出し無しの本文", heading=None, vector=[1.0, 0.0])])
    results = top_k(index, query_vector=[1.0, 0.0], k=1)
    assert results[0].section is None


def test_top_k_empty_index_returns_empty_list():
    index = _index([])
    assert top_k(index, query_vector=[1.0, 0.0], k=3) == []


def test_top_k_k_larger_than_chunk_count_returns_all_chunks():
    index = _index([EmbeddedChunk(chunk_id="chunk_1", text="a", heading=None, vector=[1.0, 0.0])])
    results = top_k(index, query_vector=[1.0, 0.0], k=10)
    assert len(results) == 1


@pytest.mark.asyncio
async def test_embed_query_uses_query_prefix_flag():
    client = FakeEmbeddingClient(vector=[1.0, 0.0])
    await embed_query("ログイン画面とは", client)
    assert client.calls == [("ログイン画面とは", True)]


@pytest.mark.asyncio
async def test_retrieve_related_sources_returns_empty_when_index_is_none():
    client = FakeEmbeddingClient(vector=[1.0, 0.0])
    results = await retrieve_related_sources("何か", index=None, client=client, k=3)
    assert results == []
    assert client.calls == []  # indexが無ければEmbedding APIすら呼ばない


@pytest.mark.asyncio
async def test_retrieve_related_sources_returns_empty_for_empty_index():
    client = FakeEmbeddingClient(vector=[1.0, 0.0])
    results = await retrieve_related_sources("何か", index=_index([]), client=client, k=3)
    assert results == []


@pytest.mark.asyncio
async def test_retrieve_related_sources_end_to_end_with_fake_client():
    index = _index([
        EmbeddedChunk(chunk_id="chunk_1", text="ログイン機能について", heading="3. ログイン機能", vector=[1.0, 0.0]),
        EmbeddedChunk(chunk_id="chunk_2", text="無関係な内容", heading="9. 付録", vector=[0.0, 1.0]),
    ])
    client = FakeEmbeddingClient(vector=[1.0, 0.0])  # queryのembeddingはchunk_1に近い

    results = await retrieve_related_sources("ログイン画面を実装する", index=index, client=client, k=1)

    assert len(results) == 1
    assert results[0].chunk_id == "chunk_1"
    assert results[0].similarity == 1.0
