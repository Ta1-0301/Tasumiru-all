# backend/auth/dependencies.py
"""
FastAPIのDependsから使う認証系の依存関数。
ビジネスロジック側は「現在のメンバー/チーム」だけを受け取り、
トークンの検証方法（Cookie・ハッシュ照合など）を知る必要がないようにする。
"""

from datetime import datetime, timezone

from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.auth.models import MemberSession, TeamMember
from backend.auth.token_service import ensure_utc, hash_token
from backend.db.session import get_db

SESSION_COOKIE_NAME = "tasumiru_session"


async def get_current_member(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> TeamMember:
    """Cookieのセッショントークンを検証し、現在のメンバーを返す"""
    raw_token = request.cookies.get(SESSION_COOKIE_NAME)
    if not raw_token:
        raise HTTPException(
            status_code=401,
            detail={"code": "UNAUTHENTICATED", "message": "ログインが必要です。"},
        )

    token_hash = hash_token(raw_token)
    result = await db.execute(
        select(MemberSession).where(MemberSession.token_hash == token_hash)
    )
    session = result.scalar_one_or_none()

    now = datetime.now(timezone.utc)
    if session is None or session.revoked or ensure_utc(session.expires_at) < now:
        raise HTTPException(
            status_code=401,
            detail={"code": "SESSION_INVALID", "message": "セッションが無効です。再度参加してください。"},
        )

    member = await db.get(TeamMember, session.member_id)
    if member is None:
        raise HTTPException(
            status_code=401,
            detail={"code": "SESSION_INVALID", "message": "セッションが無効です。"},
        )

    session.last_used_at = now
    await db.commit()

    return member


async def get_current_admin(
    member: TeamMember = Depends(get_current_member),
) -> TeamMember:
    """現在のメンバーがチーム管理者であることを要求する"""
    if not member.is_admin:
        raise HTTPException(
            status_code=403,
            detail={"code": "FORBIDDEN", "message": "管理者権限が必要です。"},
        )
    return member


def require_same_team(team_id: str, member: TeamMember) -> None:
    """
    パスパラメータのteam_idが現在のメンバーの所属チームと一致するか検証する（IDOR対策）。
    他チームのリソースであることを教えないため、403ではなく404を返す。
    """
    if member.team_id != team_id:
        raise HTTPException(
            status_code=404,
            detail={"code": "NOT_FOUND", "message": "リソースが見つかりません。"},
        )
