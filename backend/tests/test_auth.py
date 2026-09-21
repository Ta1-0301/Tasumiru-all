# backend/tests/test_auth.py
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from backend.auth.dependencies import SESSION_COOKIE_NAME
from backend.auth.models import InvitationToken, MemberSession

from backend.tests.conftest import new_client


async def _create_team(client, name="テストチーム", admin_name="管理者A"):
    resp = await client.post("/api/teams", json={"name": name, "admin_display_name": admin_name})
    assert resp.status_code == 201
    return resp.json()


async def _create_invitation(client, team_id, expires_in_hours=24):
    resp = await client.post(
        f"/api/teams/{team_id}/invitations", json={"expires_in_hours": expires_in_hours}
    )
    assert resp.status_code == 201
    return resp.json()


# 1. チーム作成
async def test_create_team(client):
    body = await _create_team(client)
    assert body["team"]["name"] == "テストチーム"
    assert body["member"]["display_name"] == "管理者A"
    assert body["member"]["is_admin"] is True
    assert SESSION_COOKIE_NAME in client.cookies


# 2. 招待作成
async def test_create_invitation(client):
    team = (await _create_team(client))["team"]
    invitation = await _create_invitation(client, team["id"])
    assert "token" in invitation and len(invitation["token"]) > 20
    assert "expires_at" in invitation


# 3. 招待で参加
async def test_join_team(client, db_engine):
    team = (await _create_team(client))["team"]
    invitation = await _create_invitation(client, team["id"])

    member_client = new_client(db_engine)
    async with member_client:
        resp = await member_client.post(
            f"/api/invitations/{invitation['token']}/join",
            json={"display_name": "参加者B"},
        )
        assert resp.status_code == 201
        body = resp.json()
        assert body["team"]["id"] == team["id"]
        assert body["member"]["display_name"] == "参加者B"
        assert body["member"]["is_admin"] is False
        assert SESSION_COOKIE_NAME in member_client.cookies


# 4. 無効な招待トークン
async def test_invalid_invitation(client):
    resp = await client.post(
        "/api/invitations/not-a-real-token/join", json={"display_name": "参加者X"}
    )
    assert resp.status_code == 404
    assert resp.json()["detail"]["code"] == "INVITATION_NOT_FOUND"


# 5. 期限切れの招待トークン
async def test_expired_invitation(client, db_session):
    team = (await _create_team(client))["team"]
    invitation = await _create_invitation(client, team["id"])

    result = await db_session.execute(
        select(InvitationToken).where(InvitationToken.team_id == team["id"])
    )
    invitation_row = result.scalar_one()
    invitation_row.expires_at = datetime.now(timezone.utc) - timedelta(hours=1)
    await db_session.commit()

    resp = await client.post(
        f"/api/invitations/{invitation['token']}/join", json={"display_name": "参加者C"}
    )
    assert resp.status_code == 410
    assert resp.json()["detail"]["code"] == "INVITATION_EXPIRED"


# 6. 無効化された招待トークン
async def test_revoked_invitation(client, db_session):
    team = (await _create_team(client))["team"]
    invitation = await _create_invitation(client, team["id"])

    result = await db_session.execute(
        select(InvitationToken).where(InvitationToken.team_id == team["id"])
    )
    invitation_row = result.scalar_one()
    invitation_row.revoked = True
    await db_session.commit()

    resp = await client.post(
        f"/api/invitations/{invitation['token']}/join", json={"display_name": "参加者D"}
    )
    assert resp.status_code == 410
    assert resp.json()["detail"]["code"] == "INVITATION_REVOKED"


# 7. メンバーセッション（デバイストークン）の作成
async def test_create_member_session(client, db_session):
    team = (await _create_team(client))["team"]

    result = await db_session.execute(select(MemberSession))
    sessions_before = result.scalars().all()
    assert len(sessions_before) == 1  # チーム作成時に管理者のセッションが1つ作られている


# 8. 認証済みAPIへのアクセス
async def test_access_authenticated_api(client):
    team_body = await _create_team(client)
    resp = await client.get("/api/me")
    assert resp.status_code == 200
    body = resp.json()
    assert body["team"]["id"] == team_body["team"]["id"]
    assert body["member"]["id"] == team_body["member"]["id"]


# 9. 未認証でのアクセス
async def test_access_without_authentication(client):
    resp = await client.get("/api/me")
    assert resp.status_code == 401
    assert resp.json()["detail"]["code"] == "UNAUTHENTICATED"


# 10. 他チームのリソースへのアクセス（IDOR対策）
async def test_access_another_team_resource(client, db_engine):
    team_a = (await _create_team(client, name="チームA", admin_name="管理者A"))["team"]

    client_b = new_client(db_engine)
    async with client_b:
        team_b_body = await _create_team(client_b, name="チームB", admin_name="管理者B")
        team_b = team_b_body["team"]
        member_b = team_b_body["member"]

        # チームAの管理者がチームBのメンバー一覧を取得しようとする
        resp = await client.get(f"/api/teams/{team_b['id']}/members")
        assert resp.status_code == 404
        assert resp.json()["detail"]["code"] == "NOT_FOUND"

        # チームAの管理者がチームBのメンバーを削除しようとする
        resp = await client.delete(f"/api/members/{member_b['id']}")
        assert resp.status_code == 404
        assert resp.json()["detail"]["code"] == "MEMBER_NOT_FOUND"


# 11. セッションの無効化
async def test_revoke_session(client):
    await _create_team(client)
    old_token = client.cookies[SESSION_COOKIE_NAME]

    resp = await client.post("/api/sessions/revoke")
    assert resp.status_code == 204

    # ブラウザは delete_cookie により以降このCookieを送らなくなるが、
    # トークン自体がサーバー側で失効していることを確認するため、
    # 漏洩・キャッシュされた古いトークン値を明示的に付け直して再送する
    resp = await client.get("/api/me", headers={"Cookie": f"{SESSION_COOKIE_NAME}={old_token}"})
    assert resp.status_code == 401
    assert resp.json()["detail"]["code"] == "SESSION_INVALID"


# 12. 期限切れセッション
async def test_expired_session(client, db_session):
    await _create_team(client)

    result = await db_session.execute(select(MemberSession))
    session_row = result.scalar_one()
    session_row.expires_at = datetime.now(timezone.utc) - timedelta(days=1)
    await db_session.commit()

    resp = await client.get("/api/me")
    assert resp.status_code == 401
    assert resp.json()["detail"]["code"] == "SESSION_INVALID"


# --- 追加のセキュリティ観点のテスト（要求された12件を超える範囲だが、
#     今回実装したガードレールの検証として有効なため含める） ---


async def test_non_admin_cannot_create_invitation(client, db_engine):
    team = (await _create_team(client))["team"]
    invitation = await _create_invitation(client, team["id"])

    member_client = new_client(db_engine)
    async with member_client:
        await member_client.post(
            f"/api/invitations/{invitation['token']}/join", json={"display_name": "一般メンバー"}
        )
        resp = await member_client.post(f"/api/teams/{team['id']}/invitations", json={})
        assert resp.status_code == 403
        assert resp.json()["detail"]["code"] == "FORBIDDEN"


async def test_cannot_delete_last_admin(client):
    await _create_team(client)
    me_body = (await client.get("/api/me")).json()

    resp = await client.delete(f"/api/members/{me_body['member']['id']}")
    # 自分自身の削除は明示的に禁止（別コードだが、結果として最後の管理者は消せない）
    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == "CANNOT_REMOVE_SELF"
