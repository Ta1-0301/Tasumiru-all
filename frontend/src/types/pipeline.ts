// src/types/pipeline.ts
//
// Phase 10: 型定義 — Requirements → Tasks → Dependencies → Members →
// Assignments → Validation → Final JSON パイプラインの型。
//
// フィールドは全て docs/openapi.json 実物 + バックエンド担当者から共有された
// API_CONTRACT.md §11（Pydanticモデルそのまま）を根拠にしており、
// このフロントエンド側で新しいフィールドを追加/改名したものは一つもない。
// これらのパイプライン（Phase 3〜9）は現時点でHTTPエンドポイントとして
// 公開されていない（CLIスクリプトのみ）ため、実データは
// src/mock/sampleProjectResult.ts のサンプルフィクスチャ経由で得ている。
// 実エンドポイントが追加された際は、この型定義はそのまま使い回せる想定。

export type PriorityLevel = "high" | "medium" | "low" | "unknown";

export interface SourceReference {
  document_id: string;
  page: number | null;
  section: string | null;
  paragraph: string | null;
  source_text: string | null;
}

// ── §11.3 Requirement / RequirementDocument (Phase 3) ──
export type RequirementType =
  | "system_purpose"
  | "target_user"
  | "functional"
  | "non_functional"
  | "constraint"
  | "assumption"
  | "deliverable"
  | "technical"
  | "business_rule";

export interface Requirement {
  id: string; // ^REQ-\d{3,}$
  type: RequirementType;
  title: string;
  description: string;
  priority: PriorityLevel;
  origin: "explicit" | "inferred";
  source_reference: SourceReference | null;
  confidence: number; // 0.0-1.0
}

export interface RequirementIssue {
  code: string;
  message: string;
  requirement_ids: string[];
}

export interface RequirementDocument {
  document_id: string;
  requirements: Requirement[];
  issues: RequirementIssue[];
  model: string | null;
  model_version: string | null;
  generated_at: string | null;
}

// ── §11.4 Task / TaskDocument (Phase 4) ──
// 注意: これは backend/routers/tasks.py の TaskSchema（T-001形式）とは
// 別物・非互換（こちらは TASK-001形式）。パイプライン側の型として
// PipelineTask と命名している。
export interface PipelineTask {
  id: string; // ^TASK-\d{3,}$
  requirement_ids: string[];
  title: string;
  description: string;
  priority: PriorityLevel;
  estimated_hours: number | null;
  required_skills: string[];
  acceptance_criteria: string[];
  source_reference: SourceReference | null;
  confidence: number;
  needs_review: boolean;
  review_reasons: string[];
  // タスク個別の期限（任意、YYYY-MM-DD）。LLMのタスク生成は設定しない。
  due_date?: string | null;
}

export interface TaskIssue {
  code: string;
  message: string;
  task_ids: string[];
}

export interface TaskDocument {
  document_id: string;
  tasks: PipelineTask[];
  issues: TaskIssue[];
  model: string | null;
  generated_at: string | null;
}

// ── §11.5 Dependency / DependencyDocument (Phase 5) ──
export type DependencyType = "required" | "recommended" | "optional";

export interface Dependency {
  from_task_id: string; // 完了が先に必要なタスク
  to_task_id: string; // from_task_id完了後でないと着手できないタスク
  type: DependencyType;
  reason: string;
  confidence: number;
}

export interface DependencyIssueEdge {
  from_task_id: string;
  to_task_id: string;
}

export interface DependencyIssue {
  code: string;
  message: string;
  edges: DependencyIssueEdge[];
}

export interface DependencyGraph {
  nodes: string[];
  edges: Record<string, unknown>[];
  levels: Record<string, unknown>;
  required_cycle: string[] | null;
}

export interface DependencyDocument {
  document_id: string;
  dependencies: Dependency[];
  issues: DependencyIssue[];
  graph: DependencyGraph;
  model: string | null;
  generated_at: string | null;
}

// ── §11.6 Member / MemberDirectory (Phase 6) ──
// 注意: これは §3 認証の TeamMemberInfo とも、legacy MemberSchema
// （name/skills文字列配列/load_pct）とも別物・第三の「メンバー」概念。
export interface MemberSkillEntry {
  skill: string;
  level: number; // 1-5
  experience_years: number | null;
}

export interface MemberAvailability {
  available_hours_per_week: number;
  working_days: string[];
  current_assigned_hours: number;
  // remaining_capacity は Python 側の @property であり、シリアライズされた
  // JSONには含まれない（API_CONTRACT.md §11.6 の注記の通り）。
  // フロント側で available_hours_per_week - current_assigned_hours として
  // 都度計算する（新しいフィールドを勝手に追加しているわけではない）。
}

export type MemberConstraintType =
  | "scope_restriction"
  | "day_unavailable"
  | "max_hours_per_week"
  | "requires_review";

export interface MemberConstraint {
  type: MemberConstraintType;
  value: string | null;
  max_hours: number | null;
}

export interface PipelineMember {
  id: string;
  name: string;
  skills: MemberSkillEntry[];
  experience_years: number | null;
  availability: MemberAvailability;
  constraints: MemberConstraint[];
}

export interface MemberIssue {
  code: string;
  message: string;
  member_id: string | null;
}

export interface MemberDirectory {
  team_id: string | null;
  members: PipelineMember[];
  issues: MemberIssue[];
  updated_at: string | null;
}

// ── §11.7 AssignmentResult / FinalAssignment (Phase 7) ──
export interface CandidateScore {
  member_id: string;
  skill_match: number;
  workload_score: number;
  experience_score: number;
  availability_score: number;
  score: number;
}

export interface RejectedCandidate {
  member_id: string;
  reasons: string[];
}

export type AssignmentStatus = "recommended" | "no_suitable_member";

export interface AssignmentResult {
  task_id: string;
  recommended_member_id: string | null;
  score: number | null;
  candidate_scores: CandidateScore[];
  rejected_candidates: RejectedCandidate[];
  reasons: string[];
  warnings: string[];
  status: AssignmentStatus;
}

export interface FinalAssignment {
  task_id: string;
  assigned_member_id: string | null;
  decided_by: "ai" | "human";
  overridden: boolean;
  override_reason: string | null;
  ai_recommendation: AssignmentResult;
}

// ── §11.8 ValidationReport (Phase 8) ──
export interface MissingRequirement {
  requirement_id: string;
  message: string;
}

export interface DuplicateTask {
  task_ids: string[];
  similarity: number;
  method: "rule" | "llm" | "hybrid";
  reason: string;
}

export interface DependencyError {
  code: string;
  message: string;
  task_ids: string[];
}

export interface WorkloadWarning {
  member_id: string;
  assigned_hours: number;
  available_hours: number;
  remaining_capacity: number;
  workload_percentage: number;
  code: string;
  message: string;
}

export interface SkillMismatch {
  task_id: string;
  member_id: string;
  skill: string;
  required_level: number;
  member_level: number;
  message: string;
}

export interface ConstraintViolation {
  task_id: string;
  member_id: string;
  code: string;
  message: string;
}

export interface WorkloadSummary {
  member_id: string;
  assigned_hours: number;
  available_hours: number;
  remaining_capacity: number;
  workload_percentage: number;
  // 納期考慮で追加。"period" のとき available_hours は period_start〜period_end の
  // 稼働可能時間（"weekly" または未設定なら従来通り週あたり稼働可能時間）。
  basis?: "weekly" | "period";
  weekly_available_hours?: number | null;
  period_start?: string | null;
  period_end?: string | null;
}

export interface ValidationReport {
  valid: boolean;
  missing_requirements: MissingRequirement[];
  duplicate_tasks: DuplicateTask[];
  dependency_errors: DependencyError[];
  workload_warnings: WorkloadWarning[];
  skill_mismatches: SkillMismatch[];
  constraint_violations: ConstraintViolation[];
  workload_summaries: WorkloadSummary[];
  /** CHECK 7〜9（古いバックエンドの結果には無いため任意） */
  task_quality_issues?: { task_id: string; code: string; message: string }[];
  assignment_score_anomalies?: { task_id: string; member_id: string; score: number; threshold: number; message: string }[];
  unassigned_tasks?: { task_id: string; reason: string; message: string }[];
  generated_at: string | null;
}

// ── §11.9 FinalProjectOutput (Phase 9) ──
export type ValidationStatus = "valid" | "warning" | "error";

export interface TraceabilityError {
  code: string;
  message: string;
  task_id: string | null;
}

export interface ValidationSummary {
  status: ValidationStatus;
  critical_issue_count: number;
  warning_issue_count: number;
  traceability_errors: TraceabilityError[];
  report: ValidationReport;
}

export interface ProjectMeta {
  document_id: string;
  name: string | null;
  exported_at: string | null;
  // 納期考慮（任意、YYYY-MM-DD）
  start_date?: string | null;
  due_date?: string | null;
  planning_reference_date?: string | null;
}

// 【2026-08-31修正】実際の /openapi.json では prompt_versions は固定4キーの
// オブジェクトではなく additionalProperties: {type: string} の自由な辞書
// として定義されている（models_by_phase と同じ形）。フェーズが増減しても
// 壊れないよう、固定キーの PromptVersions ではなく Record<string, string> にする。
export interface PipelineMetadata {
  generated_at: string;
  pipeline_version: string;
  model: string | null;
  model_version: string | null;
  prompt_versions: Record<string, string>;
  document_id: string | null;
  models_by_phase: Record<string, string>;
}

export interface FinalProjectOutput {
  project: ProjectMeta;
  requirements: Requirement[];
  tasks: PipelineTask[];
  dependencies: Dependency[];
  members: PipelineMember[];
  assignments: FinalAssignment[];
  validation: ValidationSummary;
  metadata: PipelineMetadata;
}
