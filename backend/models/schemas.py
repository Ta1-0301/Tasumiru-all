# backend/models/schemas.py
from datetime import date
from typing import List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


class MemberSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    name: str = Field(..., description="メンバーの氏名")
    skills: List[str] = Field(..., description="所有スキルのリスト")
    load_pct: int = Field(0, ge=0, le=100, description="現在の稼働負荷 (0-100%)")

    @field_validator("skills", mode="before")
    @classmethod
    def _split_skills(cls, value):
        # DB保存時はカンマ区切りの文字列のため、リストに変換する
        if isinstance(value, str):
            return [s.strip() for s in value.split(",") if s.strip()]
        return value


class TaskGenerateRequest(BaseModel):
    # ファイルアップロード(Form)と同時にメンバーリストをJSON文字列などで受け取るため、
    # ルーター側で個別に処理しますが、型定義として残しておきます。
    members: List[MemberSchema]


class TaskSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    task_id: str = Field(..., description="タスクID (例: T-001)")
    title: str = Field(..., description="タスク名")
    assignee: str = Field(..., description="担当候補者名")
    skill_required: str = Field(..., description="必要スキル（表示用の文字列。詳細はrequired_skills参照）")
    priority: Literal["high", "medium", "low", "unknown"] = Field(..., description="優先度")
    deadline: Optional[date] = Field(None, description="締切日")
    source_section: str = Field(..., description="仕様書の参照箇所（表示用。詳細はsource_chunk_id/source_excerpt参照）")
    load_pct: int = Field(..., ge=0, le=100, description="アサイン後の予測稼働負荷")
    status: str = Field("TODO", description="Kanbanステータス (TODO, DOING, DONE)")

    # --- 新タスク抽出パイプライン由来の拡張フィールド（すべて省略可） ---
    description: Optional[str] = Field(None, description="タスクの詳細説明")
    estimated_hours: Optional[float] = Field(None, description="見積り工数（時間）")
    required_skills: Optional[List[str]] = Field(None, description="必要スキルのリスト")
    acceptance_criteria: Optional[List[str]] = Field(None, description="完了と判断できる条件のリスト")
    source_chunk_id: Optional[str] = Field(None, description="出典の仕様書チャンクID")
    source_excerpt: Optional[str] = Field(None, description="出典の原文抜粋")
    needs_review: bool = Field(False, description="人による確認が必要かどうか")
    review_reason: Optional[str] = Field(None, description="要確認の理由")


class GenerationNotes(BaseModel):
    """生成処理で捨てられた/失敗した項目を透明化するための付帯情報"""

    failed_item_count: int = Field(0, description="検証に失敗し破棄された項目数")
    dropped_duplicate_titles: List[str] = Field(default_factory=list, description="重複として除外されたタスク名")


class ProjectOutputSchema(BaseModel):
    project: str = Field("名称未設定プロジェクト", description="プロジェクト名")
    exported_at: date = Field(..., description="エクスポート日")
    tasks: List[TaskSchema] = Field(..., description="生成されたタスク一覧")
    generation_notes: Optional[GenerationNotes] = Field(
        None, description="直近のtasks/generate実行についての付帯情報（一覧取得時はnull）"
    )


class TaskUpdateRequest(BaseModel):
    title: Optional[str] = None
    assignee: Optional[str] = None
    priority: Optional[Literal["high", "medium", "low", "unknown"]] = None
    source_section: Optional[str] = None
    status: Optional[str] = None  # Kanban用 (TODO, DOING, DONE)


class SettingsSchema(BaseModel):
    provider: Literal["openai", "anthropic", "ollama"] = Field(
        ..., description="LLMプロバイダ"
    )
    api_key: str = Field(..., description="APIキー (type=password)")
    base_url: Optional[str] = Field(
        None, description="Ollama選択時のみ使用するBase URL"
    )
    slack_webhook_url: Optional[str] = Field(None, description="Slack Webhook URL")
    teams_webhook_url: Optional[str] = Field(None, description="Teams Webhook URL")
