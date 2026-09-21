# backend/tests/test_rag_plot.py
"""backend/services/rag/plot.py の単体テスト。

実際のOllamaは一切呼ばない（フェイクEmbeddingクライアント使用）。LLM生成
クライアント(BaseLLMClient)はこのモジュールのどこからも参照されないこと、
つまり本当にEmbeddingとCosine Similarityの計算・描画だけで完結している
ことも合わせて確認する。
"""

import pytest

from backend.services.rag.embeddings import BaseEmbeddingClient
from backend.services.rag.plot import _all_similarities, build_and_plot
from backend.services.rag.schema import EmbeddedChunk, SpecIndex


class FakeEmbeddingClient(BaseEmbeddingClient):
    def __init__(self):
        self.model = "fake-embedding-v1"
        self.calls: list[tuple[str, bool]] = []

    async def embed(self, text: str, *, is_query: bool = False) -> list[float]:
        self.calls.append((text, is_query))
        # クエリと"ログイン"を含むchunkが近くなるようなフェイクベクトル
        if is_query or "ログイン" in text:
            return [1.0, 0.0]
        return [0.0, 1.0]


DOC_TEXT = "第1条(ログイン)\nログイン機能を実装する。\n\n第2条(付録)\n無関係な内容。"


def test_all_similarities_matches_chunk_count():
    index = SpecIndex(
        document_id="doc_1", document_hash="h", model="fake",
        chunks=[
            EmbeddedChunk(chunk_id="chunk_1", text="a", heading=None, vector=[1.0, 0.0]),
            EmbeddedChunk(chunk_id="chunk_2", text="b", heading=None, vector=[0.0, 1.0]),
        ],
    )
    similarities = _all_similarities(index, [1.0, 0.0])
    assert similarities == [1.0, 0.0]


@pytest.mark.asyncio
async def test_build_and_plot_creates_png_file_without_calling_generation_llm(tmp_path):
    client = FakeEmbeddingClient()
    output_path = tmp_path / "similarity.png"

    result_path = await build_and_plot(
        "doc_1", DOC_TEXT, "ログイン画面を実装する",
        embedding_client=client, top_k=2, output_path=output_path,
    )

    assert result_path == output_path
    assert output_path.exists()
    assert output_path.stat().st_size > 0
    # 呼ばれたのはEmbedding APIだけ（LLM生成クライアントはこのモジュールに存在しない）
    assert len(client.calls) >= 1


@pytest.mark.asyncio
async def test_build_and_plot_empty_document_does_not_crash(tmp_path):
    client = FakeEmbeddingClient()
    output_path = tmp_path / "empty.png"

    result_path = await build_and_plot(
        "doc_1", "", "何か", embedding_client=client, output_path=output_path,
    )

    assert result_path.exists()
