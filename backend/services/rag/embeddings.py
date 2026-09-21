# backend/services/rag/embeddings.py
"""
実験的RAG機能: Embeddingクライアント。

`backend.services.llm.BaseLLMClient`(生成用)とは完全に分離する。生成モデルは
`OLLAMA_MODEL`、Embeddingモデルは`OLLAMA_EMBEDDING_MODEL`と別の環境変数で設定でき、
モデル名はコードにハードコードしない。

document側/query側で異なるprefix("search_document: "/"search_query: ")を付けるのは
nomic-embed-textの学習時の慣例に合わせたもの（先生提供コードの考え方を踏襲）。
"""

from __future__ import annotations

import os
from abc import ABC, abstractmethod
from typing import List

import httpx
from fastapi import HTTPException

OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL")
OLLAMA_EMBEDDING_MODEL = os.getenv("OLLAMA_EMBEDDING_MODEL", "nomic-embed-text")

_DOCUMENT_PREFIX = "search_document: "
_QUERY_PREFIX = "search_query: "


class BaseEmbeddingClient(ABC):
    """全Embeddingプロバイダー共通のインターフェース。"""

    model: str

    @abstractmethod
    async def embed(self, text: str, *, is_query: bool = False) -> List[float]:
        """textをベクトルに変換する。is_query=Trueならquery用prefixを使う。"""


class OllamaEmbeddingClient(BaseEmbeddingClient):
    """ローカルOllamaのEmbedding APIを使う実装。"""

    def __init__(self):
        if not OLLAMA_BASE_URL:
            raise RuntimeError("環境変数 'OLLAMA_BASE_URL' が設定されていません。")
        self.base_url = OLLAMA_BASE_URL
        self.model = OLLAMA_EMBEDDING_MODEL

    async def embed(self, text: str, *, is_query: bool = False) -> List[float]:
        prefix = _QUERY_PREFIX if is_query else _DOCUMENT_PREFIX
        payload = {"model": self.model, "prompt": prefix + text}

        async with httpx.AsyncClient(timeout=300) as client:
            try:
                response = await client.post(f"{self.base_url}/api/embeddings", json=payload)
                response.raise_for_status()
                return response.json()["embedding"]
            except httpx.HTTPError:
                raise HTTPException(
                    status_code=504,
                    detail={"code": "EMBEDDING_TIMEOUT", "message": "Embedding APIとの通信に失敗しました。"},
                )
            except KeyError:
                raise HTTPException(
                    status_code=500,
                    detail={"code": "EMBEDDING_PARSE_ERROR", "message": "Embedding APIの応答フォーマットが不正です。"},
                )


def get_embedding_client() -> BaseEmbeddingClient:
    """現状はOllama固定（生成側のLLM_PROVIDERと違い、Embeddingは常にローカルOllama）。

    将来他プロバイダーを追加する場合も、非公開情報を外部クラウドに送らない
    という制約上、ローカル実行のプロバイダーのみを追加する想定。
    """
    return OllamaEmbeddingClient()
