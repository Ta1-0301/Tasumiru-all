// // app.ts

// interface Member {
//   id: string;
//   name: string;
//   skills: string[];
//   load_pct: number;
// }

// interface Task {
//   task_id: string;
//   title: string;
//   assignee: string;
//   skill_required: string;
//   priority: "high" | "medium" | "low";
//   deadline: string | null;
//   source_section: string;
//   load_pct: number;
//   status: "todo" | "doing" | "done" | null; // 初期状態は null (カンバン未登録)
// }

// let members: Member[] = [
//   { id: "m1", name: "田中 一郎", skills: ["Python", "FastAPI"], load_pct: 40 },
//   {
//     id: "m2",
//     name: "佐藤 花子",
//     skills: ["HTML", "CSS", "TypeScript"],
//     load_pct: 60,
//   },
//   {
//     id: "m3",
//     name: "鈴木 次郎",
//     skills: ["scikit-learn", "Python"],
//     load_pct: 20,
//   },
// ];

// // 初期モックタスク
// let generatedTasks: Task[] = [
//   {
//     task_id: "TSK-001",
//     title: "要件定義書に基づくデータベース論理設計",
//     assignee: "田中 一郎",
//     skill_required: "Python, FastAPI",
//     priority: "high",
//     deadline: "2026-07-15",
//     source_section: "1.2 データベース構成",
//     load_pct: 25,
//     status: null, // 最初はカンバンに入っていない
//   },
//   {
//     task_id: "TSK-002",
//     title: "フロントエンド用カンバンUIコンポーネント実装",
//     assignee: "佐藤 花子",
//     skill_required: "HTML, CSS, TypeScript",
//     priority: "medium",
//     deadline: "2026-07-20",
//     source_section: "2.5 画面UI仕様",
//     load_pct: 35,
//     status: null, // 最初はカンバンに入っていない
//   },
// ];

// let activeFilterMember: string = "全員";

// document.addEventListener("DOMContentLoaded", () => {
//   renderMembers();
//   setupNavigation();
//   setupFormEvents();
//   setupSettingsEvents();

//   renderTasksTable();
//   initKanbanBoard();
//   renderGeneratedPreview();
// });

// function showScreen(screenId: string) {
//   document.querySelectorAll(".screen-view").forEach((el) => {
//     (el as HTMLElement).style.display = el.id === screenId ? "block" : "none";
//   });
// }

// // サイドバーのナビゲーション項目 ↔ 画面IDの対応表
// const NAV_TO_SCREEN: Record<string, string> = {
//   "nav-generate": "screen-generate",
//   "nav-tasklist": "screen-tasklist",
//   "nav-members": "screen-members",
//   "nav-settings": "screen-settings",
// };

// // プレビューカードなど、別画面から遷移させたい場合に呼び出す
// function navigateToScreen(screenId: string) {
//   const navId = Object.keys(NAV_TO_SCREEN).find(
//     (key) => NAV_TO_SCREEN[key] === screenId,
//   );
//   Object.keys(NAV_TO_SCREEN).forEach((id) =>
//     document.getElementById(id)?.classList.remove("active"),
//   );
//   if (navId) document.getElementById(navId)?.classList.add("active");
//   showScreen(screenId);
// }

// function setupNavigation() {
//   Object.keys(NAV_TO_SCREEN).forEach((navId) => {
//     document.getElementById(navId)?.addEventListener("click", () => {
//       navigateToScreen(NAV_TO_SCREEN[navId]);
//     });
//   });

//   const btnViewTable = document.getElementById("btn-view-table");
//   const btnViewKanban = document.getElementById("btn-view-kanban");
//   const viewTableWrapper = document.getElementById("view-table-wrapper");
//   const viewKanbanWrapper = document.getElementById("view-kanban-wrapper");

//   btnViewTable?.addEventListener("click", () => {
//     btnViewTable.classList.add("active");
//     btnViewKanban?.classList.remove("active");
//     if (viewTableWrapper) viewTableWrapper.style.display = "block";
//     if (viewKanbanWrapper) viewKanbanWrapper.style.display = "none";
//     renderTasksTable();
//   });

//   btnViewKanban?.addEventListener("click", () => {
//     btnViewKanban.classList.add("active");
//     btnViewTable?.classList.remove("active");
//     if (viewTableWrapper) viewTableWrapper.style.display = "none";
//     if (viewKanbanWrapper) viewKanbanWrapper.style.display = "flex";
//     initKanbanBoard();
//   });
// }

// // ════ テーブルのレンダリング（ボタン機能の組み込み） ════
// function renderTasksTable() {
//   const tbody = document.getElementById("task-table-body");
//   if (!tbody) return;
//   tbody.innerHTML = "";

//   const filteredTasks = generatedTasks.filter(
//     (t) => activeFilterMember === "全員" || t.assignee === activeFilterMember,
//   );

//   // `renderTasksTable` 関数内のループ処理部分
//   filteredTasks.forEach((task) => {
//     const tr = document.createElement("tr");

//     const isAdded = task.status !== null;

//     // HTML側にはCSSクラス名のみを付与
//     const btnHtml = isAdded
//       ? `<button class="btn-kanban-added" disabled><i class="ti ti-check"></i> 追加済み</button>`
//       : `<button class="btn-add-to-kanban" data-id="${task.task_id}"><i class="ti ti-plus"></i> カンバンに追加</button>`;

//     tr.innerHTML = `
//       <td style="font-weight:600;color:var(--brand-mid)">${task.task_id}</td>
//       <td style="font-weight:500">${task.title}</td>
//       <td><span style="background:#F0F2FA;padding:2px 6px;border-radius:4px;font-weight:500">${task.assignee}</span></td>
//       <td><code style="font-size:11px;background:#F5F5FA;padding:2px 4px;border-radius:4px">${task.skill_required}</code></td>
//       <td><span class="badge-priority ${task.priority}">${task.priority.toUpperCase()}</span></td>
//       <td style="color:#666">${task.source_section}</td>
//       <td style="font-weight:600;color:var(--brand)">${task.load_pct}%</td>
//       <td style="text-align:center">${btnHtml}</td>
//     `;

//     // イベントリスナーの処理はそのまま維持
//     tr.querySelector(".btn-add-to-kanban")?.addEventListener("click", (e) => {
//       const id = (e.currentTarget as HTMLElement).getAttribute("data-id");
//       const targetTask = generatedTasks.find((t) => t.task_id === id);
//       if (targetTask) {
//         targetTask.status = "todo";
//         renderTasksTable();
//         initKanbanBoard();
//         renderGeneratedPreview();
//       }
//     });

//     tbody.appendChild(tr);
//   });
// }

// // ════ タスク生成プレビュー（メイン画面右側パネル）のレンダリング ════
// function renderGeneratedPreview() {
//   const emptyState = document.getElementById("preview-empty-state");
//   const container = document.getElementById("preview-cards-container");
//   if (!emptyState || !container) return;

