# backend/services/rag/index.py
"""
実験的RAG機能: 仕様書のベクトルインデックス構築。

chunk化には新しいロジックを作らず、既存の`backend.services.pipeline.structure.decompose_document()`
(requirements抽出と全く同じ、出典が実在チャンクに機械的に紐づくchunk化)をそのまま再利用する。

Embeddingは同一仕様書(同一テキスト)につき一度だけ行う。`document_hash`(sha256)をキーにした
ファイルベースのキャッシュ(`backend/services/rag/cache/`)に保存し、2回目以降はEmbedding
APIを呼ばずキャッシュから読む。DBテーブルは追加しない(既存のOUTPUT_DIR/save_*_document
パターンを踏襲したファイル永続化)。
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import List, Optional

from backend.services.concurrency import gather_with_concurrency, get_max_concurrency
from backend.services.pipeline.schema import DocumentChunk
from backend.services.pipeline.structure import decompose_document
from backend.services.rag.embeddings import BaseEmbeddingClient
from backend.services.rag.schema import EmbeddedChunk, SpecIndex

CACHE_DIR = Path(__file__).resolve().parent / "cache"


def document_hash(document_text: str) -> str:
    """仕様書テキストのキャッシュキー。同一テキストは常に同一ハッシュになる。"""
    return hashlib.sha256(document_text.encode("utf-8")).hexdigest()[:16]


def _cache_path(doc_hash: str, cache_dir: Path) -> Path:
    return cache_dir / f"{doc_hash}.index.json"


def load_cached_index(doc_hash: str, cache_dir: Path = CACHE_DIR) -> Optional[SpecIndex]:
    path = _cache_path(doc_hash, cache_dir)
    if not path.exists():
        return None
    try:
        return SpecIndex.model_validate_json(path.read_text(encoding="utf-8"))
    except ValueError:
        # 壊れた/形式が古いキャッシュは無視して再構築する（例外で処理を止めない）
        return None


def save_index(index: SpecIndex, cache_dir: Path = CACHE_DIR) -> Path:
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = _cache_path(index.document_hash, cache_dir)
    path.write_text(index.model_dump_json(indent=2), encoding="utf-8")
    return path


def chunk_document(document_text: str) -> List[DocumentChunk]:
    """既存のdecompose_document()をそのまま呼ぶだけ（新しいchunkingロジックは作らない）。"""
    return decompose_document(document_text)


async def build_spec_index(
    document_id: str,
    document_text: str,
    client: BaseEmbeddingClient,
    *,
    cache_dir: Path = CACHE_DIR,
) -> SpecIndex:
    """仕様書テキストからベクトルインデックスを構築する（キャッシュがあれば再利用）。

    同一document_textに対しては、キャッシュヒット時はEmbedding API呼び出しが
    0回になる（速度要件: 「仕様書のEmbeddingは可能なら一度だけ作成」）。
    """
    doc_hash = document_hash(document_text)

    cached = load_cached_index(doc_hash, cache_dir)
    if cached is not None:
        return cached

    chunks = chunk_document(document_text)

    # chunk同士のembeddingは互いに独立しているため、requirements/tasks抽出と
    # 同じ既存のconcurrencyヘルパーで安全に並列化できる（既定値1=逐次実行のまま、
    # OLLAMA_MAX_CONCURRENCYで明示的に上げない限り挙動は変わらない）。
    max_concurrency = get_max_concurrency()
    vectors = await gather_with_concurrency(
        [(lambda c=chunk: client.embed(c.text, is_query=False)) for chunk in chunks],
        max_concurrency,
    )
    embedded_chunks: List[EmbeddedChunk] = [
        EmbeddedChunk(chunk_id=chunk.chunk_id, text=chunk.text, heading=chunk.heading, vector=vector)
        for chunk, vector in zip(chunks, vectors)
    ]

    index = SpecIndex(
        document_id=document_id,
        document_hash=doc_hash,
        model=getattr(client, "model", "unknown"),
        chunks=embedded_chunks,
    )
    save_index(index, cache_dir)
    return index
