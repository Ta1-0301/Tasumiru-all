// src/services/taskGenerationProgressService.ts
//
// TaskGenerationProgress コンポーネントの状態を保持・更新する「Progress state/service」層。
//
// アーキテクチャ:
//   Page (app.ts)
//     → TaskGenerationProgress component (components/taskGenerationProgress.ts)
//       → この Progress state/service (このファイル)
//         → start() = [フロントエンドのタイマーによる一時的なシミュレーション]（デモ/オフライン専用）
//         → applyRealStatus() = 【Phase 10.5で接続済み】GET /api/jobs/{job_id} の
//           ポーリング結果（本物のstatus/progress/current_step/message）
//
// 【重要】start()（シミュレーション）が生成する途中経過は実際のバックエンド
// パイプラインの進捗とは一切連動しない、フロントエンドのみの疑似進捗である
// （isSimulated: true として明示）。本番のタスク生成フロー（app.tsの
// runTaskGeneration()）はもう start() を呼ばない — 実際の
// POST /api/projects/{id}/generate → job_id → GET /api/jobs/{job_id} の
// ポーリングを行い、その結果を都度 applyRealStatus() に渡すことで、
// 本物のstatus/progress/current_step/messageをそのまま画面に反映する
// （isSimulated: false）。start()自体は削除せず、フロントエンド単独の
// デモ/オフライン確認用として引き続き呼び出し可能にしてある。
import type {
  ProgressStep,
  StepId,
  StepStatus,
  TaskGenerationProgressState,
} from "../types/taskGenerationProgress";
import { PIPELINE_STEPS } from "../types/taskGenerationProgress";

// ステップごとのシミュレーション所要時間（ミリ秒、min-max でランダム化）。
// LLMを使うステップ（tasks / assignments 等）を長めにして、実際の処理特性に近づけている。
// finalize は仕様通り「シミュレーションでは自動到達しない」ため定義しない。
const STEP_DURATIONS_MS: Record<Exclude<StepId, "finalize">, [number, number]> = {
  specification: [2500, 4000],
  requirements: [3000, 5000],
  tasks: [5000, 8000],
  dependencies: [4000, 6500],
  members: [2000, 3500],
  assignments: [5000, 8000],
  validation: [3000, 5000],
};

const SIMULATION_STEP_IDS = PIPELINE_STEPS.filter((s) => s.id !== "finalize").map((s) => s.id);

function randomBetween(min: number, max: number): number {
  return Math.round(min + Math.random() * (max - min));
}

function findStepDef(id: StepId) {
  return PIPELINE_STEPS.find((s) => s.id === id);
}

function initialState(): TaskGenerationProgressState {
  return {
    status: "idle",
    percentage: 0,
    currentStep: "",
    currentMessage: "",
    steps: PIPELINE_STEPS.map((s) => ({ id: s.id, label: s.label, status: "pending" as StepStatus })),
    errorMessage: null,
    isSimulated: true,
  };
}

// GET /api/jobs/{job_id} のレスポンス形（JobStatusResponse）のうち、
// この進捗UIの表示に必要なフィールドだけを受け取る。types/job.ts の
// JobStatusResponse をそのまま渡せる（このサービス自体は特定のジョブAPIの
// 型に強く依存しないよう、必要なフィールドだけを構造的に受け取る設計）。
export interface RealJobStatusLike {
  status: "queued" | "running" | "completed" | "failed" | "cancelled";
  progress: number;
  current_step: string | null;
  message: string | null;
}

export interface TaskGenerationProgressService {
  getState(): TaskGenerationProgressState;
  subscribe(listener: (state: TaskGenerationProgressState) => void): () => void;
  start(): void;
  cancel(): void;
  retry(): void;
  reportOutcome(success: boolean, opts?: { message?: string; failedStep?: StepId }): void;
  // 【Phase 10.5】本物のジョブポーリング結果をそのまま状態に反映する。
  // シミュレーション（start()）とは排他— 呼ばれた時点で進行中のシミュレーション
  // タイマーは破棄され、以後は呼び出し側（app.ts）が渡すデータだけが表示される。
  applyRealStatus(payload: RealJobStatusLike): void;
  reset(): void;
  destroy(): void;
}

