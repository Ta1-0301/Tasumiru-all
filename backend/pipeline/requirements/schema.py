# backend/pipeline/requirements/schema.py
"""
Phase 3の出力データ構造（requirements.json）。

設計方針:
1. `type`は依頼された9つの抽出対象（system purpose / target users /
   functional / non-functional / constraints / assumptions / deliverables /
   technical requirements / business rules）と1対1に対応する。
2. `origin`で「仕様書に明記されている(explicit)」か「文脈からの推測(inferred)」
   かを明示的に分離する（依頼の「Separate explicit requirements from
   inferred information」に対応）。
3. `source_reference`は常に`backend.services.pipeline.structure.decompose_document()`
   （既存の文書構造抽出、読み取り専用で再利用）が切り出した実在のチャンクから
   機械的に転記される。LLMが出典テキストそのものを自由記述することはない
   （`backend/services/pipeline/`と同じ、出典を捏造できない構造上の保証）。
4. `page`は現状プレーンテキストの仕様書にしか対応しておらず、ページの概念が
   無いため常に`None`（無い情報を捏造しない）。
5. `confidence`は0.0-1.0。情報が不確かな場合は低い値にする
   （依頼の「If information is uncertain: mark confidence low」に対応）。
"""

from __future__ import annotations

from typing import List, Literal, Optional

from pydantic import BaseModel, Field

RequirementType = Literal[
    "system_purpose",
    "target_user",
    "functional",
    "non_functional",
    "constraint",
    "assumption",
    "deliverable",
    "technical",
    "business_rule",
]

Priority = Literal["high", "medium", "low", "unknown"]

Origin = Literal["explicit", "inferred"]


class SourceReference(BaseModel):
    document_id: str
    page: Optional[int] = Field(
        None, description="ページ番号。プレーンテキスト仕様書にはページの概念が無いため常にNone。"
    )
    section: Optional[str] = Field(None, description="条項見出し等。無ければNone。")
    paragraph: Optional[str] = Field(None, description="段落/チャンクの識別子（chunk_id）。")
    source_text: Optional[str] = Field(None, description="出典の原文抜粋。仕様書本文からの実在の部分文字列。")


class RequirementCandidate(BaseModel):
    """検証・ID割り当て前の中間表現"""

    type: RequirementType
    title: str
    description: str
    priority: Priority = "unknown"
    origin: Origin = "explicit"
    source_reference: Optional[SourceReference] = None
    confidence: float = Field(0.5, ge=0.0, le=1.0)


class Requirement(BaseModel):
    """最終的な構造化要求（requirements.json の1要素）"""

    id: str = Field(..., pattern=r"^REQ-\d{3,}$")
    type: RequirementType
    title: str
    description: str
    priority: Priority = "unknown"
    origin: Origin = "explicit"
    source_reference: Optional[SourceReference] = None
    confidence: float = Field(..., ge=0.0, le=1.0)


class ValidationIssue(BaseModel):
    """Requirement Validationステージが検出した問題点"""

    code: str
    message: str
    requirement_ids: List[str] = Field(default_factory=list)


class RequirementDocument(BaseModel):
    """requirements.json の全体（1つの仕様書に対する抽出結果）"""

    document_id: str
    requirements: List[Requirement]
    issues: List[ValidationIssue] = Field(default_factory=list)
    model: Optional[str] = None
    model_version: Optional[str] = None
    generated_at: Optional[str] = Field(None, description="ISO8601形式の生成時刻(UTC)")
