# backend/services/rag/schema.py
"""
実験的RAG機能のデータ構造。

既存の`backend.pipeline.requirements.schema.SourceReference`と同じ思想を踏襲する:
出典情報(chunk_id/page/section)はLLMに書かせず、常に実在の
`backend.services.pipeline.schema.DocumentChunk`(decompose_document()が仕様書本文から
機械的に切り出した、実在の部分文字列)から機械的に組み立てる。存在しないpage/sectionを
生成することはない(pageは現状プレーンテキストにしか対応していないため常にNone。
既存のSourceReferenceと同じ制約)。

このモジュールは既存のTask/Requirementスキーマを置き換えない。`related_sources`という
追加的なフィールドとして使われることを想定している。
"""

from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field


class RagSource(BaseModel):
    """RAG検索で見つかった、類似度付きの関連出典1件。

    既存の`SourceReference`(唯一の直接の出典)とは別物: こちらは
    「関連しそうな候補」を複数件、類似度スコア付きで保持するためのもの。
    """

    chunk_id: str
    document_id: str
    page: Optional[int] = Field(
        None, description="ページ番号。プレーンテキスト仕様書にはページの概念が無いため常にNone。"
    )
    section: Optional[str] = Field(None, description="条項見出し等。無ければNone。")
    similarity: float = Field(..., ge=0.0, le=1.0)


class EmbeddedChunk(BaseModel):
    """Embedding済みの1チャンク。textはDocumentChunkからの機械的なコピー。"""

    chunk_id: str
    text: str
    heading: Optional[str] = None
    vector: List[float]


class SpecIndex(BaseModel):
    """1つの仕様書テキストに対する、Embedding済みチャンクの集合(ベクトルインデックス)。

    `document_hash`はキャッシュのキー。同一仕様書(同一テキスト)であれば
    再Embeddingせず、このインデックスをそのまま再利用する。
    """

    document_id: str
    document_hash: str
    model: str
    chunks: List[EmbeddedChunk] = Field(default_factory=list)
