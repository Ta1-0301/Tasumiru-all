// src/pipeline/format.ts
//
// Phase 10 の各画面で共通して使う表示ヘルパー。
// 既存のバッジ配色（.badge-priority の high=赤/medium=橙/low=緑）を
// 流用し、新しい配色体系は増やさない（タスみるの既存デザインを維持する方針）。
import { escapeHtml } from "../auth/util";
import type { PriorityLevel, DependencyType, AssignmentStatus, ValidationStatus } from "../types/pipeline";

export const UNAVAILABLE_TEXT = "—";
export const SOURCE_UNAVAILABLE_TEXT = "参照元情報がありません";

export function priorityBadgeHtml(priority: PriorityLevel): string {
  const cls = priority === "unknown" ? "unknown" : priority;
  const label = priority === "unknown" ? "不明" : priority.toUpperCase();
  return `<span class="badge-priority ${cls}">${label}</span>`;
}

// required=高(赤) / recommended=中(橙) / optional=低(緑) と、優先度バッジと
// 同じ配色マッピングで意味を揃える。
const DEP_TYPE_TO_PRIORITY_CLASS: Record<DependencyType, string> = {
  required: "high",
  recommended: "medium",
  optional: "low",
};
const DEP_TYPE_LABEL: Record<DependencyType, string> = {
  required: "必須",
  recommended: "推奨",
  optional: "任意",
};
export function dependencyTypeBadgeHtml(type: DependencyType): string {
  return `<span class="badge-priority ${DEP_TYPE_TO_PRIORITY_CLASS[type]}">${DEP_TYPE_LABEL[type]}</span>`;
}

const ASSIGNMENT_STATUS_LABEL: Record<AssignmentStatus, string> = {
  recommended: "推奨あり",
  no_suitable_member: "適任者なし",
};
const ASSIGNMENT_STATUS_CLASS: Record<AssignmentStatus, string> = {
  recommended: "low",
  no_suitable_member: "high",
};
export function assignmentStatusBadgeHtml(status: AssignmentStatus): string {
  return `<span class="badge-priority ${ASSIGNMENT_STATUS_CLASS[status]}">${ASSIGNMENT_STATUS_LABEL[status]}</span>`;
}

const VALIDATION_STATUS_LABEL: Record<ValidationStatus, string> = {
  valid: "OK",
  warning: "WARNING",
  error: "ERROR",
};
const VALIDATION_STATUS_CLASS: Record<ValidationStatus, string> = {
  valid: "low",
  warning: "medium",
  error: "high",
};
export function validationStatusBadgeHtml(status: ValidationStatus): string {
  return `<span class="badge-priority ${VALIDATION_STATUS_CLASS[status]}" style="font-size:11px;padding:3px 10px">${VALIDATION_STATUS_LABEL[status]}</span>`;
}

export function formatHours(hours: number | null): string {
  return hours === null ? UNAVAILABLE_TEXT : `${hours}h`;
}

export function formatPercent(value: number | null): string {
  return value === null ? UNAVAILABLE_TEXT : `${Math.round(value)}%`;
}

export function formatConfidence(confidence: number): string {
  return `${Math.round(confidence * 100)}%`;
}

export function formatOptionalText(value: string | null, fallback = UNAVAILABLE_TEXT): string {
  return value ? escapeHtml(value) : fallback;
}

export function scoreBarHtml(score: number, label: string): string {
  const clamped = Math.max(0, Math.min(100, score));
  return `
    <div class="score-bar-row">
      <span class="score-bar-label">${escapeHtml(label)}</span>
      <div class="score-bar-track"><div class="score-bar-fill" style="width:${clamped}%"></div></div>
      <span class="score-bar-value">${Math.round(clamped)}</span>
    </div>
  `;
}

// サンプルフィクスチャであることを常に画面上に明示するバナー。
// projectService.IS_SAMPLE_DATA が true の間、全パイプライン画面の先頭に表示する。
export function sampleDataBannerHtml(): string {
  return `
    <div class="sample-data-banner">
      <i data-lucide="triangle-alert"></i>
      <span>サンプルデータを表示しています。実際のバックエンド出力ではありません（パイプラインのHTTP公開待ち）。</span>
    </div>
  `;
}

// 【Phase 10.5】バックエンドAPI呼び出し（getProjectResult()等）が失敗した際に
// 表示するエラーバナー。.sample-data-banner と同じ構造だが、フェイクデータの
// 注意書きではなく実際のエラーであることが一目で分かるよう赤系の配色にする。
// 空のフォールバックコンテンツを出したり、UIをそのまま「読み込み中...」に
// 固まらせたりしないためのもの（Step 16/17）。
export function pipelineErrorBannerHtml(message: string, retryHint?: string): string {
  return `
    <div class="sample-data-banner" style="background:#fff1f2;color:#9f1239;border-color:#fecdd3">
      <i data-lucide="triangle-alert"></i>
      <span>${escapeHtml(message)}${retryHint ? `<br><span style="font-weight:400">${escapeHtml(retryHint)}</span>` : ""}</span>
    </div>
  `;
}

// axios/apiClient のインターセプター（api/client.ts）が投げる ApiError
// （{code, message}の素のオブジェクト、または稀にAxiosErrorそのもの）から、
// 表示に使える日本語メッセージを取り出す共通ヘルパー。
export function extractErrorMessage(err: unknown, fallback: string): string {
  if (err && typeof err === "object" && "message" in err) {
    const message = (err as { message?: unknown }).message;
    if (typeof message === "string" && message.trim()) return message;
  }
  return fallback;
}