//   if (generatedTasks.length === 0) {
//     emptyState.style.display = "flex";
//     container.style.display = "none";
//     return;
//   }

//   emptyState.style.display = "none";
//   container.style.display = "flex";
//   container.innerHTML = "";

//   generatedTasks.forEach((task) => {
//     const card = document.createElement("div");
//     card.className = "preview-task-card";

//     const isAdded = task.status !== null;
//     const btnHtml = isAdded
//       ? `<button class="btn-kanban-added" disabled><i class="ti ti-check"></i> 追加済み</button>`
//       : `<button class="btn-add-to-kanban" data-id="${task.task_id}"><i class="ti ti-plus"></i> Kanbanへ追加</button>`;

//     card.innerHTML = `
//       <div class="preview-card-top">
//         <span class="preview-card-id">${task.task_id}</span>
//         <span class="badge-priority ${task.priority}">${task.priority.toUpperCase()}</span>
//       </div>
//       <div class="preview-card-title">${task.title}</div>
//       <div class="preview-card-meta">
//         <div class="preview-meta-item"><i class="ti ti-user"></i>推奨担当: <b>${task.assignee}</b></div>
//         <div class="preview-meta-item"><i class="ti ti-tools"></i>必要スキル: ${task.skill_required}</div>
//         <div class="preview-meta-item"><i class="ti ti-gauge"></i>想定工数: ${task.load_pct}%</div>
//       </div>
//       <div class="preview-card-actions">
//         ${btnHtml}
//         <button class="btn-preview-secondary" data-assignee="${task.assignee}">
//           <i class="ti ti-users"></i> 担当者を確認
//         </button>
//       </div>
//     `;

//     card.querySelector(".btn-add-to-kanban")?.addEventListener("click", (e) => {
//       const id = (e.currentTarget as HTMLElement).getAttribute("data-id");
//       const targetTask = generatedTasks.find((t) => t.task_id === id);
//       if (targetTask) {
//         targetTask.status = "todo";
//         renderTasksTable();
//         initKanbanBoard();
//         renderGeneratedPreview();
//       }
//     });

//     card
//       .querySelector(".btn-preview-secondary")
//       ?.addEventListener("click", () => {
//         navigateToScreen("screen-members");
//       });

//     container.appendChild(card);
//   });
// }

// // ════ カンバンボードの同期レンダリング ════
// function initKanbanBoard() {
//   const statuses: ("todo" | "doing" | "done")[] = ["todo", "doing", "done"];

//   statuses.forEach((status) => {
//     const container = document.getElementById(`kanban-cards-${status}`);
//     const countEl = document.getElementById(`count-${status}`);
//     if (!container) return;
//     container.innerHTML = "";

//     // ステータスが一致し、かつフィルターに該当するタスクのみカード化
//     const filtered = generatedTasks.filter(
//       (t) =>
//         t.status === status &&
//         (activeFilterMember === "全員" || t.assignee === activeFilterMember),
//     );

//     if (countEl) countEl.textContent = filtered.length.toString();

//     filtered.forEach((task) => {
//       const card = document.createElement("div");
//       card.className = "kanban-card";
//       card.draggable = true;
//       card.innerHTML = `
//         <div class="title" style="font-size:12px;font-weight:500;color:#111">${task.title}</div>
//         <div class="meta" style="display:flex;align-items:center;justify-content:space-between;margin-top:8px;font-size:10px">
//           <span style="font-weight:600;background:#EEF2FF;padding:1px 5px;border-radius:4px">${task.assignee}</span>
//           <span class="badge-priority ${task.priority}" style="font-size:9px;padding:1px 4px">${task.priority.toUpperCase()}</span>
//         </div>
//       `;

//       card.addEventListener("dragstart", (e) => {
//         (e as DragEvent).dataTransfer?.setData("text/plain", task.task_id);
//       });

//       container.appendChild(card);
//     });

//     container.addEventListener("dragover", (e) => e.preventDefault());
//     container.addEventListener("drop", (e) => {
//       e.preventDefault();
//       const taskId = (e as DragEvent).dataTransfer?.getData("text/plain");
//       if (taskId) {
//         const task = generatedTasks.find((t) => t.task_id === taskId);
//         if (task) {
//           task.status = status;
//           initKanbanBoard();
//           renderTasksTable(); // ドラッグ＆ドロップでステータスが変わってもテーブル側と完全同期
//         }
//       }
//     });
//   });
// }

// function setupFormEvents() {
//   document.getElementById("btn-add-member")?.addEventListener("click", () => {
//     const nameInput = document.getElementById(
//       "member-name-input",
//     ) as HTMLInputElement;
//     const skillsInput = document.getElementById(
//       "member-skills-input",
//     ) as HTMLInputElement;
//     if (!nameInput.value.trim()) return;

//     const newMember: Member = {
//       id: `m${members.length + 1}`,
//       name: nameInput.value.trim(),
//       skills: skillsInput.value
//         .split(",")
//         .map((s) => s.trim())
//         .filter(Boolean),
//       load_pct: 0,
//     };
//     members.push(newMember);
//     nameInput.value = "";
//     skillsInput.value = "";
//     renderMembers();
//   });

//   document
//     .getElementById("btn-trigger-generate")
//     ?.addEventListener("click", () => {
//       const btn = document.getElementById(
//         "btn-trigger-generate",
//       ) as HTMLButtonElement;
//       btn.disabled = true;
//       btn.innerHTML = `<i class="ti ti-loader quarter-spin"></i> AIタスクを解析して生成中...`;

//       setTimeout(() => {
//         const newGeneratedId = `TSK-00${generatedTasks.length + 1}`;
//         generatedTasks.push({
//           task_id: newGeneratedId,
//           title: "新規仕様に基づくAPIエンドポイント開発およびバリデーション",
//           assignee: members[Math.floor(Math.random() * members.length)].name,
//           skill_required: "Python",
//           priority: "high",
//           deadline: null,
//           source_section: "3.1 バックエンドIF",
//           load_pct: 15,
//           status: null, // 生成直後はまだカンバン未登録状態
//         });

//         btn.disabled = false;
//         btn.innerHTML = `<i class="ti ti-bolt"></i> AIタスク生成＆マッチングを開始`;

//         // 生成結果はメイン画面右側のプレビューパネルに表示し、
//         // 一覧・カンバンも裏側で同期しておく
//         renderGeneratedPreview();
//         renderTasksTable();
//         initKanbanBoard();
//       }, 1200);
//     });
// }

// function renderMembers() {
//   const container = document.getElementById("member-list-container");
//   if (!container) return;
//   container.innerHTML = "";

//   members.forEach((m) => {
//     const card = document.createElement("div");
//     card.className = "member-card";
//     card.style.display = "flex";
//     card.style.justifyContent = "space-between";
//     card.style.alignItems = "center";
//     card.style.background = "#F9FAFF";
//     card.style.border = "0.5px solid #E2E7FF";
//     card.style.borderRadius = "8px";
//     card.style.padding = "8px 12px";
//     card.style.marginBottom = "6px";

