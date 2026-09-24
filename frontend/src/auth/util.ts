// src/auth/util.ts
import type { ApiError } from "../types/auth";

export function escapeHtml(value: string): string {
  const div = document.createElement("div");
  div.textContent = value;
  return div.innerHTML;
}

// 実装プロンプト §5.3 に記載のエラーコード一覧に基づく日本語メッセージ。
// 認証系の画面（作成・参加・チームメンバー管理）で共通して使う。
const AUTH_ERROR_MESSAGES: Record<string, string> = {
  UNAUTHENTICATED: "ログインが必要です。",
  SESSION_INVALID: "セッションが無効になりました。もう一度チームの作成/参加をやり直してください。",
  FORBIDDEN: "この操作には管理者権限が必要です。",
  NOT_FOUND: "指定されたリソースが見つかりません。",
  TEAM_NOT_FOUND: "チームが見つかりません。",
  MEMBER_NOT_FOUND: "メンバーが見つかりません。",
  INVITATION_NOT_FOUND: "この招待URLは無効です。発行者に再度URLを発行してもらってください。",
  INVITATION_REVOKED: "この招待URLは無効化されています。",
  INVITATION_EXPIRED: "この招待URLの有効期限が切れています。",
  CANNOT_REMOVE_SELF: "自分自身を削除することはできません。",
  LAST_ADMIN: "チーム最後の管理者は削除できません。",
  RATE_LIMITED: "試行回数が上限に達しました。しばらく待ってから再度お試しください。",
  NETWORK_ERROR: "バックエンドに接続できませんでした。サーバーの起動を確認してください。",
};

export function mapAuthError(err: ApiError, fallback: string): string {
  return AUTH_ERROR_MESSAGES[err.code] || err.message || fallback;
}
