# backend/pipeline/dependencies/schema.py
"""
Phase 5の出力データ構造（dependencies.json）。

依存関係の方向の定義:
  辺 (from_task_id -> to_task_id) は「from_task_id が完了しないと
  to_task_id に着手できない」という意味（from が先行タスク、to が後続タスク）。

  例（GOAL節の図）:
    データベース設計(TASK-001) → バックエンドAPI(TASK-002) → フロントエンド統合(TASK-003)
    は from_task_id="TASK-001", to_task_id="TASK-002" のように表現する。

`Dependency`にはIDを割り当てない（依頼のSCHEMAにも無い）。1つの依存関係は
(from_task_id, to_task_id)のペアで識別する。
"""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field

DependencyType = Literal["required", "recommended", "optional"]


class Dependency(BaseModel):
    """タスク間の依存関係（1件）"""

    from_task_id: str
    to_task_id: str
    type: DependencyType = "optional"
    reason: str = ""
    confidence: float = Field(..., ge=0.0, le=1.0)


class EdgeRef(BaseModel):
    """ValidationIssueが指す辺（依存関係にはIDが無いため、from/toのペアで参照する）"""

    from_task_id: str
    to_task_id: str


class ValidationIssue(BaseModel):
    """Dependency Validationステージが検出した問題点"""

    code: str
    message: str
    edges: List[EdgeRef] = Field(default_factory=list)


class DependencyDocument(BaseModel):
    """dependencies.json の全体"""

    document_id: str
    dependencies: List[Dependency]
    issues: List[ValidationIssue] = Field(default_factory=list)
    graph: Dict[str, Any] = Field(default_factory=dict, description="DependencyGraph.to_dict()の結果")
    model: Optional[str] = None
    generated_at: Optional[str] = Field(None, description="ISO8601形式の生成時刻(UTC)")
