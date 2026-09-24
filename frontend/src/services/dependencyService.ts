// src/services/dependencyService.ts
//
// 依存関係（Dependencies, Phase 5）データの取得。
import type { Dependency, DependencyIssue } from "../types/pipeline";
import { apiClient } from "../api/client";
import { getActiveJobId, getProjectResult } from "./projectService";

export async function getDependencies(): Promise<Dependency[]> {
  const project = await getProjectResult();
  return project.dependencies;
}

// 【Phase 10.5】DependencyDocument.issues（循環検出など）は
// FinalProjectOutput 単体には含まれていないが、専用エンドポイント
// GET /api/jobs/{job_id}/dependencies から取得できる。
// なお既存の依存関係エラーは validation.report.dependency_errors 側でも
// 表現されている（そちらは validationService を参照）。
export async function getDependencyIssues(): Promise<DependencyIssue[]> {
  const jobId = getActiveJobId();
  if (!jobId) return [];
  const { data } = await apiClient.get<{ issues: DependencyIssue[] }>(
    `/api/jobs/${jobId}/dependencies`,
  );
  return data.issues;
}