//     card.innerHTML = `
//       <div>
//         <div>
//           <span class="m-info-name" style="font-size:12px;font-weight:600;color:var(--brand)">${m.name}</span>
//           <span class="m-info-load" style="font-size:10px;color:#777;margin-left:8px">ベース負荷: ${m.load_pct}%</span>
//         </div>
//         <div class="m-tags" style="display:flex;gap:4px;margin-top:4px;flex-wrap:wrap">
//           ${m.skills.map((s) => `<span class="m-tag" style="background:#EEF2FF;color:var(--brand-mid);font-size:9px;padding:1px 6px;border-radius:4px;border:0.5px solid #D4DBFF">${s}</span>`).join("")}
//         </div>
//       </div>
//       <button class="btn-del-member" style="background:transparent;border:none;color:#FF7B7B;cursor:pointer"><i class="ti ti-trash"></i></button>
//     `;
//     container.appendChild(card);
//   });
// }

// function setupSettingsEvents() {
//   const radioGroup = document.getElementById("provider-radio-group");
//   radioGroup?.querySelectorAll(".r-btn").forEach((btn) => {
//     btn.addEventListener("click", (e) => {
//       radioGroup
//         .querySelectorAll(".r-btn")
//         .forEach((b) => b.classList.remove("on"));
//       (e.target as HTMLElement).classList.add("on");
//     });
//   });

//   document.getElementById("toggle-slack")?.addEventListener("click", (e) => {
//     (e.currentTarget as HTMLElement).classList.toggle("off");
//   });
//   document.getElementById("toggle-teams")?.addEventListener("click", (e) => {
//     (e.currentTarget as HTMLElement).classList.toggle("off");
//   });
// }
// app.ts

// app.ts

import { mountTaskGenerationProgress } from "./components/taskGenerationProgress";
import type { TaskGenerationProgressHandle } from "./components/taskGenerationProgress";
// 【Phase 10.5】タスク生成は、legacyの同期的な POST /api/tasks/generate から、
// 実際のバックエンドの本番ルートである「プロジェクト作成 → メンバー登録 →
// 非同期生成ジョブ開始 → GET /api/jobs/{job_id} のポーリング」方式へ切り替えた。
// これらは全て src/services/projectService.ts（唯一のAPI呼び出し窓口）経由。
import {
  ensureActiveProject,
  fetchProjectMembers,
  getActiveJobId,
  getActiveProjectId,
  getJobStatus,
  setProjectMembers,
  startGeneration,
} from "./services/projectService";
import { extractErrorMessage } from "./pipeline/format";
import type { PipelineMember } from "./types/pipeline";
import type { JobStatusResponse } from "./types/job";

interface Member {
  id: string;
  name: string;
  skills: string[];
  load_pct: number;
}

interface Task {
  task_id: string;
  title: string;
  assignee: string | null; // バックエンドのマッチング結果（None時はnull）に同期
  skill_required: string;
  priority: "high" | "medium" | "low";
  deadline: string | null;
  source_section: string;
  status: "TODO" | "DOING" | "DONE"; // バックエンドのステータス大文字表記に同期
}

// 💡 メンバーリスト（追加・削除ができるよう let で定義）
let members: Member[] = [];

// 設定（/api/settings のスキーマに対応）
interface Settings {
  provider: "openai" | "anthropic" | "ollama";
  api_key: string;
  base_url: string | null;
  slack_webhook_url: string | null;
  teams_webhook_url: string | null;
}

// 生成されたタスクを保持するグローバル配列（API経由で動的に取得）
let generatedTasks: Task[] = [];
let activeFilterMember: string = "全員";

// AIタスク生成中の進捗UI（src/components/taskGenerationProgress.ts）のハンドル。
// DOMContentLoaded時にマウントし、以後は生成ボタンのイベントから操作する。
let taskGenerationProgress: TaskGenerationProgressHandle | null = null;
// 実行中のジョブポーリングループを止めるためのフラグ設定用コールバック。
// キャンセルボタンが押された時にこれを呼ぶ（ポーリングをやめるだけで、
// バックエンドで既に開始しているジョブそのものを止めるものではない —
// ジョブをキャンセルするAPIは存在しないため、それは正直にできない）。
let cancelActiveGenerationPolling: (() => void) | null = null;
// ユーザーによる明示的なキャンセル由来かを区別するためのフラグ
// （キャンセル時はエラー扱いにしない）。
let generationCancelledByUser = false;

// バックエンドのベースURL（frontend/.env の VITE_API_BASE_URL から読み込む）
const API_BASE_URL =
  import.meta.env.VITE_API_BASE_URL || "http://localhost:8000";

// バックエンドのエラーコード → ユーザー向けメッセージの対応表（ガイド §4 / §7.1）
const ERROR_MESSAGES: Record<string, string> = {
  FILE_TOO_LARGE: "ファイルサイズが上限を超えています。",
  FILE_PARSE_ERROR: "ファイルの解析に失敗しました。形式を確認してください。",
  EMPTY_INPUT: "仕様書ファイルまたはテキストのどちらかを入力してください。",
  INVALID_MEMBERS_JSON: "メンバー情報の形式が不正です。",
  PLAN_LIMIT_EXCEEDED: "タスク数の上限に達しました。",
  TASK_NOT_FOUND: "対象のタスクが見つかりませんでした。",
  LLM_TIMEOUT: "AIの応答がタイムアウトしました。入力を短くして再試行してください。",
  LLM_PARSE_ERROR: "AIの応答を解釈できませんでした。もう一度お試しください。",
  CONFIG_ERROR: "サーバーの設定に問題があります。管理者に確認してください。",
  NETWORK_ERROR: "バックエンドに接続できませんでした。サーバーの起動を確認してください。",
};

// レスポンスから {code, message} を取り出し、Error として投げ直す共通ハンドラ
async function throwApiError(res: Response): Promise<never> {
  let detail: { code?: string; message?: string } | undefined;
  try {
    const body = await res.json();
    detail = body?.detail;
  } catch {
    /* JSON でない場合は無視 */
  }
  const code = detail?.code ?? "";
  const message =
    detail?.message || ERROR_MESSAGES[code] || `リクエストに失敗しました (Status: ${res.status})`;
  const err = new Error(message) as Error & { code?: string };
  err.code = code;
  throw err;
}

document.addEventListener("DOMContentLoaded", () => {
  renderMembers(); // 💡 メンバー一覧を初期描画（バックエンドから読み込むまでの一時的な表示）
  setupNavigation();
  setupFormEvents();
  setupSettingsEvents();
  setupExportEvents();
  setupTaskGenerationProgress();
  loadActiveProjectMembers(); // 実際に登録済みのプロジェクトメンバーで上書きする

  renderTasksTable();
  initKanbanBoard();
  renderGeneratedPreview();

  checkBackendStatus(); // バックエンドへの接続状態確認
  loadInitialData(); // DB上の既存タスク・保存済み設定を取得
});

