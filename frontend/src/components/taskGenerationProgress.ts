// src/components/taskGenerationProgress.ts
//
// AIタスク生成中の進捗UI。
//
// アーキテクチャ:
//   Page (app.ts)
//     ↓ mountTaskGenerationProgress(container, options)
//   TaskGenerationProgress component（このファイル）
//     ↓ createTaskGenerationProgressService()
//   Progress state/service（services/taskGenerationProgressService.ts）
//     ↓ 現時点
//   [フロントエンドのタイマーによる一時的なシミュレーション]
//
// 将来的には、Progress state/serviceの内部実装だけを
// Axios → FastAPI → 実際のパイプライン進捗のポーリングに差し替える想定
// （services/taskGenerationProgressService.ts 冒頭のコメント参照）。
// このコンポーネント・呼び出し側（app.ts）は無変更で動くように、
// 状態の形（TaskGenerationProgressState）を将来のバックエンド差し替えを
// 見越して設計している。
//
// Reactは使わず、他の画面（views/*.ts, components/kanban.ts）と同じく
// テンプレート文字列によるinnerHTML描画 + イベント再登録の方式に統一している。
import "./task-generation-progress.css";
import { escapeHtml } from "../auth/util";
import { createTaskGenerationProgressService } from "../services/taskGenerationProgressService";
import type { RealJobStatusLike } from "../services/taskGenerationProgressService";
import type {
  ProgressStep,
  StepId,
  TaskGenerationProgressState,
} from "../types/taskGenerationProgress";

export type { ProgressStep, StepId, TaskGenerationProgressState } from "../types/taskGenerationProgress";

export interface TaskGenerationProgressOptions {
  // キャンセルボタンが押された時に呼ばれる。実際のfetch/AbortControllerの
  // 中断はここで呼び出し側（app.ts）が行う。このコンポーネント自体は
  // バックエンド/LLM処理そのものを止める手段を持たない。
  onCancel?: () => void;
  // 再試行ボタンが押された時に呼ばれる。呼び出し側で本物の
  // /api/tasks/generate へのリクエストをやり直すために使う。
  onRetry?: () => void;
  // 完了時の「結果を確認」ボタンが押された時に呼ばれる。
  // 既存のタスク一覧画面への画面遷移は呼び出し側（app.ts）が行う。
  onConfirmResult?: () => void;
  // 状態が変わるたびに呼ばれる。呼び出し側が周辺UI（プレビューパネルの
  // 空状態など）の表示/非表示を同期させるためのフック。
  onStateChange?: (state: TaskGenerationProgressState) => void;
}

export interface TaskGenerationProgressHandle {
  start(): void;
  cancel(): void;
  retry(): void;
  reportOutcome(success: boolean, opts?: { message?: string; failedStep?: StepId }): void;
  // 【Phase 10.5】本物のジョブポーリング結果（GET /api/jobs/{job_id}）を
  // そのままこの進捗UIに反映する。呼び出し側（app.ts）がポーリングの
  // 都度これを呼ぶだけで、パーセンテージ・現在の処理・ステップ一覧・
  // 完了/エラー状態が全て本物のデータで更新される。
  applyRealStatus(payload: RealJobStatusLike): void;
  reset(): void;
  getState(): TaskGenerationProgressState;
  destroy(): void;
}

function stepIconHtml(status: ProgressStep["status"]): string {
  switch (status) {
    case "completed":
      return `<span class="tgp-step-icon is-completed"><i data-lucide="check"></i></span>`;
    case "running":
      return `<span class="tgp-step-icon is-running"><span class="tgp-dot"></span></span>`;
    case "error":
      return `<span class="tgp-step-icon is-error"><i data-lucide="circle-alert"></i></span>`;
    default:
      return `<span class="tgp-step-icon"></span>`;
  }
}

