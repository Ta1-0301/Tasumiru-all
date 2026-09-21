# backend/models/task.py
from datetime import date

from sqlalchemy import JSON, Boolean, Date, Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from backend.db.base import Base


class TaskModel(Base):
    __tablename__ = "tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    org_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    task_id: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    assignee: Mapped[str] = mapped_column(String(255), default="未割り当て")

    # 既存互換フィールド（matcher.py・旧フロントAPI契約向け）
    skill_required: Mapped[str] = mapped_column(String(255), default="unknown")
    priority: Mapped[str] = mapped_column(String(50), default="unknown")
    deadline: Mapped[date | None] = mapped_column(Date, nullable=True)
    source_section: Mapped[str] = mapped_column(String(255), default="§ 出典不明")
    load_pct: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(50), default="TODO")

    # 新タスク抽出パイプライン(backend/services/pipeline/)由来の拡張フィールド
    # すべてnullable。パイプラインが確信を持てなかった項目はnullのまま保存する。
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    estimated_hours: Mapped[float | None] = mapped_column(Float, nullable=True)
    required_skills: Mapped[list | None] = mapped_column(JSON, nullable=True)
    acceptance_criteria: Mapped[list | None] = mapped_column(JSON, nullable=True)
    source_chunk_id: Mapped[str | None] = mapped_column(String(50), nullable=True)
    source_excerpt: Mapped[str | None] = mapped_column(Text, nullable=True)
    needs_review: Mapped[bool] = mapped_column(Boolean, default=False)
    review_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