// 起動時にバックエンドから既存タスクと設定を取得して画面へ反映する
async function loadInitialData() {
  // 既存タスク（GET /api/tasks）
  try {
    const res = await fetch(`${API_BASE_URL}/api/tasks`);
    if (res.ok) {
      const data = await res.json();
      if (data && Array.isArray(data.tasks)) {
        generatedTasks = data.tasks;
        renderGeneratedPreview();
        renderTasksTable();
        initKanbanBoard();
      }
    }
  } catch {
    /* オフライン時は checkBackendStatus 側で通知済み */
  }

  // 保存済み設定（GET /api/settings）
  try {
    const res = await fetch(`${API_BASE_URL}/api/settings`);
    if (res.ok) {
      const settings: Settings = await res.json();
      applySettingsToForm(settings);
    }
  } catch {
    /* 設定が取得できなくても初期表示のまま続行 */
  }
}

// バックエンドの接続確認とインジケーター表示
async function checkBackendStatus() {
  const dot = document.getElementById("status-dot");
  const text = document.getElementById("backend-status-text");
  try {
    const res = await fetch(`${API_BASE_URL}/healthz`);
    if (res.ok && dot && text) {
      dot.style.backgroundColor = "#22c55e";
      text.textContent = "バックエンドオンライン";
    }
  } catch (e) {
    if (dot && text) {
      dot.style.backgroundColor = "#ef4444";
      text.textContent = "バックエンドオフライン (サーバーを起動してください)";
    }
  }
}

function showScreen(screenId: string) {
  document.querySelectorAll(".screen-view").forEach((el) => {
    (el as HTMLElement).style.display = el.id === screenId ? "block" : "none";
  });
}

const NAV_TO_SCREEN: Record<string, string> = {
  "nav-generate": "screen-generate",
  "nav-tasklist": "screen-tasklist",
  "nav-members": "screen-members",
  "nav-settings": "screen-settings",
};

function navigateToScreen(screenId: string) {
  const navId = Object.keys(NAV_TO_SCREEN).find(
    (key) => NAV_TO_SCREEN[key] === screenId,
  );
  Object.keys(NAV_TO_SCREEN).forEach((id) =>
    document.getElementById(id)?.classList.remove("active"),
  );
  if (navId) document.getElementById(navId)?.classList.add("active");
  showScreen(screenId);
}

function setupNavigation() {
  Object.keys(NAV_TO_SCREEN).forEach((navId) => {
    document.getElementById(navId)?.addEventListener("click", () => {
      navigateToScreen(NAV_TO_SCREEN[navId]);
    });
  });

  const btnViewTable = document.getElementById("btn-view-table");
  const btnViewKanban = document.getElementById("btn-view-kanban");
  const viewTableWrapper = document.getElementById("view-table-wrapper");
  const viewKanbanWrapper = document.getElementById("view-kanban-wrapper");

  btnViewTable?.addEventListener("click", () => {
    btnViewTable.classList.add("active");
    btnViewKanban?.classList.remove("active");
    if (viewTableWrapper) viewTableWrapper.style.display = "block";
    if (viewKanbanWrapper) viewKanbanWrapper.style.display = "none";
    renderTasksTable();
  });

  btnViewKanban?.addEventListener("click", () => {
    btnViewKanban.classList.add("active");
    btnViewTable?.classList.remove("active");
    if (viewTableWrapper) viewTableWrapper.style.display = "none";
    if (viewKanbanWrapper) viewKanbanWrapper.style.display = "flex";
    initKanbanBoard();
  });
}

// ── 1. タスク一覧テーブルのレンダリング ──
function renderTasksTable() {
  const tbody = document.getElementById("task-table-body");
  if (!tbody) return;
  tbody.innerHTML = "";

  const filteredTasks = generatedTasks.filter(
    (t) => activeFilterMember === "全員" || t.assignee === activeFilterMember,
  );

  filteredTasks.forEach((task) => {
    const tr = document.createElement("tr");
    const assigneeName = task.assignee || "未割り当て";

    tr.innerHTML = `
      <td style="font-weight:600;color:var(--brand-mid)">${task.task_id}</td>
      <td class="editable-title-cell" style="font-weight:500; cursor: pointer;" title="クリックして編集">
        <span class="title-text">${task.title}</span>
        <input type="text" class="title-input" value="${task.title}" style="display:none; width:100%; padding:4px; font-size:13px; border:1px solid var(--brand-mid); border-radius:4px;" />
      </td>
      <td><span style="background:#f5ece2;padding:2px 6px;border-radius:4px;font-weight:500">${assigneeName}</span></td>
      <td><code style="font-size:11px;background:#faf1e6;padding:2px 4px;border-radius:4px">${task.skill_required}</code></td>
      <td><span class="badge-priority ${task.priority.toLowerCase()}">${task.priority.toUpperCase()}</span></td>
      <td style="color:#666">${task.source_section}</td>
      <td style="font-weight:600;color:var(--brand)">-</td>
      <td style="text-align:center">
        <span class="badge-priority" style="background:#ffe3c2; color:var(--brand-mid)">${task.status}</span>
      </td>
    `;

    const titleCell = tr.querySelector(".editable-title-cell") as HTMLElement;
    const titleText = titleCell.querySelector(".title-text") as HTMLElement;
    const titleInput = titleCell.querySelector(".title-input") as HTMLInputElement;

    titleCell.addEventListener("click", () => {
      if (titleInput.style.display === "none") {
        titleText.style.display = "none";
        titleInput.style.display = "block";
        titleInput.focus();
        titleInput.select();
      }
    });

    const saveTitle = async () => {
      const newTitle = titleInput.value.trim();
      if (newTitle && newTitle !== task.title) {
        const oldTitle = task.title;
        task.title = newTitle;
        titleText.textContent = newTitle;
        
        try {
          const res = await fetch(`${API_BASE_URL}/api/tasks/${task.task_id}`, {
            method: "PUT",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ 
              title: newTitle,
              status: task.status,
              priority: task.priority,
              source_section: task.source_section,
              assignee: task.assignee
            })
          });
          if (!res.ok) throw new Error("サーバーエラー");
        } catch (err) {
          console.error("バックエンド同期失敗", err);
          task.title = oldTitle;
          titleText.textContent = oldTitle;
        }
        renderGeneratedPreview();
      }
      titleText.style.display = "block";
      titleInput.style.display = "none";
    };

    titleInput.addEventListener("blur", saveTitle);
    titleInput.addEventListener("keydown", (e) => {
      if (e.key === "Enter") saveTitle();
    });

    tbody.appendChild(tr);
  });
}

