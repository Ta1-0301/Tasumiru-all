// src/services/validationService.ts
//
// 検証結果（Validation, Phase 8）の取得。
import type { ValidationSummary } from "../types/pipeline";
import { getProjectResult } from "./projectService";

export async function getValidationSummary(): Promise<ValidationSummary> {
  const project = await getProjectResult();
  return project.validation;
}
