// src/specToTasks/entry.ts
//
// index.html のエントリーポイント。認証の流れは src/auth/router.ts と同じ:
//   - ?token=... があれば招待参加ページ
//   - GET /api/me が成功すれば Spec to Tasks 画面
//   - 失敗すればチーム作成ページ（VITE_DEMO_MODE=true の場合のみサンプル結果で表示）
import { getMe, refreshSession } from "../api/auth";
import { setSessionInvalidHandler } from "../api/client";
import { getCurrentAuth, setCurrentAuth } from "../auth/session";
import { renderJoinView } from "../views/joinView";
import { renderTeamCreateView } from "../views/teamCreateView";
import { renderTeamMembersView } from "../views/teamMembersView";
import type { Team, TeamMemberInfo } from "../types/auth";
import { mountSpecToTasks } from "./app";

type Auth = { team: Team; member: TeamMemberInfo };

const DEMO_MODE_ENABLED = import.meta.env.VITE_DEMO_MODE === "true";
const DEMO_BOOTSTRAP_TIMEOUT_MS = 4000;

const $ = (id: string) => document.getElementById(id) as HTMLElement;
let dashboardActive = false;

function hideAll(): void {
  ["s2t-root", "screen-team-create", "screen-join", "team-overlay"].forEach((id) => {
    const el = document.getElementById(id);
    if (el) el.style.display = "none";
  });
}

function showAuthScreen(kind: "create" | "join", token?: string): void {
  dashboardActive = false;
  hideAll();
  if (kind === "create") {
    $("screen-team-create").style.display = "block";
    renderTeamCreateView($("screen-team-create"), handleJoined);
  } else if (token) {
    $("screen-join").style.display = "block";
    renderJoinView($("screen-join"), token, handleJoined);
  }
}

function openTeamOverlay(): void {
  const overlay = $("team-overlay");
  const body = $("team-overlay-body");
  overlay.style.display = "grid";
  renderTeamMembersView(body, () => {
    overlay.style.display = "none";
    handleSignedOut();
  });
}

function showApp(auth: Auth, demo = false): void {
  dashboardActive = true;
  setCurrentAuth(auth);
  hideAll();
  $("s2t-root").style.display = "block";
  $("demo-mode-banner").style.display = demo ? "block" : "none";
  mountSpecToTasks($("s2t-root"), {
    userLabel: `${auth.team.name} · ${auth.member.display_name}`,
    demo,
    onTeam: openTeamOverlay,
  });
}

function handleJoined(auth: Auth): void {
  history.pushState({}, "", "/");
  showApp(auth);
}

function handleSignedOut(): void {
  setCurrentAuth(null);
  history.pushState({}, "", "/");
  // 画面の状態（別チームのプロジェクト等）を持ち越さないよう再読み込みする
  location.reload();
}

setSessionInvalidHandler(() => {
  if (dashboardActive) handleSignedOut();
});

function withTimeout<T>(p: Promise<T>, ms: number): Promise<T> {
  return new Promise<T>((resolve, reject) => {
    const t = setTimeout(() => reject(new Error("TIMEOUT")), ms);
    p.then((v) => { clearTimeout(t); resolve(v); }, (e) => { clearTimeout(t); reject(e); });
  });
}

async function bootstrap(): Promise<void> {
  $("team-overlay").addEventListener("click", (e) => {
    const t = e.target as HTMLElement;
    if (t.id === "team-overlay" || t.closest("[data-close-overlay]")) $("team-overlay").style.display = "none";
  });

  const token = new URLSearchParams(location.search).get("token");
  if (token) {
    showAuthScreen("join", token);
    return;
  }
  try {
    const me = DEMO_MODE_ENABLED ? await withTimeout(getMe(), DEMO_BOOTSTRAP_TIMEOUT_MS) : await getMe();
    refreshSession().catch(() => { /* セッション延長はベストエフォート */ });
    showApp(me);
  } catch {
    if (DEMO_MODE_ENABLED) {
      showApp({
        team: { id: "__demo__", name: "デモモード（バックエンド未接続）" },
        member: { id: "__demo__", display_name: "ゲスト（デモ）", is_admin: false },
      }, true);
      return;
    }
    showAuthScreen("create");
  }
}

window.addEventListener("popstate", () => {
  const token = new URLSearchParams(location.search).get("token");
  if (token) return showAuthScreen("join", token);
  const auth = getCurrentAuth();
  if (auth) showApp(auth);
  else showAuthScreen("create");
});

document.addEventListener("DOMContentLoaded", () => {
  bootstrap();
});