// ── 2. 生成プレビューのレンダリング ──
function renderGeneratedPreview() {
  const emptyState = document.getElementById("preview-empty-state");
  const container = document.getElementById("preview-cards-container");
  if (!emptyState || !container) return;

  if (!generatedTasks || generatedTasks.length === 0) {
    emptyState.style.display = "flex";
    container.style.display = "none";
    return;
  }

  emptyState.style.display = "none";
  container.style.display = "flex";
  container.innerHTML = "";

  generatedTasks.forEach((task) => {
    const card = document.createElement("div");
    card.className = "preview-task-card";
    
    const assigneeName = task.assignee || "未割り当て";
    const skillRequired = (task as any).skill_required || (task as any).skill || "未指定";
    const priority = task.priority ? task.priority.toUpperCase() : "MEDIUM";
    const priorityClass = task.priority ? task.priority.toLowerCase() : "medium";
    const sourceSection = task.source_section || "§ 自動生成";
    const taskStatus = task.status || "TODO";

    card.innerHTML = `
      <div class="preview-card-top">
        <span class="preview-card-id">${task.task_id}</span>
        <span class="badge-priority ${priorityClass}">${priority}</span>
      </div>
      <div class="preview-card-title">${task.title}</div>
      <div class="preview-card-meta">
        <div class="preview-meta-item"><i data-lucide="user"></i>推奨担当: <b>${assigneeName}</b></div>
        <div class="preview-meta-item"><i data-lucide="wrench"></i>必要スキル: ${skillRequired}</div>
        <div class="preview-meta-item"><i data-lucide="file-text"></i>参照箇所: ${sourceSection}</div>
      </div>
      <div class="preview-card-actions" style="margin-top: 8px;">
        <span class="btn-kanban-added" disabled><i data-lucide="check"></i> 生成完了 (${taskStatus})</span>
        <button class="btn-preview-secondary" data-assignee="${assigneeName}">
          <i data-lucide="users"></i> 担当者を確認
        </button>
      </div>
    `;

    card.querySelector(".btn-preview-secondary")?.addEventListener("click", () => {
      navigateToScreen("screen-members");
    });

    container.appendChild(card);
  });
}

// ── 3. カンバンボードのレンダリング ──
function initKanbanBoard() {
  const statuses: ("TODO" | "DOING" | "DONE")[] = ["TODO", "DOING", "DONE"];

  statuses.forEach((status) => {
    const container = document.getElementById(`kanban-cards-${status.toLowerCase()}`);
    const countEl = document.getElementById(`count-${status.toLowerCase()}`);
    if (!container) return;
    container.innerHTML = "";

    const filtered = generatedTasks.filter(
      (t) => t.status === status && (activeFilterMember === "全員" || t.assignee === activeFilterMember),
    );

    if (countEl) countEl.textContent = filtered.length.toString();

    filtered.forEach((task) => {
      const card = document.createElement("div");
      card.className = "kanban-card";
      card.draggable = true;
      const assigneeName = task.assignee || "未割り当て";

      card.innerHTML = `
        <div class="kanban-title-area" style="cursor:text;">
          <span class="k-title-text" style="font-size:12px;font-weight:500;color:#111">${task.title}</span>
          <input type="text" class="k-title-input" value="${task.title}" style="display:none; width:100%; font-size:12px; padding:2px; border:1px solid var(--brand-mid); border-radius:4px;" />
        </div>
        <div class="meta" style="display:flex;align-items:center;justify-content:space-between;margin-top:8px;font-size:10px">
          <span style="font-weight:600;background:#ffe3c2;padding:1px 5px;border-radius:4px">${assigneeName}</span>
          <span class="badge-priority ${task.priority.toLowerCase()}" style="font-size:9px;padding:1px 4px">${task.priority.toUpperCase()}</span>
        </div>
      `;

      const titleArea = card.querySelector(".kanban-title-area") as HTMLElement;
      const kTitleText = card.querySelector(".k-title-text") as HTMLElement;
      const kTitleInput = card.querySelector(".k-title-input") as HTMLInputElement;

      titleArea.addEventListener("click", (e) => {
        e.stopPropagation(); 
        if (kTitleInput.style.display === "none") {
          card.draggable = false; 
          kTitleText.style.display = "none";
          kTitleInput.style.display = "block";
          kTitleInput.focus();
          kTitleInput.select();
        }
      });

      const saveKanbanTitle = async () => {
        const newTitle = kTitleInput.value.trim();
        if (newTitle && newTitle !== task.title) {
          const oldTitle = task.title;
          task.title = newTitle;
          kTitleText.textContent = newTitle;
          
          try {
            const res = await fetch(`${API_BASE_URL}/api/tasks/${task.task_id}`, {
              method: "PUT",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ 
                title: newTitle,
                status: task.status,
                priority: task.priority,
                source_section: task.source_section,
                assignee: task.assignee
              })
            });
            if (!res.ok) throw new Error("サーバーエラー");
          } catch (err) {
            console.error("カンバン名同期失敗", err);
            task.title = oldTitle;
            kTitleText.textContent = oldTitle;
          }
          renderGeneratedPreview();
        }
        kTitleText.style.display = "block";
        kTitleInput.style.display = "none";
        card.draggable = true;
      };

      kTitleInput.addEventListener("blur", saveKanbanTitle);
      kTitleInput.addEventListener("keydown", (e) => {
        if (e.key === "Enter") saveKanbanTitle();
      });

      card.addEventListener("dragstart", (e) => {
        if (kTitleInput.style.display === "block") {
          e.preventDefault();
          return;
        }
        (e as DragEvent).dataTransfer?.setData("text/plain", task.task_id);
      });

      container.appendChild(card);
    });

    container.addEventListener("dragover", (e) => e.preventDefault());
    container.addEventListener("drop", async (e) => {
      e.preventDefault();
      const taskId = (e as DragEvent).dataTransfer?.getData("text/plain");
      if (taskId) {
        const task = generatedTasks.find((t) => t.task_id === taskId);
        if (task) {
          const oldStatus = task.status;
          task.status = status;
          initKanbanBoard();
          renderTasksTable();

          try {
            const res = await fetch(`${API_BASE_URL}/api/tasks/${taskId}`, {
              method: "PUT",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ 
                title: task.title,
                status: status,
                priority: task.priority,
                source_section: task.source_section,
                assignee: task.assignee
              })
            });
            if (!res.ok) throw new Error("同期失敗");
          } catch (err) {
            console.error("ドラッグ＆ドロップ同期エラー", err);
            task.status = oldStatus;
            initKanbanBoard();
            renderTasksTable();
          }
        }
      }
    });
  });
}

