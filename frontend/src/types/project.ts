// src/types/project.ts
//
// プロジェクト管理（POST /api/projects, GET /api/projects/{id},
// PUT/GET /api/projects/{id}/members）に対応する型定義。
//
// 【根拠】/openapi.json 実物（2026-08-31取得）に基づく。
// §3認証の Team/TeamMemberInfo、パイプライン結果内の ProjectMeta
// （FinalProjectOutput.project）、legacyの簡易Member（app.tsのMember型）
// とは別の、第4の「プロジェクト」概念であることに注意。
import type { PipelineMember, MemberIssue } from "./pipeline";

export interface ProjectCreateRequest {
  // プロジェクト名（表示用、任意）
  name?: string | null;
  // 仕様書本文（後から /generate 呼び出し時に渡すことも可能）
  document_text?: string | null;
}

export interface ProjectResponse {
  id: string;
  team_id: string;
  name: string | null;
  has_document: boolean;
  has_members: boolean;
  created_at: string;
  updated_at: string;
}

// PUT /api/projects/{id}/members のリクエストボディ。
// バックエンドは「Phase 6のMemberスキーマに沿った生レコードの配列」を
// そのまま受け取る（additionalProperties: true）。フロント側で値を
// 作り出さず、Phase 6の Member 型（types/pipeline.ts の PipelineMember）に
// 準拠したオブジェクトをそのまま渡す。
export interface SetMembersRequest {
  members: PipelineMember[];
}

// PUT/GET /api/projects/{id}/members の共通レスポンス形。
// types/pipeline.ts の MemberDirectory と同一だが、project.ts 側からも
// 参照できるようここに型エイリアスを置く。
export interface MemberDirectoryResponse {
  team_id: string | null;
  members: PipelineMember[];
  issues: MemberIssue[];
  updated_at: string | null;
}
