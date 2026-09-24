// src/auth/session.ts
//
// 認証状態のクライアント側キャッシュ。
//
// メンバーの「セッション」自体はバックエンドが発行する HttpOnly Cookie で
// 管理されるため、このファイルはセッショントークンそのものには一切触れない
// （JSからは読めないし読む必要もない。axios 側は withCredentials: true で
// ブラウザに送受信を任せる）。
//
// 管理者操作（招待発行・メンバー削除）もセッションCookieだけで認可される
// （バックエンドが member.is_admin を判定する）ため、以前の版にあった
// 「チーム管理トークン」をここで別途キャッシュする仕組みは不要になった
// （統合テストで判明。詳細は AUTH_INTEGRATION_TEST.md 参照）。
import type { Team, TeamMemberInfo } from "../types/auth";

let currentAuthState: { team: Team; member: TeamMemberInfo } | null = null;

export function getCurrentAuth(): { team: Team; member: TeamMemberInfo } | null {
  return currentAuthState;
}

export function setCurrentAuth(
  auth: { team: Team; member: TeamMemberInfo } | null,
): void {
  currentAuthState = auth;
}