// ── 4. フォーム及びボタンイベント処理（追加・削除・タイムアウト対策） ──
function setupFormEvents() {
  // 💡 メンバーの追加ボタン処理
  // 【Phase 10.5】ローカル配列に追加するだけでなく、実際にバックエンドの
  // プロジェクトメンバーとして永続化する（persistMembers参照）。
  document.getElementById("btn-add-member")?.addEventListener("click", async () => {
    const nameInput = document.getElementById("member-name-input") as HTMLInputElement;
    const skillsInput = document.getElementById("member-skills-input") as HTMLInputElement;

    const name = nameInput.value.trim();
    if (!name) return;

    // カンマ区切りの文字列を綺麗に配列に変換
    const skills = skillsInput.value
      .split(",")
      .map((s) => s.trim())
      .filter(Boolean);

    const newMember: Member = {
      id: `m_${Date.now()}`, // 重複しない一意なIDを設定
      name: name,
      skills: skills,
      load_pct: 0,
    };

    const nextMembers = [...members, newMember];
    const ok = await persistMembers(nextMembers);
    if (ok) {
      nameInput.value = "";
      skillsInput.value = "";
    }
  });

  // AIタスク生成＆マッチング開始ボタンイベント
  // 実際の生成処理本体は runTaskGeneration() に切り出してある
  // （進捗UIの「再試行」ボタンからも同じ処理を呼び出すため）。
  document.getElementById("btn-trigger-generate")?.addEventListener("click", () => {
    runTaskGeneration();
  });

  document.getElementById("spec-file-input")?.addEventListener("change", (e) => {
    const input = e.target as HTMLInputElement;
    const label = document.getElementById("selected-file-name");
    if (input.files && input.files[0] && label) {
      label.textContent = `選択されたファイル: ${input.files[0].name}`;
      label.style.display = "block";
    }
  });
}

// ── AIタスク生成の実行本体（進捗UIと連動） ──
// setupFormEvents() のボタンクリック、進捗UIの「再試行」ボタン(onRetry)、
// および起動時のジョブ再開（resumeActiveGenerationIfAny）の全てから呼ばれる。
//
// 【Phase 10.5】legacyの同期的な POST /api/tasks/generate（ファイル可・
// 即座に結果を返す）から、本番のバックエンドが提供する非同期方式へ切り替えた:
//   ensureActiveProject() → POST /api/projects/{id}/generate（202・job_id）
//   → GET /api/jobs/{job_id} を約1.5秒間隔でポーリング
// バックエンド/FastAPI/LLMパイプライン自体には一切手を加えていない。
//
// 【既知の制限】新しいプロジェクトAPI（POST /api/projects, .../generate）は
// document_text（文字列）しか受け付けず、legacyのようなファイル
// （PDF/Word）のアップロード解析エンドポイントを持たない。そのため、
// 現時点ではテキスト貼り付け入力のみに対応する（ファイル選択のみで
// テキストが空の場合は、その旨を明示してブロックする — 動かないのに
// 動いたふりはしない）。
async function runTaskGeneration(): Promise<void> {
  const btn = document.getElementById("btn-trigger-generate") as HTMLButtonElement;
  const fileInput = document.getElementById("spec-file-input") as HTMLInputElement;
  const textInput = document.getElementById("spec-text-input") as HTMLInputElement;

  const file = fileInput.files?.[0];
  const textContent = textInput.value.trim();

  if (!textContent) {
    if (file) {
      alert(
        "現在、AIタスク生成はテキスト貼り付けのみに対応しています（ファイルからの自動テキスト抽出は未対応です）。\n" +
          "お手数ですが、仕様書の内容を「参考テキストを入力」欄に貼り付けてください。",
      );
    } else {
      alert("仕様書のテキストを入力してください。");
    }
    return;
  }

  btn.disabled = true;
  btn.innerHTML = `<i data-lucide="loader-circle" class="icon-spin"></i> AIタスクを生成中...`;

  generationCancelledByUser = false;
  taskGenerationProgress?.reset();

  let cancelled = false;
  cancelActiveGenerationPolling = () => {
    cancelled = true;
  };

  try {
    const project = await ensureActiveProject();
    const { job_id } = await startGeneration(project.id, { document_text: textContent });
    await pollGenerationJob(job_id, () => cancelled);
  } catch (error) {
    console.error(error);
    if (!generationCancelledByUser) {
      taskGenerationProgress?.reportOutcome(false, {
        message: extractErrorMessage(error, "タスク生成の開始に失敗しました。"),
      });
    }
  } finally {
    cancelActiveGenerationPolling = null;
    btn.disabled = false;
    btn.innerHTML = `<i data-lucide="zap"></i> AIタスク生成＆マッチングを開始`;
  }
}

// GET /api/jobs/{job_id} を完了/失敗/キャンセルまでポーリングし、その都度
// 本物のstatus/progress/current_step/messageを進捗UIへそのまま反映する
// （Step 9: フェイクの進捗・タイマーベースの%は一切使わない）。
async function pollGenerationJob(jobId: string, isCancelled: () => boolean): Promise<void> {
  const POLL_INTERVAL_MS = 1500;
  for (;;) {
    if (isCancelled()) return;

    let status: JobStatusResponse;
    try {
      status = await getJobStatus(jobId);
    } catch (error) {
      if (!isCancelled()) {
        taskGenerationProgress?.reportOutcome(false, {
          message: extractErrorMessage(error, "ジョブ状態の取得に失敗しました。"),
        });
      }
      return;
    }

    if (isCancelled()) return;
    taskGenerationProgress?.applyRealStatus(status);

    if (status.status === "completed" || status.status === "failed" || status.status === "cancelled") {
      return;
    }

    await new Promise((resolve) => setTimeout(resolve, POLL_INTERVAL_MS));
  }
}

// ブラウザ起動時、直前のセッションで開始した生成ジョブがまだ
// running/queued のままなら、ポーリングを再開して進捗UIを復元する
// （Step 29「ブラウザをリフレッシュ」対応。バックエンドに「プロジェクトの
// 最新ジョブ一覧」を返すAPIが無いため、localStorageに保存した直近の
// job_idだけを手がかりにする）。
async function resumeActiveGenerationIfAny(): Promise<void> {
  const jobId = getActiveJobId();
  if (!jobId) return;

  try {
    const status = await getJobStatus(jobId);
    if (status.status !== "queued" && status.status !== "running") {
      return; // 既に終わっている場合は、パイプライン結果画面が訪問時に再取得する
    }
    const btn = document.getElementById("btn-trigger-generate") as HTMLButtonElement | null;
    if (btn) {
      btn.disabled = true;
      btn.innerHTML = `<i data-lucide="loader-circle" class="icon-spin"></i> AIタスクを生成中...`;
    }
    taskGenerationProgress?.applyRealStatus(status);
    let cancelled = false;
    cancelActiveGenerationPolling = () => {
      cancelled = true;
    };
    await pollGenerationJob(jobId, () => cancelled);
    cancelActiveGenerationPolling = null;
    if (btn) {
      btn.disabled = false;
      btn.innerHTML = `<i data-lucide="zap"></i> AIタスク生成＆マッチングを開始`;
    }
  } catch {
    // 保存されていたjob_idがもう存在しない等。静かに諦める
    // （ユーザーが改めて生成ボタンを押せば新しいジョブが始まる）。
  }
}

