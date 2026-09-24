// src/views/pipelineTasksView.ts
//
// 画面: タスクレビュー（Task review, Phase 4の結果を可視化）。
// 表示: タスクID / タイトル / 説明 / 優先度 / 見積工数 / 必要スキル /
//       参照元 / 依存関係 / 担当者。ソート・フィルタ・優先度バッジ対応。
import { getPipelineTasks } from "../services/taskService";
import { getDependencies } from "../services/dependencyService";
import { getAssignments } from "../services/assignmentService";
import { getPipelineMembers } from "../services/memberService";
import { escapeHtml } from "../auth/util";
import { IS_SAMPLE_DATA } from "../services/projectService";
import {
  sampleDataBannerHtml,
  pipelineErrorBannerHtml,
  extractErrorMessage,
  priorityBadgeHtml,
  formatHours,
  SOURCE_UNAVAILABLE_TEXT,
  UNAVAILABLE_TEXT,
} from "../pipeline/format";
import type {
  Dependency,
  FinalAssignment,
  PipelineMember,
  PipelineTask,
  PriorityLevel,
} from "../types/pipeline";

type SortKey = "id" | "priority" | "estimated_hours";
type SortDir = "asc" | "desc";

const PRIORITY_ORDER: Record<PriorityLevel, number> = {
  high: 0,
  medium: 1,
  low: 2,
  unknown: 3,
};

interface PageState {
  search: string;
  priority: PriorityLevel | "all";
  sortKey: SortKey;
  sortDir: SortDir;
}

function dependencySummaryHtml(task: PipelineTask, dependencies: Dependency[]): string {
  const blockedBy = dependencies.filter((d) => d.to_task_id === task.id);
  const blocks = dependencies.filter((d) => d.from_task_id === task.id);
  if (blockedBy.length === 0 && blocks.length === 0) {
    return `<span class="auth-hint">依存なし</span>`;
  }
  const lines: string[] = [];
  if (blockedBy.length > 0) {
    lines.push(
      `<div><i data-lucide="arrow-left"></i> 前提: ${blockedBy.map((d) => escapeHtml(d.from_task_id)).join(", ")}</div>`,
    );
  }
  if (blocks.length > 0) {
    lines.push(
      `<div><i data-lucide="arrow-right"></i> 後続: ${blocks.map((d) => escapeHtml(d.to_task_id)).join(", ")}</div>`,
    );
  }
  return lines.join("");
}

function assigneeHtml(
  task: PipelineTask,
  assignments: FinalAssignment[],
  members: PipelineMember[],
): string {
  const assignment = assignments.find((a) => a.task_id === task.id);
  if (!assignment || !assignment.assigned_member_id) {
    return `<span class="auth-hint">未割り当て</span>`;
  }
  const member = members.find((m) => m.id === assignment.assigned_member_id);
  const name = member ? escapeHtml(member.name) : escapeHtml(assignment.assigned_member_id);
  const decidedBy = assignment.decided_by === "human" ? "人手" : "AI";
  return `<span style="background:#f5ece2;padding:2px 6px;border-radius:4px;font-weight:500">${name}</span><div class="auth-hint" style="margin-top:2px">${decidedBy}決定${assignment.overridden ? "・上書き" : ""}</div>`;
}

function taskRowHtml(
  task: PipelineTask,
  dependencies: Dependency[],
  assignments: FinalAssignment[],
  members: PipelineMember[],
): string {
  const sourceText = task.source_reference
    ? `${escapeHtml(task.source_reference.section ?? task.source_reference.document_id)}`
    : `<span class="auth-hint">${SOURCE_UNAVAILABLE_TEXT}</span>`;

  return `
    <tr>
      <td style="font-weight:600;color:var(--brand-mid);white-space:nowrap">${escapeHtml(task.id)}</td>
      <td style="min-width:220px">
        <div style="font-weight:600">${escapeHtml(task.title)}</div>
        <div class="auth-hint" style="margin-top:2px">${escapeHtml(task.description)}</div>
        ${task.needs_review ? `<div class="req-card-origin" style="margin-top:4px;color:#e11d48"><i data-lucide="circle-alert"></i> 要確認: ${task.review_reasons.map(escapeHtml).join(" / ")}</div>` : ""}
      </td>
      <td>${priorityBadgeHtml(task.priority)}</td>
      <td>${formatHours(task.estimated_hours)}</td>
      <td>
        ${
          task.required_skills.length > 0
            ? `<div class="m-tags">${task.required_skills.map((s) => `<span class="m-tag">${escapeHtml(s)}</span>`).join("")}</div>`
            : `<span class="auth-hint">${UNAVAILABLE_TEXT}</span>`
        }
      </td>
      <td style="font-size:11px;color:#666">${sourceText}</td>
      <td style="font-size:11px">${dependencySummaryHtml(task, dependencies)}</td>
      <td>${assigneeHtml(task, assignments, members)}</td>
    </tr>
  `;
}

function sortIndicator(state: PageState, key: SortKey): string {
  if (state.sortKey !== key) return "";
  return state.sortDir === "asc" ? " ▲" : " ▼";
}

