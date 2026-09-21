# backend/auth/models.py
"""
チーム・デバイスセッション方式の認証データモデル。

概念:
  Team          : チーム（旧来のユーザーアカウントに相当するものは持たない）
  TeamMember    : チームに参加している人（表示名のみ。グローバルなユーザーではない）
  InvitationToken: チームへの招待リンクのトークン（ハッシュを保存）
  MemberSession : メンバーの端末ごとのセッション（ハッシュを保存）

NOTE: backend/models/member.py の MemberModel（タスク担当候補としてのスキル保有者）とは
      別概念のため、名前の衝突を避けて TeamMember という名前にしている。
      将来的にこの2つを統合するかどうかは別途検討する。
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from backend.db.base import Base


def _new_uuid() -> str:
    return str(uuid.uuid4())


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Team(Base):
    __tablename__ = "auth_teams"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )


class TeamMember(Base):
    __tablename__ = "auth_team_members"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    team_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("auth_teams.id"), index=True, nullable=False
    )
    display_name: Mapped[str] = mapped_column(String(100), nullable=False)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )


class InvitationToken(Base):
    __tablename__ = "auth_invitation_tokens"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    team_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("auth_teams.id"), index=True, nullable=False
    )
    # 生トークンは保存しない。SHA-256ハッシュのみDBに保存する。
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class MemberSession(Base):
    __tablename__ = "auth_member_sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    member_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("auth_team_members.id"), index=True, nullable=False
    )
    # 生トークンは保存しない。SHA-256ハッシュのみDBに保存する。
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    last_used_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