// AIタスク生成の進捗UIをマウントし、キャンセル/再試行/結果確認の各操作を
// 実際のポーリング停止・再実行・画面遷移と結びつける。
// プレビューパネル内の空状態/生成結果カードとは表示を排他にする
// （同じパネル内で進捗カードと結果カードが二重に表示されないようにする）。
function setupTaskGenerationProgress(): void {
  const container = document.getElementById("task-generation-progress-container");
  if (!container) return;

  taskGenerationProgress = mountTaskGenerationProgress(container, {
    onCancel: () => {
      // フロントエンド側のポーリングを止めるだけで、バックエンドで既に
      // 開始しているジョブそのものをキャンセルするものではない
      // （ジョブをキャンセルするAPIは存在しない）。
      generationCancelledByUser = true;
      cancelActiveGenerationPolling?.();
    },
    onRetry: () => {
      runTaskGeneration();
    },
    onConfirmResult: () => {
      // 実際に生成されたタスクは「パイプライン結果」側の各画面
      // （タスクレビュー等）に表示される。legacyの screen-tasklist は
      // このジョブベースの新しいフローとはもう連動していないため、
      // 新しい方の画面へ遷移させる（既存のパイプラインルーターの
      // ナビゲーションボタンをそのままクリックする、既存の疎結合な方式）。
      document.getElementById("nav-pipeline-tasks")?.click();
    },
    onStateChange: (state) => {
      const emptyState = document.getElementById("preview-empty-state");
      const previewCards = document.getElementById("preview-cards-container");
      const showProgress = state.status !== "idle";
      if (showProgress) {
        if (emptyState) emptyState.style.display = "none";
        if (previewCards) previewCards.style.display = "none";
      } else {
        // idleに戻ったら（キャンセル、または完了後の「結果を確認」経由のreset）
        // 通常のプレビュー表示ロジックに委ねる。
        renderGeneratedPreview();
      }
    },
  });

  resumeActiveGenerationIfAny();
}

// ── 5. メンバー一覧のレンダリング（削除イベント紐付け対応） ──
function renderMembers() {
  const container = document.getElementById("member-list-container");
  if (!container) return;
  container.innerHTML = "";

  members.forEach((m) => {
    const card = document.createElement("div");
    card.className = "member-card";
    card.style.display = "flex";
    card.style.justifyContent = "space-between";
    card.style.alignItems = "center";
    card.style.background = "#fffaf3";
    card.style.border = "0.5px solid #f0d9bb";
    card.style.borderRadius = "8px";
    card.style.padding = "8px 12px";
    card.style.marginBottom = "6px";

    card.innerHTML = `
      <div>
        <div>
          <span class="m-info-name" style="font-size:12px;font-weight:600;color:var(--brand)">${m.name}</span>
          <span class="m-info-load" style="font-size:10px;color:#777;margin-left:8px">ベース負荷: ${m.load_pct}%</span>
        </div>
        <div class="m-tags" style="display:flex;gap:4px;margin-top:4px;flex-wrap:wrap">
          ${m.skills.map((s) => `<span class="m-tag" style="background:#ffe3c2;color:var(--brand-mid);font-size:9px;padding:1px 6px;border-radius:4px;border:0.5px solid #f0c898">${s}</span>`).join("")}
        </div>
      </div>
      <button class="btn-del-member" data-id="${m.id}" style="background:transparent;border:none;color:#FF7B7B;cursor:pointer">
        <i data-lucide="trash"></i>
      </button>
    `;

    // 💡 ゴミ箱ボタンクリック時の動的削除処理
    // 【Phase 10.5】ローカル配列からの削除だけでなく、実際にバックエンドの
    // プロジェクトメンバーからも削除する（persistMembers参照）。
    const delBtn = card.querySelector(".btn-del-member");
    delBtn?.addEventListener("click", async (e) => {
      e.stopPropagation();
      const idToDel = delBtn.getAttribute("data-id");
      if (idToDel) {
        const nextMembers = members.filter((member) => member.id !== idToDel);
        await persistMembers(nextMembers);
      }
    });

    container.appendChild(card);
  });
}

// ── Phase 10.5: メンバーの永続化・変換ヘルパー ──
//
// legacyの簡易メンバー画面（氏名 + カンマ区切りスキル）は、そのUIを
// 変更せずに実際の PUT /api/projects/{id}/members（Phase 6の構造化
// メンバースキーマ: スキルレベル・週あたり稼働時間・稼働曜日等が必須）へ
// 橋渡しする。このシンプルなフォームはスキルレベルや稼働時間を収集
// しないため、それらは以下の固定デフォルト値で補っている
// （バックエンドの出力を捏造しているのではなく、入力側の妥当なデフォルト
// 値である点に注意 — レベルや稼働時間を細かく設定したい場合は、
// 「メンバー管理（スキル/稼働モデル）」画面で実際の値を確認できる）。
const DEFAULT_SKILL_LEVEL = 3; // 1-5段階の中間値
const DEFAULT_AVAILABLE_HOURS_PER_WEEK = 40;
const DEFAULT_WORKING_DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri"];

function toPipelineMembers(list: Member[]): PipelineMember[] {
  return list.map((m) => ({
    id: m.id,
    name: m.name,
    skills: m.skills.map((skill) => ({ skill, level: DEFAULT_SKILL_LEVEL, experience_years: null })),
    experience_years: null,
    availability: {
      available_hours_per_week: DEFAULT_AVAILABLE_HOURS_PER_WEEK,
      working_days: DEFAULT_WORKING_DAYS,
      current_assigned_hours: 0,
    },
    constraints: [],
  }));
}

function fromPipelineMembers(list: PipelineMember[]): Member[] {
  return list.map((m) => ({
    id: m.id,
    name: m.name,
    skills: m.skills.map((s) => s.skill),
    load_pct:
      m.availability.available_hours_per_week > 0
        ? Math.round((m.availability.current_assigned_hours / m.availability.available_hours_per_week) * 100)
        : 0,
  }));
}

// メンバー一覧を実際にバックエンドへ保存し、保存後にサーバー側の最新状態を
// 再取得して画面へ反映する（Step 7: ローカル状態だけに頼らず、必ずDBを
// 真実の情報源として読み直す）。成功したら true を返す。
let memberSyncInFlight = false;

async function persistMembers(nextMembers: Member[]): Promise<boolean> {
  if (memberSyncInFlight) return false;
  memberSyncInFlight = true;

  const addBtn = document.getElementById("btn-add-member") as HTMLButtonElement | null;
  const originalLabel = addBtn?.textContent ?? "追加";
  if (addBtn) {
    addBtn.disabled = true;
    addBtn.textContent = "保存中...";
  }

  try {
    const project = await ensureActiveProject();
    await setProjectMembers(project.id, toPipelineMembers(nextMembers));
    const reloaded = await fetchProjectMembers(project.id);
    members = fromPipelineMembers(reloaded.members);
    return true;
  } catch (error) {
    console.error(error);
    alert(`メンバー情報の保存に失敗しました: ${extractErrorMessage(error, "不明なエラーが発生しました。")}`);
    return false;
  } finally {
    memberSyncInFlight = false;
    if (addBtn) {
      addBtn.disabled = false;
      addBtn.textContent = originalLabel;
    }
    renderMembers();
  }
}

