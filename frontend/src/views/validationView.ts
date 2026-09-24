// src/views/validationView.ts
//
// 画面: 検証結果（Validation results, Phase 8/9の結果を可視化）。
// 表示: 欠落要件 / 重複タスク / 依存関係エラー / 稼働超過警告 /
//       スキル不一致 / 制約違反。OK/WARNING/ERRORの状態を明示し、
//       問題を隠さない。
import { getValidationSummary } from "../services/validationService";
import { escapeHtml } from "../auth/util";
import { IS_SAMPLE_DATA } from "../services/projectService";
import {
  sampleDataBannerHtml,
  pipelineErrorBannerHtml,
  extractErrorMessage,
  validationStatusBadgeHtml,
  formatPercent,
} from "../pipeline/format";
import type { ValidationSummary } from "../types/pipeline";

function sectionHtml(
  title: string,
  icon: string,
  severity: "error" | "warning",
  items: string[],
): string {
  if (items.length === 0) {
    return `
      <div class="validation-section">
        <div class="sec-header" style="border-bottom:none;padding-bottom:6px">
          <div class="sec-header-icon"><i data-lucide="${icon}"></i></div>
          <span class="sec-header-title">${title}</span>
          <span class="badge-priority low" style="margin-left:auto">問題なし</span>
        </div>
      </div>
    `;
  }
  return `
    <div class="validation-section">
      <div class="sec-header" style="border-bottom:none;padding-bottom:6px">
        <div class="sec-header-icon"><i data-lucide="${icon}"></i></div>
        <span class="sec-header-title">${title}</span>
        <span class="badge-priority ${severity === "error" ? "high" : "medium"}" style="margin-left:auto">${items.length}件</span>
      </div>
      ${items.map((html) => `<div class="validation-issue-card ${severity}">${html}</div>`).join("")}
    </div>
  `;
}

export async function renderValidationView(container: HTMLElement): Promise<void> {
  container.innerHTML = `
    <div class="sec-header sec-header-page">
      <div class="sec-header-icon"><i data-lucide="shield-check"></i></div>
      <span class="sec-header-title">検証結果</span>
    </div>
    <div class="sec-body" style="padding: 20px">
      ${IS_SAMPLE_DATA ? sampleDataBannerHtml() : ""}
      <div id="validation-summary-container">読み込み中...</div>
    </div>
  `;

  const summaryContainer = container.querySelector("#validation-summary-container") as HTMLElement;
  let validation: ValidationSummary;
  try {
    validation = await getValidationSummary();
  } catch (err) {
    summaryContainer.innerHTML = pipelineErrorBannerHtml(
      extractErrorMessage(err, "検証結果の取得に失敗しました。"),
    );
    return;
  }
  const report = validation.report;

  summaryContainer.innerHTML = `
    <div class="validation-status-header">
      ${validationStatusBadgeHtml(validation.status)}
      <div class="validation-status-counts">
        <span>重大な問題: <b>${validation.critical_issue_count}</b>件</span>
        <span>警告: <b>${validation.warning_issue_count}</b>件</span>
      </div>
      ${report.generated_at ? `<span class="auth-hint">検証日時: ${escapeHtml(report.generated_at)}</span>` : ""}
    </div>

    ${sectionHtml(
      "整合性エラー（トレーサビリティ）",
      "link",
      "error",
      validation.traceability_errors.map(
        (e) =>
          `<div class="validation-issue-code">${escapeHtml(e.code)}</div><div class="validation-issue-message">${escapeHtml(e.message)}</div>${e.task_id ? `<div class="validation-issue-refs">対象タスク: ${escapeHtml(e.task_id)}</div>` : ""}`,
      ),
    )}

    ${sectionHtml(
      "欠落要件",
      "file-x",
      "error",
      report.missing_requirements.map(
        (m) => `<div class="validation-issue-refs">要件: ${escapeHtml(m.requirement_id)}</div><div class="validation-issue-message">${escapeHtml(m.message)}</div>`,
      ),
    )}

    ${sectionHtml(
      "重複タスク",
      "copy",
      "warning",
      report.duplicate_tasks.map(
        (d) =>
          `<div class="validation-issue-refs">対象: ${d.task_ids.map(escapeHtml).join(" / ")}（類似度 ${Math.round(d.similarity * 100)}%・検出方法: ${escapeHtml(d.method)}）</div><div class="validation-issue-message">${escapeHtml(d.reason)}</div>`,
      ),
    )}

    ${sectionHtml(
      "依存関係エラー",
      "git-branch",
      "error",
      report.dependency_errors.map(
        (d) => `<div class="validation-issue-code">${escapeHtml(d.code)}</div><div class="validation-issue-message">${escapeHtml(d.message)}</div><div class="validation-issue-refs">対象タスク: ${d.task_ids.map(escapeHtml).join(" / ")}</div>`,
      ),
    )}

    ${sectionHtml(
      "稼働超過警告",
      "gauge",
      "warning",
      report.workload_warnings.map(
        (w) =>
          `<div class="validation-issue-refs">メンバー: ${escapeHtml(w.member_id)}（${escapeHtml(w.code)}）</div><div class="validation-issue-message">${escapeHtml(w.message)}</div><div class="auth-hint">割当 ${w.assigned_hours}h / 可能 ${w.available_hours}h（残り${w.remaining_capacity}h・稼働率${formatPercent(w.workload_percentage)}）</div>`,
      ),
    )}

    ${sectionHtml(
      "スキル不一致",
      "wrench",
      "warning",
      report.skill_mismatches.map(
        (s) =>
          `<div class="validation-issue-refs">タスク: ${escapeHtml(s.task_id)} / メンバー: ${escapeHtml(s.member_id)}</div><div class="validation-issue-message">${escapeHtml(s.message)}</div><div class="auth-hint">スキル「${escapeHtml(s.skill)}」要求Lv.${s.required_level} / 保有Lv.${s.member_level}</div>`,
      ),
    )}

    ${sectionHtml(
      "制約違反",
      "lock",
      "error",
      report.constraint_violations.map(
        (c) => `<div class="validation-issue-refs">タスク: ${escapeHtml(c.task_id)} / メンバー: ${escapeHtml(c.member_id)}（${escapeHtml(c.code)}）</div><div class="validation-issue-message">${escapeHtml(c.message)}</div>`,
      ),
    )}

    <div class="validation-section">
      <div class="sec-header" style="border-bottom:none;padding-bottom:6px">
        <div class="sec-header-icon"><i data-lucide="chart-bar"></i></div>
        <span class="sec-header-title">メンバー稼働サマリー</span>
      </div>
      ${
        report.workload_summaries.length > 0
          ? `<div style="overflow-x:auto"><table class="task-table"><thead><tr>
              <th>メンバー</th><th>割当時間</th><th>稼働可能時間</th><th>残キャパシティ</th><th>稼働率</th>
            </tr></thead><tbody>
              ${report.workload_summaries
                .map(
                  (w) =>
                    `<tr><td>${escapeHtml(w.member_id)}</td><td>${w.assigned_hours}h</td><td>${w.available_hours}h</td><td>${w.remaining_capacity}h</td><td>${formatPercent(w.workload_percentage)}</td></tr>`,
                )
                .join("")}
            </tbody></table></div>`
          : `<span class="auth-hint">稼働サマリーデータがありません。</span>`
      }
    </div>
  `;
}
