// src/api/client.ts
//
// チーム/認証系APIのための axios クライアント。
// 既存の /api/tasks, /api/settings は app.ts が直接 fetch() で呼んでおり、
// 既存動作を壊さないためそちらには手を入れない。今回追加するチーム認証
// 機能はこのクライアントを経由してのみバックエンドと通信する。
import axios, { AxiosError } from "axios";
import type { ApiError } from "../types/auth";

// 【重要】baseURL はあえて相対パス（空文字）にしている。
// フロントとバックエンドが別ホスト（例: Mac B / Mac A）の場合、
// バックエンドが発行する Cookie は SameSite=Lax のため、ブラウザは
// クロスサイトの fetch/XHR にそのCookieを付与しない
// （= チーム作成直後の招待発行など、認証が必要な直後の呼び出しが
// サイレントに失敗する）。vite.config.ts 側の開発サーバープロキシで
// `/api` をバックエンドへ中継し、ブラウザから見て常に同一オリジンに
// なるようにすることでこれを回避している。
const API_BASE_URL = import.meta.env.VITE_AUTH_API_BASE_URL ?? "";

export const authApiClient = axios.create({
  baseURL: API_BASE_URL,
  // バックエンドが HttpOnly Cookie でメンバーセッションを発行する前提のため、
  // 常に Cookie を送受信できるようにする（JS側からセッショントークン自体は
  // 一切参照しない）
  withCredentials: true,
});

// 【Phase 10.5】チーム/招待/セッションだけでなく、プロジェクト・メンバー・
// 生成ジョブ（/api/projects*, /api/jobs*）も含め、Cookieセッションを必要と
// する全てのバックエンド通信は必ずこの単一の axios インスタンスを経由する
// （ページ・ビューが axios を直接呼ぶことはない）。同じインスタンスに
// 別名を与えているだけで、実体・設定（baseURL・withCredentials・
// インターセプター）は上の authApiClient と完全に同一。
export const apiClient = authApiClient;

// セッションが無効になったこと（他デバイスでの失効・自然な期限切れなど）を
// 検知した際に呼び出すハンドラ。router.ts が起動時に一度だけ登録し、
// ダッシュボード表示中にどの画面でAPI呼び出しが失敗しても、確実に
// チーム作成/参加画面へ戻すために使う（循環importを避けるため、
// ここではルーティングの詳細を知らずコールバックだけを保持する）。
let sessionInvalidHandler: (() => void) | null = null;

export function setSessionInvalidHandler(handler: () => void): void {
  sessionInvalidHandler = handler;
}

// バックエンドが実際に返すことを統合テストで確認したコード
// （SESSION_INVALID: セッション失効後の再アクセス, UNAUTHENTICATED: 未ログイン）
const SESSION_INVALID_CODES = new Set(["SESSION_INVALID", "UNAUTHENTICATED"]);

authApiClient.interceptors.response.use(
  (res) => res,
  (err: AxiosError<{ detail?: ApiError }>) => {
    const detail = err.response?.data?.detail;
    if (detail?.code && SESSION_INVALID_CODES.has(detail.code)) {
      sessionInvalidHandler?.();
    }
    if (detail) return Promise.reject(detail);

    // err.response が無い = ブラウザがレスポンスを一切渡してくれなかったケース。
    // ブラウザの仕様上、「本当にサーバーへ到達できなかった」のか
    // 「サーバーはクラッシュして500を返したが、CORSヘッダーが付いておらず
    // ブラウザがブロックした」のかをJS側からは区別できない（実際に統合テストで
    // 後者を確認済み: 通常のエラー応答にはCORSヘッダーが付くが、未処理の
    // 例外による500応答には付かないことがある）。そのため両方の可能性を
    // 案内するメッセージにする。
    const message =
      err.code === "ECONNABORTED"
        ? "サーバーからの応答がタイムアウトしました。"
        : "バックエンドに接続できませんでした。サーバーが起動していないか、" +
          "サーバー内部でエラーが発生してCORSヘッダーが返っていない可能性が" +
          "あります（後者の場合、ブラウザの開発者ツールのConsoleタブに" +
          "CORSエラーの詳細が表示されます。管理者に確認してください）。";

    return Promise.reject({
      code: "NETWORK_ERROR",
      message,
    } as ApiError);
  },
);
