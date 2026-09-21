# backend/pipeline/tasks/schema.py
"""
Phase 4の出力データ構造（tasks.json）。

`SourceReference`/`Priority`はPhase 3(`backend.pipeline.requirements.schema`)の
ものを再利用する。タスクの出典は常にそれを生んだ`Requirement`の
`source_reference`をそのまま引き継ぐだけであり、このフェーズで新しい出典を
書き起こすことはない（元の仕様書を直接パースし直さないという方針に対応）。

`needs_review`/`review_reasons`は「検証で見つかった問題を黒黙に修復せず、
レビュー対象として印を付ける」という依頼のルールに対応するフィールド。
"""

from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field

from backend.pipeline.requirements.schema import Priority, SourceReference
from backend.services.rag.schema import RagSource

__all__ = [
    "Priority",
    "SourceReference",
    "RagSource",
    "TaskCandidate",
    "Task",
    "ValidationIssue",
    "TaskDocument",
]


class TaskCandidate(BaseModel):
    """検証・ID割り当て前の中間表現"""

    requirement_ids: List[str] = Field(default_factory=list)
    title: str
    description: str
    priority: Priority = "unknown"
    estimated_hours: Optional[float] = None
    required_skills: List[str] = Field(default_factory=lambda: ["unknown"])
    acceptance_criteria: List[str] = Field(default_factory=list)
    source_reference: Optional[SourceReference] = None
    confidence: float = Field(0.5, ge=0.0, le=1.0)
    # 実験的RAG機能（既定はOFF、空配列）: 既存のsource_referenceを置き換えるものではなく、
    # 類似度検索で見つかった追加の関連出典を保持するだけの付加的なフィールド。
    related_sources: List[RagSource] = Field(default_factory=list)


class Task(BaseModel):
    """最終的な構造化タスク（tasks.json の1要素）"""

    id: str = Field(..., pattern=r"^TASK-\d{3,}$")
    requirement_ids: List[str] = Field(default_factory=list)
    title: str
    description: str
    priority: Priority = "unknown"
    estimated_hours: Optional[float] = None
    required_skills: List[str] = Field(default_factory=lambda: ["unknown"])
    acceptance_criteria: List[str] = Field(default_factory=list)
    source_reference: Optional[SourceReference] = None
    confidence: float = Field(..., ge=0.0, le=1.0)
    # 実験的RAG機能（既定はOFF、空配列）: 既存のsource_referenceを置き換えるものではなく、
    # 類似度検索で見つかった追加の関連出典を保持するだけの付加的なフィールド。
    related_sources: List[RagSource] = Field(default_factory=list)

    # Task Validationが検出した問題を「修復せず印を付ける」ためのフィールド
    needs_review: bool = False
    review_reasons: List[str] = Field(default_factory=list)


class ValidationIssue(BaseModel):
    """Task Validationステージが検出した問題点"""

    code: str
    message: str
    task_ids: List[str] = Field(default_factory=list)


class TaskDocument(BaseModel):
    """tasks.json の全体（1つの要求ドキュメントから分解されたタスク一覧）"""

    document_id: str
    tasks: List[Task]
    issues: List[ValidationIssue] = Field(default_factory=list)
    model: Optional[str] = None
    generated_at: Optional[str] = Field(None, description="ISO8601形式の生成時刻(UTC)")
