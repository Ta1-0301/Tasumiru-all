// src/auth/router.ts
//
// チーム認証機能のブートストラップ／簡易ルーター。
//
// 既存の app.ts（DOMContentLoaded で仕様書アップロード・カンバン等を初期化）
// には一切手を入れず、この独立したモジュールが同じ DOMContentLoaded に
// 相乗りして、以下だけを行う:
//   - URLクエリに ?token=... があれば → 参加ページを表示
//     （実装プロンプト §8.2 の方針に合わせ、パスルーティングは行わない）
//   - それ以外 → GET /api/me でセッションを確認し、有効なら既存の
//     app-shell（ダッシュボード）を表示、無効ならチーム作成ページを表示
//   - ダッシュボード表示後、サイドバーに新しい「チームメンバー」タブを追加
//
// ログインページは作らない（No traditional login page）。
//
// ── フロントエンド単体デモ/開発モード（Phase 10）──
// `VITE_DEMO_MODE=true` かつ GET /api/me が失敗した場合（＝バックエンド未接続）
// に限り、チーム作成画面の代わりにダッシュボードをローカルの
// ダミー認証情報で表示する。これにより、バックエンドが無い状態でも
// Phase 10 のパイプライン結果画面（サンプルデータ）を確認できる。
//
// 【重要・セキュリティ上の注意】
//   - この分岐は本番の認証・認可を一切変更しない。GET /api/me が実際に
//     成功する環境（＝バックエンドが動いている環境）では、この分岐は
//     一度も実行されない（既存の通常フローがそのまま使われる）。
//   - ダミー認証情報 (DEMO_AUTH) はこのモジュール内のローカル変数として
//     保持されるだけで、api/client.ts や api/auth.ts 経由でバックエンドへ
//     送信されることは一切ない（Cookieセッションは発行されない/使われない）。
//   - デモモード中に「チームメンバー」タブ等から実際にバックエンドAPIを
//     呼び出した場合は、通常通り認証エラー（401等）になる。デモモードが
//     バックエンドの権限チェックを迂回することはない。
//   - `VITE_DEMO_MODE` はデフォルト false（.env参照）。true にする場合は
//     個人のローカル環境（.env.local等、通常Git管理しない設定）でのみ
//     行うことを推奨する。
import { getMe, refreshSession } from "../api/auth";
import { setSessionInvalidHandler } from "../api/client";
import { getCurrentAuth, setCurrentAuth } from "./session";
import { escapeHtml } from "./util";
import { renderTeamCreateView } from "../views/teamCreateView";
import { renderJoinView } from "../views/joinView";
import { renderTeamMembersView } from "../views/teamMembersView";
import type { Team, TeamMemberInfo } from "../types/auth";

const EXISTING_NAV_IDS = [
  "nav-generate",
  "nav-tasklist",
  "nav-members",
  "nav-settings",
];

function els() {
  return {
    appShell: document.getElementById("app-shell"),
    teamCreateScreen: document.getElementById("screen-team-create"),
    joinScreen: document.getElementById("screen-join"),
    teamScreen: document.getElementById("screen-team"),
    navTeamBtn: document.getElementById("nav-team"),
    sidebarBadge: document.getElementById("sidebar-team-badge"),
    demoModeBanner: document.getElementById("demo-mode-banner"),
  };
}

const DEMO_MODE_ENABLED = import.meta.env.VITE_DEMO_MODE === "true";

// バックエンドへは一切送信されないローカル専用のダミー値。
// 実際のチームID/メンバーIDと衝突しないよう、明らかにデモ用と分かる値にしている。
const DEMO_AUTH: { team: Team; member: TeamMemberInfo } = {
  team: { id: "__demo__", name: "デモモード（バックエンド未接続）" },
  member: { id: "__demo__", display_name: "ゲスト（デモ）", is_admin: false },
};

// ダッシュボードを表示中かどうか。SESSION_INVALID の多重ハンドリング防止に使う
// （後述の setSessionInvalidHandler 参照）
let dashboardActive = false;

function showAuthScreen(kind: "create" | "join", token?: string): void {
  dashboardActive = false;
  const { appShell, teamCreateScreen, joinScreen, demoModeBanner } = els();
  if (appShell) appShell.style.display = "none";
  document.body.classList.remove("demo-mode-active");
  if (demoModeBanner) demoModeBanner.style.display = "none";

  if (teamCreateScreen) {
    teamCreateScreen.style.display = kind === "create" ? "block" : "none";
  }
  if (joinScreen) {
    joinScreen.style.display = kind === "join" ? "block" : "none";
  }

  if (kind === "create" && teamCreateScreen) {
    // チーム作成はその場でセッションが発行される（統合テストで確認済み）ため、
    // 参加ページへの誘導は不要。作成完了 = 認証済み扱いで直接ダッシュボードへ
    renderTeamCreateView(teamCreateScreen, handleJoined);
  } else if (kind === "join" && joinScreen && token) {
    renderJoinView(joinScreen, token, handleJoined);
  }
}

function showDashboard(auth: { team: Team; member: TeamMemberInfo }, isDemo = false): void {
  dashboardActive = true;
  setCurrentAuth(auth);
  const { appShell, teamCreateScreen, joinScreen, demoModeBanner } = els();
  if (teamCreateScreen) teamCreateScreen.style.display = "none";
  if (joinScreen) joinScreen.style.display = "none";
  // .app-shell は CSS 側で display: flex が指定されているため、その値に戻す
  if (appShell) appShell.style.display = "flex";

  document.body.classList.toggle("demo-mode-active", isDemo);
  if (demoModeBanner) demoModeBanner.style.display = isDemo ? "block" : "none";

  updateSidebarBadge(auth);
}

