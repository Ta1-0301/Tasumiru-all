// src/pipeline/router.ts
//
// Phase 10: パイプライン結果（サンプル）ナビゲーションのブートストラップ。
// auth/router.ts と同じ方針で、既存の app.ts / index.html には手を入れず
// 独立して同じ DOMContentLoaded に相乗りする。
// 新しいサイドバー項目（8画面分）のクリックを拾い、対応するビューを
// 初回クリック時に一度だけ描画する（以後は再クリックのたびに再描画）。
import { renderRequirementsView } from "../views/requirementsView";
import { renderPipelineTasksView } from "../views/pipelineTasksView";
import { renderDependenciesView } from "../views/dependenciesView";
import { renderPipelineMembersView } from "../views/pipelineMembersView";
import { renderAssignmentsView } from "../views/assignmentsView";
import { renderValidationView } from "../views/validationView";
import { renderPipelineKanban } from "../components/kanban";
import { renderPipelineExportView } from "../views/pipelineExportView";

interface PipelineScreenEntry {
  navId: string;
  screenId: string;
  render: (el: HTMLElement) => void | Promise<void>;
}

const PIPELINE_SCREENS: PipelineScreenEntry[] = [
  { navId: "nav-pipeline-requirements", screenId: "screen-pipeline-requirements", render: renderRequirementsView },
  { navId: "nav-pipeline-tasks", screenId: "screen-pipeline-tasks", render: renderPipelineTasksView },
  { navId: "nav-pipeline-dependencies", screenId: "screen-pipeline-dependencies", render: renderDependenciesView },
  { navId: "nav-pipeline-members", screenId: "screen-pipeline-members", render: renderPipelineMembersView },
  { navId: "nav-pipeline-assignments", screenId: "screen-pipeline-assignments", render: renderAssignmentsView },
  { navId: "nav-pipeline-validation", screenId: "screen-pipeline-validation", render: renderValidationView },
  { navId: "nav-pipeline-kanban", screenId: "screen-pipeline-kanban", render: renderPipelineKanban },
  { navId: "nav-pipeline-export", screenId: "screen-pipeline-export", render: renderPipelineExportView },
];

// 既存(legacy)＋認証系のナビ項目。これらがクリックされたら、
// パイプライン側のナビの active 状態を解除する。
const OTHER_NAV_IDS = ["nav-generate", "nav-tasklist", "nav-members", "nav-team", "nav-settings"];

function showPipelineScreen(screenId: string): void {
  document.querySelectorAll(".screen-view").forEach((el) => {
    (el as HTMLElement).style.display = el.id === screenId ? "block" : "none";
  });
}

function setActiveNav(navId: string): void {
  document.querySelectorAll(".sidebar-nav-item").forEach((el) => el.classList.remove("active"));
  document.getElementById(navId)?.classList.add("active");
}

function clearPipelineActiveNav(): void {
  PIPELINE_SCREENS.forEach((entry) => document.getElementById(entry.navId)?.classList.remove("active"));
}

function init(): void {
  const rendered = new Set<string>();

  PIPELINE_SCREENS.forEach((entry) => {
    const btn = document.getElementById(entry.navId);
    const screen = document.getElementById(entry.screenId);
    if (!btn || !screen) return;

    btn.addEventListener("click", () => {
      setActiveNav(entry.navId);
      showPipelineScreen(entry.screenId);
      // カンバン画面はローカルのドラッグ状態を保持したいので、
      // 一度描画したら再訪問時に再描画しない。他の画面は毎回最新の
      // フィクスチャ/APIレスポンスを見せるため訪問のたびに再描画する。
      if (entry.navId === "nav-pipeline-kanban" && rendered.has(entry.navId)) {
        return;
      }
      rendered.add(entry.navId);
      entry.render(screen as HTMLElement);
    });
  });

  OTHER_NAV_IDS.forEach((id) => {
    document.getElementById(id)?.addEventListener("click", clearPipelineActiveNav);
  });
}

document.addEventListener("DOMContentLoaded", init);
