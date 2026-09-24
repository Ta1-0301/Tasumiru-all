// src/views/requirementsView.ts
//
// 画面: 要件レビュー（Requirements review, Phase 3の結果を可視化）。
// 表示: 要件ID / 説明 / 参照元 / 関連タスク。
import { getRequirements } from "../services/requirementService";
import { getPipelineTasks } from "../services/taskService";
import { escapeHtml } from "../auth/util";
import { IS_SAMPLE_DATA } from "../services/projectService";
import {
  sampleDataBannerHtml,
  pipelineErrorBannerHtml,
  extractErrorMessage,
  priorityBadgeHtml,
  formatConfidence,
  SOURCE_UNAVAILABLE_TEXT,
} from "../pipeline/format";
import type { PipelineTask, Requirement, SourceReference } from "../types/pipeline";

const REQUIREMENT_TYPE_LABEL: Record<string, string> = {
  system_purpose: "システム目的",
  target_user: "対象ユーザー",
  functional: "機能要件",
  non_functional: "非機能要件",
  constraint: "制約",
  assumption: "前提条件",
  deliverable: "成果物",
  technical: "技術要件",
  business_rule: "業務ルール",
};

function sourceReferenceHtml(ref: SourceReference | null): string {
  if (!ref) return `<span class="auth-hint">${SOURCE_UNAVAILABLE_TEXT}</span>`;
  const parts: string[] = [];
  if (ref.section) parts.push(escapeHtml(ref.section));
  if (ref.page !== null) parts.push(`p.${ref.page}`);
  if (ref.paragraph) parts.push(`段落${escapeHtml(ref.paragraph)}`);
  const location = parts.length > 0 ? parts.join(" / ") : ref.document_id;
  const excerpt = ref.source_text
    ? `「${escapeHtml(ref.source_text)}」`
    : "";
  return `<span>${escapeHtml(location)}</span>${excerpt ? `<div class="req-card-source-excerpt">${excerpt}</div>` : ""}`;
}

function relatedTasksHtml(requirement: Requirement, tasks: PipelineTask[]): string {
  const related = tasks.filter((t) => t.requirement_ids.includes(requirement.id));
  if (related.length === 0) {
    return `<span class="auth-hint">関連タスクなし</span>`;
  }
  return related
    .map(
      (t) =>
        `<span class="m-tag" title="${escapeHtml(t.title)}">${escapeHtml(t.id)} — ${escapeHtml(t.title)}</span>`,
    )
    .join("");
}

function requirementCardHtml(requirement: Requirement, tasks: PipelineTask[]): string {
  return `
    <div class="req-card">
      <div class="req-card-top">
        <span class="req-card-id">${escapeHtml(requirement.id)}</span>
        ${priorityBadgeHtml(requirement.priority)}
        <span class="req-card-type">${REQUIREMENT_TYPE_LABEL[requirement.type] ?? requirement.type}</span>
        <span class="req-card-origin">${requirement.origin === "explicit" ? "明示要件" : "推測要件（要確認）"}・確信度${formatConfidence(requirement.confidence)}</span>
      </div>
      <div class="req-card-title">${escapeHtml(requirement.title)}</div>
      <div class="req-card-desc">${escapeHtml(requirement.description)}</div>
      <div class="req-card-meta">
        <div class="preview-meta-item"><i data-lucide="file-text"></i>参照元: ${sourceReferenceHtml(requirement.source_reference)}</div>
      </div>
      <div class="req-card-tasks">
        <div class="req-card-tasks-label"><i data-lucide="list-tree"></i> 関連タスク</div>
        <div class="m-tags">${relatedTasksHtml(requirement, tasks)}</div>
      </div>
    </div>
  `;
}

export async function renderRequirementsView(container: HTMLElement): Promise<void> {
  container.innerHTML = `
    <div class="sec-header sec-header-page">
      <div class="sec-header-icon"><i data-lucide="clipboard-list"></i></div>
      <span class="sec-header-title">要件レビュー</span>
    </div>
    <div class="sec-body" style="padding: 20px">
      ${IS_SAMPLE_DATA ? sampleDataBannerHtml() : ""}
      <div id="req-list-container">読み込み中...</div>
    </div>
  `;

  const listContainer = container.querySelector("#req-list-container") as HTMLElement;
  let requirements: Requirement[];
  let tasks: PipelineTask[];
  try {
    [requirements, tasks] = await Promise.all([getRequirements(), getPipelineTasks()]);
  } catch (err) {
    listContainer.innerHTML = pipelineErrorBannerHtml(
      extractErrorMessage(err, "要件データの取得に失敗しました。"),
    );
    return;
  }

  if (requirements.length === 0) {
    listContainer.innerHTML = `<div class="auth-hint">要件データがありません。</div>`;
    return;
  }

  listContainer.innerHTML = `
    <div class="req-list">
      ${requirements.map((r) => requirementCardHtml(r, tasks)).join("")}
    </div>
  `;
}