// 起動時、既にアクティブなプロジェクトがあれば、実際に登録済みのメンバーを
// バックエンドから読み込んで表示する（Step 7/18: ローカルの空配列のまま
// 放置せず、リフレッシュ後もDBの内容を正しく反映する）。
async function loadActiveProjectMembers(): Promise<void> {
  const projectId = getActiveProjectId();
  if (!projectId) return;
  try {
    const directory = await fetchProjectMembers(projectId);
    members = fromPipelineMembers(directory.members);
    renderMembers();
  } catch {
    // プロジェクトが既に存在しない等。致命的ではないため静かに諦める
    // （次にメンバーを追加した際に ensureActiveProject() が新規作成にフォールバックする）。
  }
}

// ── 6. 設定画面用イベント ──

// provider に応じて Base URL 入力欄（Ollama用）の表示/非表示を切り替える
function updateProviderDependentUI() {
  const active = document
    .querySelector("#provider-radio-group .r-btn.on")
    ?.getAttribute("data-provider");
  const rowBaseUrl = document.getElementById("row-base-url");
  if (rowBaseUrl) {
    rowBaseUrl.style.display = active === "ollama" ? "flex" : "none";
  }
}

function setupSettingsEvents() {
  const radioGroup = document.getElementById("provider-radio-group");
  radioGroup?.querySelectorAll(".r-btn").forEach((btn) => {
    btn.addEventListener("click", (e) => {
      radioGroup.querySelectorAll(".r-btn").forEach((b) => b.classList.remove("on"));
      (e.currentTarget as HTMLElement).classList.add("on");
      updateProviderDependentUI();
    });
  });

  document.getElementById("toggle-slack")?.addEventListener("click", (e) => {
    (e.currentTarget as HTMLElement).classList.toggle("off");
  });
  document.getElementById("toggle-teams")?.addEventListener("click", (e) => {
    (e.currentTarget as HTMLElement).classList.toggle("off");
  });

  // 保存ボタン → POST /api/settings
  document.getElementById("btn-save-settings")?.addEventListener("click", saveSettings);

  updateProviderDependentUI();
}

// GET /api/settings の結果をフォームへ反映（ガイド §7.3）
function applySettingsToForm(settings: Settings) {
  // プロバイダー
  document.querySelectorAll("#provider-radio-group .r-btn").forEach((b) => {
    b.classList.toggle(
      "on",
      b.getAttribute("data-provider") === settings.provider,
    );
  });

  const apiKey = document.getElementById("settings-api-key") as HTMLInputElement | null;
  if (apiKey) apiKey.value = settings.api_key ?? "";

  const baseUrl = document.getElementById("settings-base-url") as HTMLInputElement | null;
  if (baseUrl) baseUrl.value = settings.base_url ?? "";

  const slackUrl = document.getElementById("settings-slack-url") as HTMLInputElement | null;
  if (slackUrl) slackUrl.value = settings.slack_webhook_url ?? "";

  const teamsUrl = document.getElementById("settings-teams-url") as HTMLInputElement | null;
  if (teamsUrl) teamsUrl.value = settings.teams_webhook_url ?? "";

  // Webhook URL が設定済みなら通知トグルを ON（= off クラスを外す）にする
  document
    .getElementById("toggle-slack")
    ?.classList.toggle("off", !settings.slack_webhook_url);
  document
    .getElementById("toggle-teams")
    ?.classList.toggle("off", !settings.teams_webhook_url);

  updateProviderDependentUI();
}

// フォームの内容を Settings に組み立てて POST /api/settings
async function saveSettings() {
  const btn = document.getElementById("btn-save-settings") as HTMLButtonElement | null;

  const provider =
    (document
      .querySelector("#provider-radio-group .r-btn.on")
      ?.getAttribute("data-provider") as Settings["provider"]) || "openai";

  const apiKey = (document.getElementById("settings-api-key") as HTMLInputElement)?.value.trim() ?? "";
  const baseUrl = (document.getElementById("settings-base-url") as HTMLInputElement)?.value.trim() ?? "";
  const slackOn = !document.getElementById("toggle-slack")?.classList.contains("off");
  const teamsOn = !document.getElementById("toggle-teams")?.classList.contains("off");
  const slackUrl = (document.getElementById("settings-slack-url") as HTMLInputElement)?.value.trim() ?? "";
  const teamsUrl = (document.getElementById("settings-teams-url") as HTMLInputElement)?.value.trim() ?? "";

  const payload: Settings = {
    provider,
    api_key: apiKey,
    base_url: baseUrl || null,
    slack_webhook_url: slackOn && slackUrl ? slackUrl : null,
    teams_webhook_url: teamsOn && teamsUrl ? teamsUrl : null,
  };

  if (btn) {
    btn.disabled = true;
    btn.textContent = "保存中...";
  }

  try {
    const res = await fetch(`${API_BASE_URL}/api/settings`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (!res.ok) await throwApiError(res);
    alert("設定を保存しました。");
  } catch (error: any) {
    alert(`設定の保存に失敗しました: ${error.message}`);
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.textContent = "設定を保存";
    }
  }
}

// ── 7. JSONエクスポート（ガイド §7.4） ──
let exportPayload: unknown = null;

function setupExportEvents() {
  const modal = document.getElementById("export-modal");

  const closeModal = () => modal?.classList.remove("open");

  // エクスポートボタン → GET /api/tasks/export → プレビューをモーダルに表示
  document.getElementById("btn-open-export")?.addEventListener("click", async () => {
    try {
      const res = await fetch(`${API_BASE_URL}/api/tasks/export`);
      if (!res.ok) await throwApiError(res);
      exportPayload = await res.json();

      const preview = document.getElementById("json-preview-area");
      if (preview) preview.textContent = JSON.stringify(exportPayload, null, 2);
      modal?.classList.add("open");
    } catch (error: any) {
      alert(`エクスポートの取得に失敗しました: ${error.message}`);
    }
  });

  // ダウンロード確定 → Blob 化してファイル保存
  document.getElementById("btn-confirm-download")?.addEventListener("click", () => {
    if (!exportPayload) return;
    const data = exportPayload as { project?: string };
    const blob = new Blob([JSON.stringify(exportPayload, null, 2)], {
      type: "application/json",
    });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${data.project || "tasumiru"}_tasks.json`;
    a.click();
    URL.revokeObjectURL(url);
    closeModal();
  });

  document.getElementById("btn-close-modal")?.addEventListener("click", closeModal);
  document.getElementById("btn-cancel-export")?.addEventListener("click", closeModal);
  // オーバーレイの背景クリックで閉じる
  modal?.addEventListener("click", (e) => {
    if (e.target === modal) closeModal();
  });
}