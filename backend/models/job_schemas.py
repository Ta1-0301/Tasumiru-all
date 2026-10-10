# backend/models/job_schemas.py
"""Phase 10: プロジェクト/ジョブAPIのリクエスト・レスポンススキーマ。

`backend/models/job.py`/`backend/models/project.py`（SQLAlchemyのDBモデル）
とは別。既存の`backend/models/schemas.py`と同じ役割（HTTP境界のPydantic
モデル）をジョブ/プロジェクトAPI向けに提供する。
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field

ErrorCode = str  # 既存のauth/tasksルーターと同じ、自由形式の機械可読コード


class ErrorDetail(BaseModel):
    code: ErrorCode
    message: str


class ProjectCreateRequest(BaseModel):
    name: Optional[str] = Field(None, description="プロジェクト名（表示用、任意）")
    document_text: Optional[str] = Field(None, description="仕様書本文（後から/generate時に渡すことも可能）")
    start_date: Optional[date] = Field(None, description="計画の開始日（任意。未設定なら生成ジョブの実行日）")
    due_date: Optional[date] = Field(None, description="プロジェクトの納期（任意。期限の無いタスクに適用される）")


class ProjectResponse(BaseModel):
    id: str
    team_id: str
    name: Optional[str] = None
    has_document: bool
    has_members: bool
    start_date: Optional[date] = None
    due_date: Optional[date] = None
    created_at: datetime
    updated_at: datetime


class SetMembersRequest(BaseModel):
    members: List[Dict[str, Any]] = Field(
        ..., description="Phase 6のMemberスキーマに沿った生レコードの配列。ここでは一切値を作り出さない。"
    )


class GenerateRequest(BaseModel):
    document_text: Optional[str] = Field(
        None, description="指定した場合、生成前にプロジェクトの仕様書本文を更新する"
    )
    use_assignment_llm_reasoning: bool = Field(
        False, description="Phase 7 Step 3（LLMによる補足説明）を有効にするか（既定オフ）"
    )
    use_duplicate_llm_verification: bool = Field(
        False, description="Phase 8 CHECK 2の重複候補についてLLM検証を行うか（既定オフ）"
    )
    start_date: Optional[date] = Field(
        None, description="指定した場合、生成前にプロジェクトの開始日を更新する"
    )
    due_date: Optional[date] = Field(
        None, description="指定した場合、生成前にプロジェクトの納期を更新する"
    )


class UpdateRequest(BaseModel):
    """完了済みジョブの結果を再利用して、メンバー変更・仕様変更を反映する（新しいジョブを作る）"""

    source_job_id: str = Field(..., description="再利用する完了済みジョブのID")
    mode: Literal["members", "spec"] = Field(
        ..., description="members: 割り当てだけやり直す / spec: 仕様書の変更部分だけ再解析する"
    )
    document_text: Optional[str] = Field(None, description="mode=specのとき必須。更新後の仕様書本文")
    reassign_scope: Literal["unassigned", "all", "selected"] = Field(
        "unassigned",
        description="unassigned: 担当者が決まっているタスクは変更しない（既定） / "
        "selected: task_idsのタスクだけ割り当て直す / all: すべて割り当て直す",
    )
    task_ids: List[str] = Field(default_factory=list, description="reassign_scope=selectedのとき割り当て直すタスク")
    current_assignments: Dict[str, Optional[str]] = Field(
        default_factory=dict,
        description="画面で手動変更した担当者（タスクID→メンバーID、未割当にした場合はnull）。維持対象として扱う",
    )


class GenerateResponse(BaseModel):
    job_id: str
    status: Literal["queued"]


class JobStatusResponse(BaseModel):
    job_id: str
    project_id: str
    team_id: str
    status: Literal["queued", "running", "completed", "failed", "cancelled"]
    progress: int
    current_step: Optional[str] = None
    message: Optional[str] = None
    created_at: datetime
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    error: Optional[ErrorDetail] = None
