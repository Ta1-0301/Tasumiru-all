/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_API_BASE_URL: string;
  // 未設定時は auth クライアントが相対パス（開発サーバープロキシ経由）を使う
  readonly VITE_AUTH_API_BASE_URL?: string;
  // フロントエンド単体デモ/開発モード。true かつバックエンド未接続時のみ、
  // auth/router.ts がダッシュボードをサンプルデータで表示する。
  // 本番の認証・認可ロジックは一切変更しない（詳細は auth/router.ts 参照）。
  readonly VITE_DEMO_MODE?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
