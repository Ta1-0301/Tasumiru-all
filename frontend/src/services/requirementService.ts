// src/services/requirementService.ts
//
// 要件（Requirements, Phase 3）データの取得。コンポーネントはこの層のみを
// 経由し、フィクスチャ/将来のAPIの区別を意識しない。
import type { Requirement, RequirementIssue } from "../types/pipeline";
import { apiClient } from "../api/client";
import { getActiveJobId, getProjectResult } from "./projectService";

export async function getRequirements(): Promise<Requirement[]> {
  const project = await getProjectResult();
  return project.requirements;
}

// 【Phase 10.5】バックエンドの RequirementDocument.issues は
// FinalProjectOutput には含まれていない（§11.9参照）が、専用エンドポイント
// GET /api/jobs/{job_id}/requirements（RequirementDocument）には含まれている
// ため、そちらから取得する。アクティブなジョブが無ければ空配列を返す
// （getProjectResult()のように例外にはしない — issuesは補助情報のため）。
export async function getRequirementIssues(): Promise<RequirementIssue[]> {
  const jobId = getActiveJobId();
  if (!jobId) return [];
  const { data } = await apiClient.get<{ issues: RequirementIssue[] }>(
    `/api/jobs/${jobId}/requirements`,
  );
  return data.issues;
}
