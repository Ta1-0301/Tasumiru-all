// src/types/auth.ts
//
// チーム/招待/セッション認証APIに対応する型定義。
// バックエンド担当者から共有された「タスみる フロントエンド実装プロンプト」
// §6 の型定義に準拠している（実際に稼働しているバックエンドの実装が正）。

export interface Team {
  id: string;
  name: string;
}

export interface TeamMemberInfo {
  id: string;
  display_name: string;
  is_admin: boolean;
}

// GET /api/me, POST /api/teams, POST /api/invitations/{token}/join の
// レスポンスは全て同じ形（MeResponse）。
// チーム作成・参加はどちらもその場で HttpOnly Cookie セッションを発行する。
export interface MeResponse {
  team: Team;
  member: TeamMemberInfo;
}

export interface TeamCreateRequest {
  name: string;
  admin_display_name: string;
}

export interface InvitationCreateRequest {
  expires_in_hours?: number; // 省略時24
}

export interface InvitationCreateResponse {
  token: string;
  expires_at: string; // ISO8601
}

export interface JoinTeamRequest {
  display_name: string;
}

export interface SessionRefreshResponse {
  expires_at: string;
}

export interface ApiError {
  code: string;
  message: string;
}
