# backend/auth/schemas.py
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class TeamCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=255, description="チーム名")
    admin_display_name: str = Field(
        ..., min_length=1, max_length=100, description="作成者（管理者）の表示名"
    )


class TeamResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str


class TeamMemberResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    display_name: str
    is_admin: bool


class MeResponse(BaseModel):
    team: TeamResponse
    member: TeamMemberResponse


class InvitationCreateRequest(BaseModel):
    expires_in_hours: int = Field(24, ge=1, le=24 * 30, description="招待リンクの有効時間")


class InvitationCreateResponse(BaseModel):
    token: str = Field(..., description="招待トークン（この応答でのみ生の値が返される）")
    expires_at: datetime


class JoinTeamRequest(BaseModel):
    display_name: str = Field(..., min_length=1, max_length=100, description="参加者の表示名")


class SessionRefreshResponse(BaseModel):
    expires_at: datetime
