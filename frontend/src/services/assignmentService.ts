// src/services/assignmentService.ts
//
// アサイン推奨/確定結果（Assignments, Phase 7）の取得。
import type { FinalAssignment } from "../types/pipeline";
import { getProjectResult } from "./projectService";

export async function getAssignments(): Promise<FinalAssignment[]> {
  const project = await getProjectResult();
  return project.assignments;
}

export async function getAssignmentForTask(
  taskId: string,
): Promise<FinalAssignment | undefined> {
  const assignments = await getAssignments();
  return assignments.find((a) => a.task_id === taskId);
}
