// src/api/auth.ts
//
// チーム作成・招待・参加・セッション確認/失効に関するAPI呼び出し関数群。
// 画面側(views)は axios を直接呼ばず、必ずこの層を経由する。
//
// 認可は全て HttpOnly Cookie セッション（axios の withCredentials）で
// 行われる。管理者操作（招待発行・メンバー削除）にヘッダートークンは
// 不要で、バックエンドがセッションの member.is_admin を見て判定する。
import { authApiClient } from "./client";
import type {
  InvitationCreateRequest,
  InvitationCreateResponse,
  JoinTeamRequest,
  MeResponse,
  SessionRefreshResponse,
  TeamCreateRequest,
  TeamMemberInfo,
} from "../types/auth";

export async function createTeam(body: TeamCreateRequest): Promise<MeResponse> {
  const { data } = await authApiClient.post<MeResponse>("/api/teams", body);
  return data;
}

export async function createInvitation(
  teamId: string,
  body: InvitationCreateRequest = {},
): Promise<InvitationCreateResponse> {
  const { data } = await authApiClient.post<InvitationCreateResponse>(
    `/api/teams/${teamId}/invitations`,
    body,
  );
  return data;
}

export async function joinTeam(
  token: string,
  body: JoinTeamRequest,
): Promise<MeResponse> {
  const { data } = await authApiClient.post<MeResponse>(
    `/api/invitations/${token}/join`,
    body,
  );
  return data;
}

export async function getMe(): Promise<MeResponse> {
  const { data } = await authApiClient.get<MeResponse>("/api/me");
  return data;
}

export async function refreshSession(): Promise<SessionRefreshResponse> {
  const { data } = await authApiClient.post<SessionRefreshResponse>(
    "/api/sessions/refresh",
  );
  return data;
}

export async function revokeSession(): Promise<void> {
  await authApiClient.post("/api/sessions/revoke");
}

export async function listTeamMembers(
  teamId: string,
): Promise<TeamMemberInfo[]> {
  const { data } = await authApiClient.get<TeamMemberInfo[]>(
    `/api/teams/${teamId}/members`,
  );
  return data;
}

export async function deleteMember(memberId: string): Promise<void> {
  await authApiClient.delete(`/api/members/${memberId}`);
}
