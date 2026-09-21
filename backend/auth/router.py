# backend/auth/router.py
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import delete as sa_delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.auth.dependencies import (
    SESSION_COOKIE_NAME,
    get_current_admin,
    get_current_member,
    require_same_team,
)
from backend.auth.middleware import rate_limit_invitation_join
from backend.auth.models import InvitationToken, MemberSession, Team, TeamMember
from backend.auth.schemas import (
    InvitationCreateRequest,
    InvitationCreateResponse,
    JoinTeamRequest,
    MeResponse,
    SessionRefreshResponse,
    TeamCreateRequest,
    TeamMemberResponse,
    TeamResponse,
)
from backend.auth.token_service import ensure_utc, generate_token, hash_token
from backend.config import settings
from backend.db.session import get_db

router = APIRouter(prefix="/api", tags=["auth"])

SESSION_TTL = timedelta(days=30)


def _set_session_cookie(response: Response, raw_token: str, expires_at: datetime) -> None:
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=raw_token,
        httponly=True,
        secure=settings.COOKIE_SECURE,
        samesite=settings.COOKIE_SAMESITE,
        expires=expires_at,
        path="/",
    )


async def _create_session(db: AsyncSession, member: TeamMember) -> tuple[str, datetime]:
    raw_token = generate_token()
    expires_at = datetime.now(timezone.utc) + SESSION_TTL
    db.add(
        MemberSession(
            member_id=member.id,
            token_hash=hash_token(raw_token),
            expires_at=expires_at,
        )
    )
    await db.flush()
    return raw_token, expires_at


def _me_response(team: Team, member: TeamMember) -> MeResponse:
    return MeResponse(
        team=TeamResponse.model_validate(team),
        member=TeamMemberResponse.model_validate(member),
    )


@router.post("/teams", response_model=MeResponse, status_code=201)
async def create_team(
    body: TeamCreateRequest,
    response: Response,
    db: AsyncSession = Depends(get_db),
):
    """チームを作成し、作成者を管理者メンバーとして登録した上でセッションを発行する"""
    team = Team(name=body.name)
    db.add(team)
    await db.flush()

    admin = TeamMember(team_id=team.id, display_name=body.admin_display_name, is_admin=True)
    db.add(admin)
    await db.flush()

    raw_token, expires_at = await _create_session(db, admin)
    _set_session_cookie(response, raw_token, expires_at)

    await db.commit()
    return _me_response(team, admin)


@router.post("/teams/{team_id}/invitations", response_model=InvitationCreateResponse, status_code=201)
async def create_invitation(
    team_id: str,
    body: InvitationCreateRequest,
    db: AsyncSession = Depends(get_db),
    admin: TeamMember = Depends(get_current_admin),
):
    """招待トークンを発行する（対象チームの管理者のみ実行できる）"""
    require_same_team(team_id, admin)

    raw_token = generate_token()
    expires_at = datetime.now(timezone.utc) + timedelta(hours=body.expires_in_hours)

    db.add(
        InvitationToken(
            team_id=team_id,
            token_hash=hash_token(raw_token),
            expires_at=expires_at,
        )
    )

    await db.commit()
    return InvitationCreateResponse(token=raw_token, expires_at=expires_at)


@router.post("/invitations/{token}/join", response_model=MeResponse, status_code=201)
async def join_team(
    token: str,
    body: JoinTeamRequest,
    response: Response,
    db: AsyncSession = Depends(get_db),
    _rate_limit: None = Depends(rate_limit_invitation_join),
):
    """招待トークンでチームに参加し、新しいメンバーとデバイスセッションを作成する"""
    token_hash = hash_token(token)
    result = await db.execute(
        select(InvitationToken).where(InvitationToken.token_hash == token_hash)
    )
    invitation = result.scalar_one_or_none()

    now = datetime.now(timezone.utc)
    if invitation is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "INVITATION_NOT_FOUND", "message": "招待リンクが無効です。"},
        )
    if invitation.revoked:
        raise HTTPException(
            status_code=410,
            detail={"code": "INVITATION_REVOKED", "message": "この招待リンクは無効化されています。"},
        )
    if ensure_utc(invitation.expires_at) < now:
        raise HTTPException(
            status_code=410,
            detail={"code": "INVITATION_EXPIRED", "message": "この招待リンクは期限切れです。"},
        )

    team = await db.get(Team, invitation.team_id)
    if team is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "TEAM_NOT_FOUND", "message": "招待先のチームが見つかりません。"},
        )

    member = TeamMember(team_id=team.id, display_name=body.display_name, is_admin=False)
    db.add(member)
    await db.flush()

    raw_session_token, expires_at = await _create_session(db, member)
    _set_session_cookie(response, raw_session_token, expires_at)

    await db.commit()
    return _me_response(team, member)