// VITE_DEMO_MODE=true かつバックエンド未接続（GET /api/me 失敗）の時だけ、
// bootstrap() の catch から呼ばれる。本番の認証状態は一切変更しない
// （setCurrentAuth に渡るのはローカル限定の DEMO_AUTH のみ）。
function showDemoDashboard(): void {
  showDashboard(DEMO_AUTH, true);
}

function updateSidebarBadge(auth: { team: Team; member: TeamMemberInfo }): void {
  const { sidebarBadge } = els();
  if (!sidebarBadge) return;
  sidebarBadge.style.display = "flex";
  sidebarBadge.innerHTML = `
    <div class="sidebar-team-name">${escapeHtml(auth.team.name)}</div>
    <div class="sidebar-member-name">${escapeHtml(auth.member.display_name)}</div>
  `;
}

function handleJoined(auth: { team: Team; member: TeamMemberInfo }): void {
  history.pushState({}, "", "/");
  showDashboard(auth);
}

function handleSignedOut(): void {
  setCurrentAuth(null);
  history.pushState({}, "", "/");
  showAuthScreen("create");
}

// 既存の4つのナビ項目には手を加えず、それらがクリックされたときだけ
// 新しい「チームメンバー」タブの選択状態を解除する（app.ts 側の
// setupNavigation とは独立して動く、後付けの軽いリスナー）
function setupTeamNav(): void {
  const { navTeamBtn, teamScreen } = els();
  if (!navTeamBtn || !teamScreen) return;

  navTeamBtn.addEventListener("click", () => {
    document
      .querySelectorAll(".sidebar-nav-item")
      .forEach((el) => el.classList.remove("active"));
    navTeamBtn.classList.add("active");

    document.querySelectorAll(".screen-view").forEach((el) => {
      (el as HTMLElement).style.display =
        el.id === "screen-team" ? "block" : "none";
    });

    const auth = getCurrentAuth();
    if (auth) {
      renderTeamMembersView(teamScreen, handleSignedOut);
    }
  });

  EXISTING_NAV_IDS.forEach((id) => {
    document.getElementById(id)?.addEventListener("click", () => {
      navTeamBtn.classList.remove("active");
    });
  });
}

function currentJoinToken(): string | null {
  return new URLSearchParams(window.location.search).get("token");
}

// デモモードでのみ使う起動時タイムアウト。「バックエンド未接続」には
// 即座に接続拒否される場合（何も起動していないlocalhost等）だけでなく、
// 到達不能なホスト（例: 開発者の.envに残った他マシンのIP）にパケットが
// 黙って落とされ、TCP接続の確立自体が長時間ハングするケースもある。
// authApiClient にはリクエストタイムアウトが設定されていないため
// （本番動作を変えないためここでは変更しない）、デモモード時に限り
// この関数で起動シーケンスだけを打ち切り、確実に一定時間内に
// ダッシュボード（サンプルデータ）へフォールバックできるようにする。
// 実際の getMe() 呼び出し自体は裏で継続してよく、後から解決/拒否されても
// 何も購読していないため無視される（未処理拒否にはならないよう、この
// 関数内で必ず then/catch している）。
const DEMO_MODE_BOOTSTRAP_TIMEOUT_MS = 4000;

function withTimeout<T>(promise: Promise<T>, ms: number): Promise<T> {
  return new Promise<T>((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error("DEMO_MODE_BOOTSTRAP_TIMEOUT")), ms);
    promise.then(
      (value) => {
        clearTimeout(timer);
        resolve(value);
      },
      (err) => {
        clearTimeout(timer);
        reject(err);
      },
    );
  });
}

// バックエンド統合テストで確認済みの挙動: セッションは失効しても
// チームからメンバーが削除されるわけではない（別デバイスからの revoke や
// 自然な期限切れで、今見ているセッションだけが無効になることがある）。
// ダッシュボード表示中にどのAPI呼び出しが SESSION_INVALID / UNAUTHENTICATED
// を受け取っても、確実にチーム作成/参加画面へ戻す。
// dashboardActive で、初回ブートストラップ時の「まだログインしていないだけ」
// のケースと区別し、showAuthScreen("create") の二重呼び出しを避ける。
setSessionInvalidHandler(() => {
  if (!dashboardActive) return;
  handleSignedOut();
});

async function bootstrap(): Promise<void> {
  setupTeamNav();

  const joinToken = currentJoinToken();
  if (joinToken) {
    showAuthScreen("join", joinToken);
    return;
  }

  try {
    // デモモード時のみタイムアウトを課す（本番の挙動・タイムアウト仕様は
    // 一切変更しない。DEMO_MODE_ENABLED が false の分岐は従来通り await getMe()）。
    const me = DEMO_MODE_ENABLED ? await withTimeout(getMe(), DEMO_MODE_BOOTSTRAP_TIMEOUT_MS) : await getMe();
    refreshSession().catch(() => {
      /* セッション延長はベストエフォート */
    });
    showDashboard(me);
  } catch {
    // バックエンド未接続時、デモモードが有効ならダッシュボードをサンプル
    // データで表示する。無効なら既存通りチーム作成画面へ（本番の挙動）。
    if (DEMO_MODE_ENABLED) {
      showDemoDashboard();
      return;
    }
    showAuthScreen("create");
  }
}

window.addEventListener("popstate", () => {
  const joinToken = currentJoinToken();
  if (joinToken) {
    showAuthScreen("join", joinToken);
    return;
  }
  const auth = getCurrentAuth();
  if (auth) {
    showDashboard(auth);
  } else {
    showAuthScreen("create");
  }
});

document.addEventListener("DOMContentLoaded", () => {
  bootstrap();
});