export function createTaskGenerationProgressService(): TaskGenerationProgressService {
  let state: TaskGenerationProgressState = initialState();
  const listeners = new Set<(state: TaskGenerationProgressState) => void>();
  let timers: ReturnType<typeof setTimeout>[] = [];
  // start()/cancel()/reportOutcome() のたびにインクリメントし、進行中の
  // setTimeoutコールバックが「もう無効な実行」だと分かるようにするためのトークン。
  let runToken = 0;

  // 開発時のみ: URLクエリで待機状態・エラー状態・完了状態を手動で再現できるようにする
  // デバッグ用フック。本番ビルドや通常のapp.tsからの呼び出しでは一切使われない
  // （app.tsは常にreportOutcome()で本物のfetch結果を渡すため、これらのクエリは無視される）。
  const devHooks = (() => {
    if (!import.meta.env.DEV || typeof window === "undefined") return null;
    const q = new URLSearchParams(window.location.search);
    return {
      forceErrorStep: (q.get("tgpForceError") as StepId | null) ?? null,
      autoComplete: q.get("tgpAutoComplete") === "1",
    };
  })();

  function emit() {
    listeners.forEach((listener) => listener(state));
  }

  function clearTimers() {
    timers.forEach(clearTimeout);
    timers = [];
  }

  function setStepStatus(id: StepId, status: StepStatus) {
    state = {
      ...state,
      steps: state.steps.map((s: ProgressStep) => (s.id === id ? { ...s, status } : s)),
    };
  }

  function runStep(token: number, index: number) {
    if (token !== runToken) return; // cancel/retry/reportOutcome等により無効化された実行

    const def = PIPELINE_STEPS[index];

    // validation（最後のシミュレーション対象ステップ）まで終わったら、
    // 「実際にいつ終わるか分からない」不確定な待機状態に入る。
    // ここでは絶対に自動でfinalize/100%へは進めない
    // （= 呼び出し側からreportOutcome(true)が来るまで完了を騙らない）。
    if (!def || def.id === "finalize") {
      state = {
        ...state,
        status: "waiting",
        currentStep: "waiting",
        currentMessage: "LLMの処理を待っています...",
      };
      emit();

      if (devHooks?.autoComplete) {
        const t = setTimeout(() => {
          if (token !== runToken) return;
          reportOutcome(true);
        }, randomBetween(4000, 8000));
        timers.push(t);
      }
      return;
    }

    if (devHooks?.forceErrorStep === def.id) {
      const t = setTimeout(() => {
        if (token !== runToken) return;
        reportOutcome(false, {
          message: `（開発用シミュレーション）${def.label}中にエラーが発生しました`,
          failedStep: def.id,
        });
      }, randomBetween(1000, 2000));
      timers.push(t);
      return;
    }

    if (index > 0) {
      setStepStatus(PIPELINE_STEPS[index - 1].id, "completed");
    }
    setStepStatus(def.id, "running");
    state = {
      ...state,
      status: "running",
      percentage: def.simulatedPercentage,
      currentStep: def.id,
      currentMessage: def.runningMessage,
    };
    emit();

    const [min, max] = STEP_DURATIONS_MS[def.id as Exclude<StepId, "finalize">];
    const t = setTimeout(() => runStep(token, index + 1), randomBetween(min, max));
    timers.push(t);
  }

  function start(): void {
    clearTimers();
    const token = ++runToken;
    state = { ...initialState(), status: "running" };
    emit();
    runStep(token, 0);
  }

  function cancel(): void {
    clearTimers();
    runToken += 1;
    state = initialState();
    emit();
  }

  function retry(): void {
    // 「フロントエンドのデモ状態」をリセットしてシミュレーションを最初から
    // 再生するだけ。バックエンドへの再リクエストは呼び出し側（app.ts）の責務。
    start();
  }

  function reportOutcome(success: boolean, opts?: { message?: string; failedStep?: StepId }): void {
    clearTimers();
    runToken += 1;

    if (success) {
      state = {
        ...state,
        status: "completed",
        percentage: 100,
        currentStep: "finalize",
        currentMessage: "タスク生成が完了しました",
        errorMessage: null,
        steps: state.steps.map((s) => ({ ...s, status: "completed" as StepStatus })),
      };
    } else {
      const fallback = "タスク生成中にエラーが発生しました";
      const failedId = opts?.failedStep ?? (findStepDef(state.currentStep as StepId) ? (state.currentStep as StepId) : SIMULATION_STEP_IDS[0]);
      state = {
        ...state,
        status: "error",
        errorMessage: opts?.message ?? fallback,
        currentMessage: opts?.message ?? fallback,
        steps: state.steps.map((s) => {
          if (s.id === failedId) return { ...s, status: "error" as StepStatus };
          if (s.status === "running") return { ...s, status: "pending" as StepStatus };
          return s;
        }),
      };
    }
    emit();
  }

  function reset(): void {
    clearTimers();
    runToken += 1;
    state = initialState();
    emit();
  }

  function applyRealStatus(payload: RealJobStatusLike): void {
    clearTimers();
    runToken += 1; // 進行中のシミュレーションタイマー（あれば）を確実に無効化する

    const stepIndex = PIPELINE_STEPS.findIndex((s) => s.id === payload.current_step);
    const steps: ProgressStep[] = PIPELINE_STEPS.map((def, idx) => {
      let stepStatus: StepStatus = "pending";
      if (payload.status === "completed") {
        stepStatus = "completed";
      } else if (payload.status === "failed" && idx === stepIndex) {
        stepStatus = "error";
      } else if (stepIndex >= 0 && idx < stepIndex) {
        stepStatus = "completed";
      } else if (stepIndex >= 0 && idx === stepIndex && (payload.status === "running" || payload.status === "queued")) {
        stepStatus = "running";
      }
      return { id: def.id, label: def.label, status: stepStatus };
    });

    let mappedStatus: TaskGenerationProgressState["status"];
    if (payload.status === "completed") mappedStatus = "completed";
    else if (payload.status === "failed") mappedStatus = "error";
    else if (payload.status === "cancelled") mappedStatus = "idle";
    else mappedStatus = "running"; // "queued" | "running"

    const fallbackMessage = payload.status === "queued" ? "準備中..." : "";

    state = {
      status: mappedStatus,
      percentage: payload.status === "completed" ? 100 : Math.max(0, Math.min(100, payload.progress)),
      currentStep: (payload.current_step as StepId | null) ?? "",
      currentMessage: payload.message ?? fallbackMessage,
      steps,
      errorMessage: payload.status === "failed" ? (payload.message ?? "タスク生成中にエラーが発生しました") : null,
      // これは本物のバックエンド進捗であり、シミュレーションではない。
      isSimulated: false,
    };
    emit();
  }

  function getState(): TaskGenerationProgressState {
    return state;
  }

  function subscribe(listener: (state: TaskGenerationProgressState) => void): () => void {
    listeners.add(listener);
    listener(state);
    return () => listeners.delete(listener);
  }

  function destroy(): void {
    clearTimers();
    listeners.clear();
  }

  return { getState, subscribe, start, cancel, retry, reportOutcome, applyRealStatus, reset, destroy };
}
