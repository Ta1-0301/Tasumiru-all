// src/components/kanban.ts
//
// Phase 10: パイプラインのカンバンボード。
// Phase 9 の Final JSON（タスク + 確定アサイン）を元にカードを描画する。
// Final JSON にはKanbanステータス（TODO/DOING/DONE）という概念が
// 存在しない（legacyの backend/routers/tasks.py 側のTaskSchemaにのみ
// status フィールドがある）ため、このボードのステータスは画面内だけの
// ローカル状態として保持し、元のフィクスチャ/バックエンドデータは
// 一切書き換えない。ページを離れる/リロードするとリセットされる。
import "./kanban.css";
import { getPipelineTasks } from "../services/taskService";
import { getAssignments } from "../services/assignmentService";
import { getPipelineMembers } from "../services/memberService";
import { escapeHtml } from "../auth/util";
import { IS_SAMPLE_DATA } from "../services/projectService";
import { sampleDataBannerHtml, pipelineErrorBannerHtml, extractErrorMessage, priorityBadgeHtml } from "../pipeline/format";
import type { FinalAssignment, PipelineMember, PipelineTask } from "../types/pipeline";

type KanbanStatus = "TODO" | "DOING" | "DONE";
const STATUSES: { key: KanbanStatus; label: string }[] = [
  { key: "TODO", label: "TODO" },
  { key: "DOING", label: "DOING" },
  { key: "DONE", label: "DONE" },
];

function assignedMemberName(
  taskId: string,
  assignments: FinalAssignment[],
  members: PipelineMember[],
): string {
  const assignment = assignments.find((a) => a.task_id === taskId);
  if (!assignment?.assigned_member_id) return "未割り当て";
  return members.find((m) => m.id === assignment.assigned_member_id)?.name ?? assignment.assigned_member_id;
}

export async function renderPipelineKanban(container: HTMLElement): Promise<void> {
  container.innerHTML = `
    <div class="sec-header sec-header-page">
      <div class="sec-header-icon"><i data-lucide="kanban"></i></div>
      <span class="sec-header-title">カンバン（パイプライン結果）</span>
    </div>
    <div class="sec-body" style="padding: 16px">
      ${IS_SAMPLE_DATA ? sampleDataBannerHtml() : ""}
      <div class="auth-hint" style="margin-bottom:10px">
        カードのステータス（TODO/DOING/DONE）はこの画面内だけの一時的な状態です。バックエンドへは保存されません。
      </div>
      <div class="pipeline-kanban-board" id="pipeline-kanban-board"></div>
    </div>
  `;

  const board = container.querySelector("#pipeline-kanban-board") as HTMLElement;
  let tasks: PipelineTask[];
  let assignments: FinalAssignment[];
  let members: PipelineMember[];
  try {
    [tasks, assignments, members] = await Promise.all([
      getPipelineTasks(),
      getAssignments(),
      getPipelineMembers(),
    ]);
  } catch (err) {
    board.innerHTML = pipelineErrorBannerHtml(extractErrorMessage(err, "カンバンデータの取得に失敗しました。"));
    return;
  }

  if (tasks.length === 0) {
    board.innerHTML = `<div class="auth-hint">タスクデータがありません。</div>`;
    return;
  }

  // ローカルのみのステータス状態（初期値は全てTODO）。
  const statusByTaskId = new Map<string, KanbanStatus>(tasks.map((t) => [t.id, "TODO"]));

  board.innerHTML = STATUSES.map(
    (s) => `
      <div class="kanban-column">
        <div class="kanban-column-header">
          <span class="t">${s.label}</span><span class="c" id="pk-count-${s.key}">0</span>
        </div>
        <div class="kanban-cards" id="pk-cards-${s.key}" data-status="${s.key}"></div>
      </div>
    `,
  ).join("");

  function cardHtml(task: PipelineTask): string {
    return `
      <div class="kanban-card" draggable="true" data-task-id="${escapeHtml(task.id)}">
        <div class="title">${escapeHtml(task.title)}</div>
        <div class="auth-hint" style="margin-top:4px">${escapeHtml(task.id)}</div>
        <div class="meta">
          <span style="font-weight:600;background:#ffe3c2;padding:1px 5px;border-radius:4px">${escapeHtml(assignedMemberName(task.id, assignments, members))}</span>
          ${priorityBadgeHtml(task.priority)}
        </div>
      </div>
    `;
  }

  function renderColumns(): void {
    STATUSES.forEach((s) => {
      const cardsEl = board.querySelector(`#pk-cards-${s.key}`) as HTMLElement;
      const countEl = board.querySelector(`#pk-count-${s.key}`) as HTMLElement;
      const columnTasks = tasks.filter((t) => statusByTaskId.get(t.id) === s.key);
      countEl.textContent = String(columnTasks.length);
      cardsEl.innerHTML = columnTasks.map(cardHtml).join("");

      cardsEl.querySelectorAll<HTMLElement>(".kanban-card").forEach((card) => {
        card.addEventListener("dragstart", (e) => {
          (e as DragEvent).dataTransfer?.setData("text/plain", card.getAttribute("data-task-id") ?? "");
        });
      });
    });

    board.querySelectorAll<HTMLElement>(".kanban-cards").forEach((cardsEl) => {
      cardsEl.addEventListener("dragover", (e) => e.preventDefault());
      cardsEl.addEventListener("drop", (e) => {
        e.preventDefault();
        const taskId = (e as DragEvent).dataTransfer?.getData("text/plain");
        const targetStatus = cardsEl.getAttribute("data-status") as KanbanStatus | null;
        if (taskId && targetStatus) {
          statusByTaskId.set(taskId, targetStatus);
          renderColumns();
        }
      });
    });
  }

  renderColumns();
}
