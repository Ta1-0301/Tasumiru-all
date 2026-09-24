import { defineConfig, loadEnv } from 'vite';

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '');
  // 認証系API（Cookieセッション）は、フロントとバックエンドが別ホストだと
  // SameSite=Lax の Cookie がクロスサイトのXHR/fetchでは送信されないため、
  // 開発サーバーのプロキシで同一オリジンに見せかけて回避する。
  // BACKEND_PROXY_TARGET はサーバー側専用（VITE_ プレフィックスを付けず
  // クライアントバンドルには含めない）
  const backendTarget = env.BACKEND_PROXY_TARGET || 'http://localhost:8000';

  return {
    build: {
      rollupOptions: {
        input: {
          // Spec to Tasks 画面（バックエンド接続版。src/specToTasks/entry.ts）
          main: 'index.html',
          // 従来の画面（src/app.ts ほか）
          legacy: 'legacy.html',
          // Spec to Tasks のサンプルデータ版デモ（src/specToTasks/main.ts）
          specToTasks: 'spec-to-tasks.html',
        },
      },
    },
    server: {
      port: 5173,
      proxy: {
        '/api': {
          target: backendTarget,
          changeOrigin: true,
        },
      },
    },
  };
});