export async function renderPipelineTasksView(container: HTMLElement): Promise<void> {
  container.innerHTML = `
    <div class="sec-header sec-header-page">
      <div class="sec-header-icon"><i data-lucide="list-checks"></i></div>
      <span class="sec-header-title">タスクレビュー</span>
    </div>
    <div class="sec-body" style="padding: 16px">
      ${IS_SAMPLE_DATA ? sampleDataBannerHtml() : ""}
      <div style="display:flex;gap:8px;margin-bottom:12px;flex-wrap:wrap;align-items:center">
        <input class="input-member" id="pt-search" style="width:220px" placeholder="タイトルで検索..." />
        <select class="project-select" id="pt-priority-filter" style="width:160px">
          <option value="all">すべての優先度</option>
          <option value="high">HIGH</option>
          <option value="medium">MEDIUM</option>
          <option value="low">LOW</option>
          <option value="unknown">不明</option>
        </select>
        <span class="auth-hint" id="pt-count"></span>
      </div>
      <div style="overflow-x:auto">
        <table class="task-table" id="pt-table">
          <thead>
            <tr>
              <th class="pt-sortable" data-sort="id" style="cursor:pointer">ID</th>
              <th>タイトル / 説明</th>
              <th class="pt-sortable" data-sort="priority" style="cursor:pointer">優先度</th>
              <th class="pt-sortable" data-sort="estimated_hours" style="cursor:pointer">見積工数</th>
              <th>必要スキル</th>
              <th>参照元</th>
              <th>依存関係</th>
              <th>担当者</th>
            </tr>
          </thead>
          <tbody id="pt-tbody"></tbody>
        </table>
      </div>
    </div>
  `;

  const searchInput = container.querySelector("#pt-search") as HTMLInputElement;
  const priorityFilter = container.querySelector("#pt-priority-filter") as HTMLSelectElement;
  const tbody = container.querySelector("#pt-tbody") as HTMLElement;
  const countEl = container.querySelector("#pt-count") as HTMLElement;
  const headerCells = container.querySelectorAll<HTMLElement>(".pt-sortable");

  let tasks: PipelineTask[];
  let dependencies: Dependency[];
  let assignments: FinalAssignment[];
  let members: PipelineMember[];
  try {
    [tasks, dependencies, assignments, members] = await Promise.all([
      getPipelineTasks(),
      getDependencies(),
      getAssignments(),
      getPipelineMembers(),
    ]);
  } catch (err) {
    searchInput.disabled = true;
    priorityFilter.disabled = true;
    tbody.innerHTML = `<tr><td colspan="8" style="text-align:center;padding:20px;color:#9f1239">${escapeHtml(extractErrorMessage(err, "タスクデータの取得に失敗しました。"))}</td></tr>`;
    countEl.textContent = "";
    return;
  }

  const state: PageState = { search: "", priority: "all", sortKey: "id", sortDir: "asc" };

  function renderRows(): void {
    let filtered = tasks.filter((t) => {
      const matchesSearch =
        state.search === "" || t.title.toLowerCase().includes(state.search.toLowerCase());
      const matchesPriority = state.priority === "all" || t.priority === state.priority;
      return matchesSearch && matchesPriority;
    });

    filtered = filtered.sort((a, b) => {
      let cmp = 0;
      if (state.sortKey === "id") cmp = a.id.localeCompare(b.id);
      else if (state.sortKey === "priority")
        cmp = PRIORITY_ORDER[a.priority] - PRIORITY_ORDER[b.priority];
      else if (state.sortKey === "estimated_hours")
        cmp = (a.estimated_hours ?? -1) - (b.estimated_hours ?? -1);
      return state.sortDir === "asc" ? cmp : -cmp;
    });

    tbody.innerHTML = filtered.length
      ? filtered.map((t) => taskRowHtml(t, dependencies, assignments, members)).join("")
      : `<tr><td colspan="8" class="auth-hint" style="text-align:center;padding:20px">条件に一致するタスクがありません。</td></tr>`;

    countEl.textContent = `${filtered.length} / ${tasks.length} 件`;

    headerCells.forEach((th) => {
      const key = th.getAttribute("data-sort") as SortKey;
      const label = { id: "ID", priority: "優先度", estimated_hours: "見積工数" }[key];
      th.textContent = label + sortIndicator(state, key);
    });
  }

  searchInput.addEventListener("input", () => {
    state.search = searchInput.value;
    renderRows();
  });
  priorityFilter.addEventListener("change", () => {
    state.priority = priorityFilter.value as PriorityLevel | "all";
    renderRows();
  });
  headerCells.forEach((th) => {
    th.addEventListener("click", () => {
      const key = th.getAttribute("data-sort") as SortKey;
      if (state.sortKey === key) {
        state.sortDir = state.sortDir === "asc" ? "desc" : "asc";
      } else {
        state.sortKey = key;
        state.sortDir = "asc";
      }
      renderRows();
    });
  });

  if (tasks.length === 0) {
    tbody.innerHTML = `<tr><td colspan="8" class="auth-hint" style="text-align:center;padding:20px">タスクデータがありません。</td></tr>`;
    countEl.textContent = "0 / 0 件";
    return;
  }

  renderRows();
}
