# backend/models/job.py
"""
Phase 10: 生成ジョブの状態管理。

既存のDB(SQLite)にテーブルを追加するだけ。ジョブ本体の重いデータ
(RequirementDocument/TaskDocument/...)はここには保存せず、各フェーズが
既に持っている保存関数(save_requirements_document等)でJSONファイルとして
書き出し、そのパスだけをここに記録する
（"Do not persist unnecessary data"への対応）。
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from backend.db.base import Base

# queued -> running -> (completed | failed | cancelled)
JOB_STATUSES = ("queued", "running", "completed", "failed", "cancelled")

# Phase 3-9の実際のステージ名（存在しないステージは作らない）
PIPELINE_STEPS = (
    "requirements",   # Phase 3: specification understanding / requirement extraction
    "tasks",          # Phase 4: task decomposition
    "dependencies",   # Phase 5: dependency generation
    "members",        # Phase 6: member information retrieval（LLM不使用）
    "assignments",    # Phase 7: assignment
    "validation",     # Phase 8: validation
    "finalize",       # Phase 9: final result generation
)


def _new_uuid() -> str:
    return str(uuid.uuid4())


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class JobModel(Base):
    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    project_id: Mapped[str] = mapped_column(String(36), index=True, nullable=False)
    team_id: Mapped[str] = mapped_column(String(36), index=True, nullable=False)

    status: Mapped[str] = mapped_column(String(20), default="queued", nullable=False)
    progress: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    current_step: Mapped[str | None] = mapped_column(String(50), nullable=True)
    message: Mapped[str | None] = mapped_column(String(500), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    error_code: Mapped[str | None] = mapped_column(String(50), nullable=True)
    error_message: Mapped[str | None] = mapped_column(String(1000), nullable=True)

    # 各フェーズの保存関数が書き出したJSONファイルへのパス（未完了のステージはNone）
    requirements_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    tasks_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    dependencies_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    members_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    assignments_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    validation_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    result_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
