# backend/models/project.py
"""
Phase 10: チームが所有する「プロジェクト」(仕様書 + 確定済みメンバー情報)。

既存のDB(SQLite, backend/db/session.py)にテーブルを追加するだけで、
新しいDBシステムは導入しない。Phase 3-9のパイプライン自体はこのテーブルを
一切知らない（読み書きするのはbackend/routers/projects.pyとbackend/jobs/のみ）。
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone

from sqlalchemy import Date, DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from backend.db.base import Base


def _new_uuid() -> str:
    return str(uuid.uuid4())


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ProjectModel(Base):
    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    team_id: Mapped[str] = mapped_column(String(36), index=True, nullable=False)
    name: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Phase 3以降が入力として使う仕様書本文。アップロード機能(backend/services/parser.py)
    # は再利用するが、元のファイル自体は保存しない（テキストのみ保持する）。
    document_text: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Phase 6のMemberDirectoryをJSONファイルとして保存した場所
    # (backend.pipeline.members.runner.save_member_directory の戻り値のパス)。
    # メンバーのスキルレベルはここでも一切生成しない — 既存のPhase 6の
    # 取り込みロジックをそのまま経由してのみ設定される。
    members_path: Mapped[str | None] = mapped_column(String(500), nullable=True)

    # 納期考慮（任意）。どちらも未設定なら従来と同じ週ベースの計算になる。
    # start_date未設定時は、生成ジョブの実行日を計画の基準日とする。
    start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )
