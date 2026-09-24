// src/services/memberService.ts
//
// 構造化メンバー（Members, Phase 6: スキルレベル/稼働可能時間モデル）の取得。
// §3の認証チームメンバー、legacy MemberSchema とは別の第三の「メンバー」概念。
import type { PipelineMember } from "../types/pipeline";
import { fetchProjectMembers, getProjectResult } from "./projectService";

// 直近の生成ジョブ結果に埋め込まれたメンバースナップショット（生成実行時点の
// 状態）。既存のアサイン推奨/依存関係/カンバン画面など、ジョブ結果全体と
// 突き合わせる必要がある画面はこちらを使い続ける。
export async function getPipelineMembers(): Promise<PipelineMember[]> {
  const project = await getProjectResult();
  return project.members;
}

// 指定したプロジェクトの「現在の」メンバーディレクトリ（GET /api/projects/{id}/members）。
// ジョブのスナップショットではなく、PUT /api/projects/{id}/members で
// 直接設定されている最新のメンバー一覧を返す。メンバー管理画面の
// プロジェクト絞り込みに使う。
export async function getMembersForProject(projectId: string): Promise<PipelineMember[]> {
  const directory = await fetchProjectMembers(projectId);
  return directory.members;
}

// remaining_capacity は Python側の @property でありシリアライズされない
// （API_CONTRACT.md §11.6）。フロント側で計算する共通ヘルパーをここに置く。
export function remainingCapacity(member: PipelineMember): number {
  return (
    member.availability.available_hours_per_week -
    member.availability.current_assigned_hours
  );
}
