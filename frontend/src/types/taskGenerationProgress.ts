// src/types/taskGenerationProgress.ts
//
// タスク生成中の進捗UI（TaskGenerationProgress）が扱う型定義。
// 表示層（components/taskGenerationProgress.ts）とサービス層
// （services/taskGenerationProgressService.ts）の両方から参照される、
// バックエンドの実装に依存しない共通の状態モデル。
//
// 現時点ではバックエンドは進捗情報を一切返さない（/api/tasks/generate は
// 完了時に結果をまとめて返すだけ）ため、途中経過はすべてフロントエンドの
// タイマーによるシミュレーションである。この型はその前提を変えずに、
// 将来バックエンドが本物の進捗を返せるようになった際にも UI 側を書き換えずに
// 済むように設計している。

export type StepId =
  | "specification"
  | "requirements"
  | "tasks"
  | "dependencies"
  | "members"
  | "assignments"
  | "validation"
  | "finalize";

export type StepStatus = "pending" | "running" | "completed" | "error";

export interface ProgressStep {
  id: StepId;
  label: string;
  status: StepStatus;
}

// "waiting" は仕様書には無いが、LLM処理がいつ終わるか分からない不確定な
// 待機区間（例: validation完了後、finalizeが来るまで）を表現するために追加した。
// "running" のサブ状態という位置付けで、UI側はこの状態を「進捗バーが止まって
// 見えても処理は続いている」という不確定表示に使う。
export type TaskGenerationStatus = "idle" | "running" | "waiting" | "completed" | "error";

export interface TaskGenerationProgressState {
  percentage: number;
  currentStep: StepId | "waiting" | "";
  currentMessage: string;
  steps: ProgressStep[];
  status: TaskGenerationStatus;
  // エラー時の詳細メッセージ（画面表示用）。エラーでない間は null。
  errorMessage: string | null;
  // 現在表示している percentage / currentMessage が実バックエンドの進捗ではなく
  // フロントエンドのシミュレーションであることを示すフラグ。
  // 本物の進捗APIに接続したら false にする（コンポーネント側の分岐はそのまま使える）。
  isSimulated: boolean;
}

// 将来バックエンドが返す想定の進捗ペイロード（実装はまだ存在しない、参考用）。
// 例えば GET /api/tasks/generate/{job_id}/progress のポーリング、または
// SSE/WebSocketで、以下の形が返ってくることを想定している。
export interface BackendProgressPayload {
  status: "running" | "completed" | "error";
  percentage: number;
  current_step: StepId;
  message: string;
}

export interface PipelineStepDefinition {
  id: StepId;
  label: string;
  // UIデモ用に決め打ちした仮の進捗率。LLMごとの処理時間の差が大きいため
  // 「完了ステップ数 / 全ステップ数」ではなく、ステップごとに明示的な値を持たせている。
  // 実際のバックエンド進捗を表すものではない。
  simulatedPercentage: number;
  runningMessage: string;
}

// 8ステップの定義。id・label・シミュレーション用進捗率・実行中メッセージは
// すべて要件で明示された値をそのまま使用している。
export const PIPELINE_STEPS: PipelineStepDefinition[] = [
  { id: "specification", label: "仕様書を解析", simulatedPercentage: 5, runningMessage: "仕様書を解析しています..." },
  { id: "requirements", label: "要件を抽出", simulatedPercentage: 20, runningMessage: "要件を抽出しています..." },
  { id: "tasks", label: "タスクを分解", simulatedPercentage: 40, runningMessage: "タスクを分解しています..." },
  { id: "dependencies", label: "依存関係を作成", simulatedPercentage: 55, runningMessage: "依存関係を分析しています..." },
  { id: "members", label: "メンバー情報を確認", simulatedPercentage: 65, runningMessage: "メンバー情報を確認しています..." },
  { id: "assignments", label: "タスクを割り振り", simulatedPercentage: 80, runningMessage: "タスクの割り振りを計算しています..." },
  { id: "validation", label: "結果を検証", simulatedPercentage: 90, runningMessage: "結果を検証しています..." },
  { id: "finalize", label: "結果を生成", simulatedPercentage: 100, runningMessage: "最終結果を生成しています..." },
];
