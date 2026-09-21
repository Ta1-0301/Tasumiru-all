# backend/services/pipeline/schema.py
"""
新タスク抽出パイプラインのデータ構造。

設計方針（TASK_EXTRACTION_EVALUATION.mdの発見を踏まえたもの）:

1. source_reference は「LLMが書いた文字列」ではなく、常に
   DocumentChunk（decompose_document()が仕様書本文から機械的に切り出した、
   実在する部分文字列）へのポインタから構築される。LLMはchunk_idを選ぶだけで、
   出典テキストそのものを生成しない。これにより出典の捏造が構造的に起こらない。
2. 各フィールドは「確信が持てないなら null または 'unknown'」を許容する。
   確信の持てない値を無言ででっち上げるくらいなら、分からないと言う方が良い、
   という評価結果（judgeが無意味なタスクにも甘い点を付けた事例）を踏まえた設計。
3. 検証に失敗した項目は Task に無理やり詰め込まず、failed_items に分離する
   （「LLMの不正な出力を黙って受け入れない」という要件のため）。
"""

from __future__ import annotations

from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field


class RequirementType(str, Enum):
    explicit = "explicit"          # 明示的指示（「〜してください」）
    deadline = "deadline"          # 締切・期限
    deliverable = "deliverable"    # 提出物・成果物
    conditional = "conditional"    # 条件付き（「〜の場合は〜」）
    implicit = "implicit"          # 暗黙の準備・確認
    prohibition = "prohibition"    # 禁止事項からの逆算


class Priority(str, Enum):
    high = "high"
    medium = "medium"
    low = "low"
    unknown = "unknown"


class DocumentChunk(BaseModel):
    """仕様書本文を機械的に分割した1単位。textは必ず本文の実在の部分文字列。"""

    chunk_id: str
    text: str
    heading: Optional[str] = None


class Requirement(BaseModel):
    """1つのチャンクから抽出された、単一の要求事項"""

    requirement_id: str
    chunk_id: str
    text: str
    requirement_type: RequirementType


class SourceReference(BaseModel):
    """タスクの出典。chunk_idとexcerptは常にDocumentChunkから機械的に転記される
    （LLMが自由記述したものではない）。
    """

    chunk_id: str
    excerpt: str


class CandidateTask(BaseModel):
    """normalize/dedup段階で扱う、まだ検証前の中間表現"""

    title: str
    description: Optional[str] = None
    priority: Priority = Priority.unknown
    estimated_hours: Optional[float] = None
    required_skills: List[str] = Field(default_factory=lambda: ["unknown"])
    source_reference: Optional[SourceReference] = None
    acceptance_criteria: Optional[List[str]] = None
    needs_review: bool = False
    review_reason: Optional[str] = None


class Task(BaseModel):
    """最終的な構造化出力（strict）"""

    task_id: str
    title: str
    description: Optional[str] = None
    priority: Priority = Priority.unknown
    estimated_hours: Optional[float] = None
    required_skills: List[str] = Field(default_factory=lambda: ["unknown"])
    source_reference: Optional[SourceReference] = None
    acceptance_criteria: Optional[List[str]] = None
    needs_review: bool = False
    review_reason: Optional[str] = None


class FailedItem(BaseModel):
    """検証に失敗し、修復も失敗した項目。Taskとして扱わず分離する。"""

    raw_data: dict
    error: str
    stage: str


class PipelineResult(BaseModel):
    """パイプライン全体の実行結果"""

    tasks: List[Task]
    failed_items: List[FailedItem] = Field(default_factory=list)
    dropped_duplicates: List[str] = Field(default_factory=list)
    chunk_count: int = 0
    requirement_count: int = 0