@router.post("/sessions/refresh", response_model=SessionRefreshResponse)
async def refresh_session(
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
    member: TeamMember = Depends(get_current_member),
):
    """有効なセッションをローテーションし、有効期限を延長する"""
    old_raw_token = request.cookies.get(SESSION_COOKIE_NAME)
    if old_raw_token:
        old_token_hash = hash_token(old_raw_token)
        result = await db.execute(
            select(MemberSession).where(MemberSession.token_hash == old_token_hash)
        )
        old_session = result.scalar_one_or_none()
        if old_session:
            old_session.revoked = True

    raw_token, expires_at = await _create_session(db, member)
    _set_session_cookie(response, raw_token, expires_at)

    await db.commit()
    return SessionRefreshResponse(expires_at=expires_at)


@router.post("/sessions/revoke", status_code=204)
async def revoke_session(
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
):
    """現在のデバイス/セッションを無効化する（ログアウト）"""
    raw_token = request.cookies.get(SESSION_COOKIE_NAME)
    if raw_token:
        token_hash = hash_token(raw_token)
        result = await db.execute(
            select(MemberSession).where(MemberSession.token_hash == token_hash)
        )
        session = result.scalar_one_or_none()
        if session:
            session.revoked = True
            await db.commit()

    response.delete_cookie(SESSION_COOKIE_NAME, path="/")


@router.get("/me", response_model=MeResponse)
async def get_me(
    member: TeamMember = Depends(get_current_member),
    db: AsyncSession = Depends(get_db),
):
    team = await db.get(Team, member.team_id)
    if team is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "TEAM_NOT_FOUND", "message": "チームが見つかりません。"},
        )
    return _me_response(team, member)


@router.get("/teams/{team_id}/members", response_model=list[TeamMemberResponse])
async def list_members(
    team_id: str,
    db: AsyncSession = Depends(get_db),
    member: TeamMember = Depends(get_current_member),
):
    """チームメンバー一覧を取得する（自チーム以外は404）"""
    require_same_team(team_id, member)
    result = await db.execute(select(TeamMember).where(TeamMember.team_id == team_id))
    members = result.scalars().all()
    return [TeamMemberResponse.model_validate(m) for m in members]


@router.delete("/members/{member_id}", status_code=204)
async def delete_member(
    member_id: str,
    db: AsyncSession = Depends(get_db),
    admin: TeamMember = Depends(get_current_admin),
):
    """チームメンバーを削除する（管理者のみ・自チームのメンバーのみ）"""
    if member_id == admin.id:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "CANNOT_REMOVE_SELF",
                "message": "自分自身を削除することはできません。セッションの無効化を利用してください。",
            },
        )

    target = await db.get(TeamMember, member_id)
    if target is None or target.team_id != admin.team_id:
        # 他チームのメンバーIDを推測されても存在有無を漏らさない
        raise HTTPException(
            status_code=404,
            detail={"code": "MEMBER_NOT_FOUND", "message": "メンバーが見つかりません。"},
        )

    if target.is_admin:
        result = await db.execute(
            select(TeamMember).where(
                TeamMember.team_id == admin.team_id, TeamMember.is_admin.is_(True)
            )
        )
        if len(result.scalars().all()) <= 1:
            raise HTTPException(
                status_code=400,
                detail={"code": "LAST_ADMIN", "message": "チームの最後の管理者は削除できません。"},
            )

    await db.execute(sa_delete(MemberSession).where(MemberSession.member_id == target.id))
    await db.delete(target)
    await db.commit()
