// src/services/taskService.ts
//
// パイプラインタスク（Phase 4, TASK-xxx形式）の取得。
// backend/routers/tasks.py の T-xxx形式タスクとは別物（API_CONTRACT.md §5参照）。
import type { PipelineTask } from "../types/pipeline";
import { getProjectResult } from "./projectService";

export async function getPipelineTasks(): Promise<PipelineTask[]> {
  const project = await getProjectResult();
  return project.tasks;
}

export async function getPipelineTaskById(
  taskId: string,
): Promise<PipelineTask | undefined> {
  const tasks = await getPipelineTasks();
  return tasks.find((t) => t.id === taskId);
}