function render(state: TaskGenerationProgressState): string {
  if (state.status === "idle") return "";

  const isError = state.status === "error";
  const isCompleted = state.status === "completed";
  const isWaiting = state.status === "waiting";
  const isRunningLike = state.status === "running" || isWaiting;

  const titleText = isError
    ? "タスク生成でエラーが発生しました"
    : isCompleted
      ? "タスク生成が完了しました"
      : "AIタスク生成中";
  const titleClass = isError ? "is-error" : isCompleted ? "is-completed" : "";
  const titleIcon = isError
    ? '<i data-lucide="triangle-alert"></i>'
    : isCompleted
      ? '<i data-lucide="circle-check"></i>'
      : '<i data-lucide="sparkles"></i>';

  const barClass = isError ? "is-error" : isCompleted ? "is-completed" : isWaiting ? "is-waiting" : "";
  const percentageText = `${Math.round(state.percentage)}%`;

  const stepsHtml = state.steps
    .map((s) => {
      const cls =
        s.status === "completed" ? "is-completed" : s.status === "running" ? "is-running" : s.status === "error" ? "is-error" : "";
      return `<div class="tgp-step ${cls}">${stepIconHtml(s.status)}<span>${escapeHtml(s.label)}</span></div>`;
    })
    .join("");

  const currentMessageHtml = isWaiting
    ? `<i data-lucide="loader-circle" class="icon-spin"></i> ${escapeHtml(state.currentMessage)}`
    : escapeHtml(state.currentMessage);

  // isSimulated は現時点では常にtrue（本物の進捗APIが存在しないため）。
  // 「これはデモ用の擬似進捗であり、実バックエンドの進捗ではない」ことを
  // 常にユーザーへ明示する（要件: simulated/demo progress を明確に示すこと）。
  const simBannerHtml =
    state.isSimulated && !isCompleted
      ? `<div class="sample-data-banner"><i data-lucide="triangle-alert"></i><span>現在表示している進捗率はフロントエンドのデモ用シミュレーションです。実際のバックエンド処理の進捗とは連動していません。</span></div>`
      : "";

  const errorBoxHtml = isError
    ? `<div class="tgp-error-box"><i data-lucide="triangle-alert"></i><span>${escapeHtml(state.errorMessage ?? "タスク生成中にエラーが発生しました")}</span></div>`
    : "";

  const actionsHtml = isError
    ? `<div class="tgp-actions"><button type="button" class="btn-generate tgp-btn-retry"><i data-lucide="refresh-cw"></i> 再試行</button></div>`
    : isCompleted
      ? `<div class="tgp-actions"><button type="button" class="btn-generate tgp-btn-confirm"><i data-lucide="list-checks"></i> 結果を確認</button></div>`
      : `<div class="tgp-actions"><button type="button" class="btn-modal-cancel tgp-btn-cancel">キャンセル</button></div>`;

  const cancelNoteHtml = isRunningLike
    ? `<div class="tgp-cancel-note">※ キャンセルはこの画面上の表示のみを停止します。バックエンドで既に開始しているAI処理そのものは停止されません。</div>`
    : "";

  return `
    <div class="tgp-card">
      <div class="tgp-header">
        <div class="tgp-title ${titleClass}">${titleIcon} ${titleText}</div>
        <div class="tgp-percentage">${percentageText}</div>
      </div>

      <div class="tgp-bar-track"><div class="tgp-bar-fill ${barClass}" style="width:${Math.round(state.percentage)}%"></div></div>

      <div class="tgp-current">
        <span class="tgp-current-label">現在の処理</span>
        <span class="tgp-current-message">${currentMessageHtml}</span>
      </div>

      ${errorBoxHtml}

      <div class="tgp-steps">${stepsHtml}</div>

      ${simBannerHtml}

      <div class="tgp-hint"><i data-lucide="clock"></i> 処理には数分かかる場合があります</div>

      ${actionsHtml}
      ${cancelNoteHtml}
    </div>
  `;
}

export function mountTaskGenerationProgress(
  container: HTMLElement,
  options: TaskGenerationProgressOptions = {},
): TaskGenerationProgressHandle {
  const service = createTaskGenerationProgressService();

  function attachEvents(): void {
    container.querySelector(".tgp-btn-cancel")?.addEventListener("click", () => {
      service.cancel();
      options.onCancel?.();
    });
    container.querySelector(".tgp-btn-retry")?.addEventListener("click", () => {
      service.retry();
      options.onRetry?.();
    });
    container.querySelector(".tgp-btn-confirm")?.addEventListener("click", () => {
      options.onConfirmResult?.();
      service.reset();
    });
  }

  function paint(state: TaskGenerationProgressState): void {
    container.style.display = state.status === "idle" ? "none" : "block";
    container.innerHTML = render(state);
    attachEvents();
    options.onStateChange?.(state);
  }

  const unsubscribe = service.subscribe(paint);

  return {
    start: () => service.start(),
    cancel: () => {
      service.cancel();
      options.onCancel?.();
    },
    retry: () => {
      service.retry();
      options.onRetry?.();
    },
    reportOutcome: (success, opts) => service.reportOutcome(success, opts),
    applyRealStatus: (payload) => service.applyRealStatus(payload),
    reset: () => service.reset(),
    getState: () => service.getState(),
    destroy: () => {
      unsubscribe();
      service.destroy();
      container.innerHTML = "";
    },
  };
}
