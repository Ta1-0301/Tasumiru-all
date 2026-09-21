# backend/services/rag/search.py
"""
実験的RAG機能: Cosine Similarityによるベクトル検索。

既存の`backend.services.skill_matching`(TF-IDF + Cosine Similarityによる
スキルマッチング)とは完全に別の責務・別のコードパス。混同しないよう、
関数名・モジュールも独立させている。こちらのCosine Similarityは
「Embeddingベクトル同士の類似度」専用。

出典(page/section)は常に実在のchunk metadataから返す。検索結果が無い場合は
空配列を返すだけで、それらしい出典を作り出すことはしない。
"""

from __future__ import annotations

from typing import List, Optional

import numpy as np

from backend.services.rag.embeddings import BaseEmbeddingClient
from backend.services.rag.schema import RagSource, SpecIndex


def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """2つのベクトルのCosine Similarity。 a @ b / (norm(a) * norm(b))"""
    denom = np.linalg.norm(a) * np.linalg.norm(b)
    if denom == 0.0:
        return 0.0
    return float(np.dot(a, b) / denom)


async def embed_query(text: str, client: BaseEmbeddingClient) -> List[float]:
    """query用prefixでEmbeddingする（document用embed_documentとは別の呼び出し）。"""
    return await client.embed(text, is_query=True)


def top_k(index: SpecIndex, query_vector: List[float], k: int = 3) -> List[RagSource]:
    """query_vectorとindex内の全chunkベクトルとのCosine Similarityを計算し、
    類似度上位k件を返す（Python側で高速に処理、外部ベクトルDBは使わない）。
    """
    if not index.chunks:
        return []

    q = np.asarray(query_vector, dtype=float)
    matrix = np.asarray([c.vector for c in index.chunks], dtype=float)

    denom = np.linalg.norm(matrix, axis=1) * np.linalg.norm(q)
    with np.errstate(invalid="ignore", divide="ignore"):
        similarities = np.where(denom != 0.0, (matrix @ q) / denom, 0.0)

    top_indices = np.argsort(-similarities)[:k]

    return [
        RagSource(
            chunk_id=index.chunks[i].chunk_id,
            document_id=index.document_id,
            page=None,  # 既存のSourceReferenceと同じ理由で常にNone（存在しない情報を捏造しない）
            section=index.chunks[i].heading,
            similarity=round(float(similarities[i]), 4),
        )
        for i in top_indices
    ]


async def retrieve_related_sources(
    text: str,
    index: Optional[SpecIndex],
    client: BaseEmbeddingClient,
    *,
    k: int = 3,
) -> List[RagSource]:
    """textをqueryとして、indexから関連度の高いchunkをk件検索する。

    indexが無い(RAG OFF)/空の場合は空配列を返す。フォールバックとして
    それらしい出典を作り出すことはしない。
    """
    if index is None or not index.chunks:
        return []

    query_vector = await embed_query(text, client)
    return top_k(index, query_vector, k=k)
