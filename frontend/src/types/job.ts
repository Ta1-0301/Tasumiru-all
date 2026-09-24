// src/types/job.ts
//
// 非同期タスク生成ジョブ（Phase 10.5で追加された /api/projects/{id}/generate
// と /api/jobs/{job_id}* 系）に対応する型定義。
//
// 【根拠】このファイルの全フィールドは、実際に稼働しているバックエンド
// （http://192.168.41.4:8000、`タスみる API 1.0.0`）の /openapi.json を
// 2026-08-31にこのセッションから直接取得し、実物のスキーマと突き合わせて
// 定義した。新しいフィールドの追加・改名は一切行っていない。

export type JobStatus = "queued" | "running" | "completed" | "failed" | "cancelled";

export interface ErrorDetail {
  code: string;
  message: string;
}

export interface GenerateRequest {
  // 指定した場合、生成前にプロジェクトの仕様書本文を更新する。
  // これにより「仕様書アップロード」と「生成開始」を1回のAPI呼び出しで
  // 行える（プロジェクト作成時にdocument_textを渡していない場合に使う）。
  document_text?: string | null;
  // Phase 7 Step 3（LLMによる補足説明）。既定オフ。
  use_assignment_llm_reasoning?: boolean;
  // Phase 8 CHECK 2の重複候補のLLM検証。既定オフ。
  use_duplicate_llm_verification?: boolean;
}

export interface GenerateResponse {
  job_id: string;
  status: "queued";
}

export interface JobStatusResponse {
  job_id: string;
  project_id: string;
  team_id: string;
  status: JobStatus;
  progress: number; // 0-100
  current_step: string | null;
  message: string | null;
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
  error: ErrorDetail | null;
}
