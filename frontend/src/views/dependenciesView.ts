// src/views/dependenciesView.ts
//
// 画面: 依存関係ビュー（Dependency view, Phase 5の結果を可視化）。
// 表示: 起点タスク → 終点タスク / 依存タイプ / 理由 / 確信度。
// バリデーション結果（Phase 8）の dependency_errors があれば明示する。
import { getDependencies } from "../services/dependencyService";
import { getPipelineTasks } from "../services/taskService";
import { getValidationSummary } from "../services/validationService";
import { escapeHtml } from "../auth/util";
import { IS_SAMPLE_DATA } from "../services/projectService";
import {
  sampleDataBannerHtml,
  pipelineErrorBannerHtml,
  extractErrorMessage,
  dependencyTypeBadgeHtml,
  formatConfidence,
} from "../pipeline/format";
import type { Dependency, DependencyError, PipelineTask, ValidationSummary } from "../types/pipeline";

function taskLabel(taskId: string, tasks: PipelineTask[]): string {
  const task = tasks.find((t) => t.id === taskId);
  return task ? `${escapeHtml(taskId)} — ${escapeHtml(task.title)}` : escapeHtml(taskId);
}

function dependencyRowHtml(dep: Dependency, tasks: PipelineTask[]): string {
  return `
    <div class="dep-row">
      <div class="dep-row-chain">
        <span class="dep-task-pill">${taskLabel(dep.from_task_id, tasks)}</span>
        <i data-lucide="arrow-right" class="dep-arrow"></i>
        <span class="dep-task-pill">${taskLabel(dep.to_task_id, tasks)}</span>
      </div>
      <div class="dep-row-meta">
        ${dependencyTypeBadgeHtml(dep.type)}
        <span class="auth-hint">確信度 ${formatConfidence(dep.confidence)}</span>
      </div>
      <div class="dep-row-reason">${escapeHtml(dep.reason || "（理由の記載なし）")}</div>
    </div>
  `;
}

function dependencyErrorHtml(err: DependencyError, tasks: PipelineTask[]): string {
  return `
    <div class="validation-issue-card error">
      <div class="validation-issue-code">${escapeHtml(err.code)}</div>
      <div class="validation-issue-message">${escapeHtml(err.message)}</div>
      <div class="validation-issue-refs">対象タスク: ${err.task_ids.map((id) => taskLabel(id, tasks)).join(" / ")}</div>
    </div>
  `;
}

export async function renderDependenciesView(container: HTMLElement): Promise<void> {
  container.innerHTML = `
    <div class="sec-header sec-header-page">
      <div class="sec-header-icon"><i data-lucide="git-branch"></i></div>
      <span class="sec-header-title">依存関係ビュー</span>
    </div>
    <div class="sec-body" style="padding: 20px">
      ${IS_SAMPLE_DATA ? sampleDataBannerHtml() : ""}
      <div id="dep-errors-container" style="margin-bottom: 16px"></div>
      <div id="dep-list-container">読み込み中...</div>
    </div>
  `;

  const errorsContainer = container.querySelector("#dep-errors-container") as HTMLElement;
  const listContainer = container.querySelector("#dep-list-container") as HTMLElement;

  let dependencies: Dependency[];
  let tasks: PipelineTask[];
  let validation: ValidationSummary;
  try {
    [dependencies, tasks, validation] = await Promise.all([
      getDependencies(),
      getPipelineTasks(),
      getValidationSummary(),
    ]);
  } catch (err) {
    listContainer.innerHTML = pipelineErrorBannerHtml(
      extractErrorMessage(err, "依存関係データの取得に失敗しました。"),
    );
    return;
  }
  const dependencyErrors = validation.report.dependency_errors;
  if (dependencyErrors.length > 0) {
    errorsContainer.innerHTML = `
      <div class="sec-header" style="margin-bottom:8px">
        <div class="sec-header-icon" style="color:#e11d48"><i data-lucide="triangle-alert"></i></div>
        <span class="sec-header-title" style="color:#e11d48">依存関係エラー</span>
      </div>
      ${dependencyErrors.map((e) => dependencyErrorHtml(e, tasks)).join("")}
    `;
  }

  if (dependencies.length === 0) {
    listContainer.innerHTML = `<div class="auth-hint">依存関係データがありません。</div>`;
    return;
  }

  listContainer.innerHTML = `
    <div class="dep-list">
      ${dependencies.map((d) => dependencyRowHtml(d, tasks)).join("")}
    </div>
  `;
}
