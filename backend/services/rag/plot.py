# backend/services/rag/plot.py
"""
実験的RAG機能: query-chunk間のCosine Similarityを可視化する（バックエンドのみ、matplotlib）。

LLM(生成モデル/OLLAMA_MODEL)は一切呼ばない。使うのはOllamaのEmbedding API
(OLLAMA_EMBEDDING_MODEL、既定nomic-embed-text)と、backend.services.rag.search
の純Python/numpyのCosine Similarity計算だけ。

使い方（CLIから直接実行する場合）:
    export OLLAMA_BASE_URL=http://localhost:11434
    export OLLAMA_EMBEDDING_MODEL=nomic-embed-text
    python -m backend.services.rag.plot <仕様書テキストファイル> "<検索クエリ>" \\
        [--top-k 3] [--output out.png]

matplotlibはヘッドレス環境（画面の無いサーバー）でも動くよう、pyplotを
importする前に必ずAggバックエンドを明示的に指定する（描画結果はファイルに
保存するだけで、plt.show()のようなブロッキング呼び出しは行わない）。
"""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path
from typing import List

import matplotlib

matplotlib.use("Agg")  # ヘッドレス環境向け。plt.show()は使わずファイル保存のみ行う
import matplotlib.pyplot as plt
import numpy as np

from backend.services.plot_fonts import configure_japanese_font
from backend.services.rag.embeddings import BaseEmbeddingClient, get_embedding_client
from backend.services.rag.index import build_spec_index
from backend.services.rag.schema import SpecIndex
from backend.services.rag.search import embed_query

configure_japanese_font()

DEFAULT_OUTPUT = Path(__file__).resolve().parent / "output" / "cosine_similarity.png"


def _all_similarities(index: SpecIndex, query_vector: List[float]) -> List[float]:
    """indexの全chunkに対するquery_vectorとのCosine Similarity（top-kに絞らず全件）。"""
    if not index.chunks:
        return []
    q = np.asarray(query_vector, dtype=float)
    matrix = np.asarray([c.vector for c in index.chunks], dtype=float)
    denom = np.linalg.norm(matrix, axis=1) * np.linalg.norm(q)
    with np.errstate(invalid="ignore", divide="ignore"):
        similarities = np.where(denom != 0.0, (matrix @ q) / denom, 0.0)
    return [round(float(s), 4) for s in similarities]


def plot_query_chunk_similarity(
    index: SpecIndex,
    query: str,
    similarities: List[float],
    *,
    top_k: int = 3,
    output_path: Path = DEFAULT_OUTPUT,
) -> Path:
    """query 1件と仕様書の各chunkとのCosine Similarityを棒グラフにして保存する。

    上位top_k件は強調色、それ以外は淡色にする（実際にRAG検索で選ばれる/
    選ばれないchunkが一目でわかるようにするため）。
    """
    labels = [c.heading or c.chunk_id for c in index.chunks]
    order = sorted(range(len(similarities)), key=lambda i: -similarities[i])
    top_indices = set(order[:top_k])

    colors = ["#2b6cb0" if i in top_indices else "#cbd5e0" for i in range(len(similarities))]

    fig, ax = plt.subplots(figsize=(max(6, len(labels) * 0.8), 4.5))
    ax.bar(range(len(similarities)), similarities, color=colors)
    ax.set_xticks(range(len(labels)))
    ax.set_xticklabels(labels, rotation=45, ha="right")
    ax.set_ylim(0.0, 1.0)
    ax.set_ylabel("Cosine Similarity")
    ax.set_title(f"Query-Chunk Cosine Similarity (top-{top_k} highlighted)\nquery: {query!r}")
    fig.tight_layout()

    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=150)
    plt.close(fig)
    return output_path


async def build_and_plot(
    document_id: str,
    document_text: str,
    query: str,
    *,
    embedding_client: BaseEmbeddingClient,
    top_k: int = 3,
    output_path: Path = DEFAULT_OUTPUT,
) -> Path:
    """仕様書indexを構築し、queryとの類似度を計算してプロットを保存する（LLM生成は一切呼ばない）。"""
    index = await build_spec_index(document_id, document_text, embedding_client)
    query_vector = await embed_query(query, embedding_client)
    similarities = _all_similarities(index, query_vector)
    return plot_query_chunk_similarity(index, query, similarities, top_k=top_k, output_path=output_path)


async def _main() -> None:
    parser = argparse.ArgumentParser(description="仕様書chunkとqueryのCosine Similarityをプロットする")
    parser.add_argument("spec_text_file", help="仕様書テキストファイルのパス")
    parser.add_argument("query", help="検索クエリ文字列")
    parser.add_argument("--top-k", type=int, default=3)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    document_text = Path(args.spec_text_file).read_text(encoding="utf-8")
    client = get_embedding_client()
    output_path = await build_and_plot(
        "cli_doc", document_text, args.query,
        embedding_client=client, top_k=args.top_k, output_path=args.output,
    )
    print(f"保存先: {output_path}")


if __name__ == "__main__":
    asyncio.run(_main())
