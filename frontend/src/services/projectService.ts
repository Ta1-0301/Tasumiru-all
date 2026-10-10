// src/services/projectService.ts
//
// プロジェクト管理・メンバー管理・非同期生成ジョブ・パイプライン結果取得の
// 単一の窓口。
//
// 【Phase 10.5】このファイルはこれまでサンプルフィクスチャ
// （src/mock/sampleProjectResult.ts）を返すだけだったが、実際のバックエンド
// （POST /api/projects, PUT/GET /api/projects/{id}/members,
//  POST /api/projects/{id}/generate, GET /api/jobs/{job_id}*）に接続した。
// 他の全パイプラインサービス（requirementService, taskService,
// dependencyService, memberService, assignmentService, validationService）は
// 引き続きこのファイルの getProjectResult() を経由するだけでよく、無改修で
// 動く（この設計は元々そのために作られていた — 唯一の差し替えポイント）。
//
// 【根拠】ここで呼び出すエンドポイント・リクエスト/レスポンス形は、実際に
// 稼働しているバックエンド（http://192.168.41.4:8000、`タスみる API 1.0.0`）
// の /openapi.json を2026-08-31にこのセッションから直接取得し、さらに
// 実際にHTTPで一連の流れ（チーム作成→プロジェクト作成→メンバー登録→
// 生成ジョブ開始→ポーリング→結果取得）を実行して確認したもの。
// 新しいフィールド・エンドポイントは一切考案していない。
//
// 【アクティブなプロジェクト/ジョブの永続化について】
// バックエンドには「プロジェクトの最新ジョブ一覧」を返すエンドポイントが
// 存在しない（job_id は POST .../generate のレスポンスでしか得られない）。
// ブラウザをリフレッシュしても同じ結果を再表示できるよう、アクティブな
// プロジェクトID・直近のジョブIDだけを localStorage に保存する。
// DB（SQLite）自体が真実の情報源であり、ここに保存するのはそれを再度
// 開くための最小限のポインタに過ぎない（Step 6/18の方針）。
import { apiClient } from "../api/client";
import type { ApiError } from "../types/auth";
import type {
  MemberDirectoryResponse,
  ProjectCreateRequest,
  ProjectResponse,
  SetMembersRequest,
} from "../types/project";
import type { ErrorDetail, GenerateRequest, GenerateResponse, JobStatusResponse } from "../types/job";
import type { FinalProjectOutput, PipelineMember } from "../types/pipeline";
import { SAMPLE_PROJECT_RESULT } from "../mock/sampleProjectResult";

// 本番アプリケーションはもうサンプルデータをデフォルトのデータソースとして
// 使わない。画面側の「サンプルデータ表示中」バナーの表示可否だけに使われる
// 定数で、実データ取得の可否とは独立している（常にfalse = 本番は常に実データ）。
export const IS_SAMPLE_DATA = false;

// フロントエンド単体でのオフライン確認・テスト専用。本番の getProjectResult()
// からは一切呼ばれない（Step 2/21: モックは残すが本番経路では使わない）。
export async function getSampleProjectResult(): Promise<FinalProjectOutput> {
  return JSON.parse(JSON.stringify(SAMPLE_PROJECT_RESULT)) as FinalProjectOutput;
}

const ACTIVE_PROJECT_KEY = "tasumiru.activeProjectId";
const ACTIVE_JOB_KEY = "tasumiru.activeJobId";

function readLocalStorage(key: string): string | null {
  try {
    return localStorage.getItem(key);
  } catch {
    return null; // プライベートブラウジング等でlocalStorageが使えない場合
  }
}

function writeLocalStorage(key: string, value: string | null): void {
  try {
    if (value) localStorage.setItem(key, value);
    else localStorage.removeItem(key);
  } catch {
    /* 保存できなくても致命的ではない（DBが真実の情報源のため） */
  }
}

export function getActiveProjectId(): string | null {
  return readLocalStorage(ACTIVE_PROJECT_KEY);
}

export function setActiveProjectId(id: string | null): void {
  writeLocalStorage(ACTIVE_PROJECT_KEY, id);
}

export function getActiveJobId(): string | null {
  return readLocalStorage(ACTIVE_JOB_KEY);
}

export function setActiveJobId(id: string | null): void {
  writeLocalStorage(ACTIVE_JOB_KEY, id);
}

// ── 既知のプロジェクト一覧（このブラウザのローカル履歴）──
//
// バックエンドには「チームの全プロジェクト一覧」を返すエンドポイントが
// 存在しない（/openapi.json 実物で確認済み: POST /api/projects と
// GET /api/projects/{project_id} のみで、一覧系は無い）。そのため、
// メンバー管理画面の「プロジェクトで絞り込む」機能は、このブラウザが
// これまでに作成/参照したプロジェクトのローカルな記録に頼る他ない。
// 他のブラウザ/デバイスで作成されたプロジェクトはここには現れない
// （バックエンドAPIの制約であり、フロント側の実装では解決できない）。
export interface KnownProject {
  id: string;
  name: string | null;
}

const PROJECT_REGISTRY_KEY = "tasumiru.projectRegistry";
const PROJECT_REGISTRY_MAX = 20;

export function listKnownProjects(): KnownProject[] {
  const raw = readLocalStorage(PROJECT_REGISTRY_KEY);
  if (!raw) return [];
  try {
    const parsed: unknown = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    return parsed.filter(
      (p): p is KnownProject => !!p && typeof p === "object" && typeof (p as KnownProject).id === "string",
    );
  } catch {
    return [];
  }
}

// createProject()/getProject() の成功時に呼ぶ。同じIDが既にあれば
// 先頭に移動して名前を最新化するだけで、重複エントリは作らない。
function rememberProject(project: { id: string; name: string | null }): void {
  const deduped = listKnownProjects().filter((p) => p.id !== project.id);
  const next = [{ id: project.id, name: project.name }, ...deduped].slice(0, PROJECT_REGISTRY_MAX);
  writeLocalStorage(PROJECT_REGISTRY_KEY, JSON.stringify(next));
}

// ── プロジェクト ──

export async function createProject(body: ProjectCreateRequest = {}): Promise<ProjectResponse> {
  const { data } = await apiClient.post<ProjectResponse>("/api/projects", body);
  setActiveProjectId(data.id);
  rememberProject(data);
  return data;
}

export async function getProject(projectId: string): Promise<ProjectResponse> {
  const { data } = await apiClient.get<ProjectResponse>(`/api/projects/${projectId}`);
  rememberProject(data);
  return data;
}

// アクティブなプロジェクトが無ければ新規作成し、あれば（実在確認のうえ）
// そのまま使う。偽のプロジェクトIDを生成することはない — 必ず実際に
// バックエンドが払い出したIDだけを使う（Step 6）。
export async function ensureActiveProject(): Promise<ProjectResponse> {
  const existingId = getActiveProjectId();
  if (existingId) {
    try {
      return await getProject(existingId);
    } catch {
      // 保存されていたIDがもう存在しない（別環境のDBを指している等）。
      // 破棄して新規作成にフォールバックする。
      setActiveProjectId(null);
    }
  }
  return createProject({});
}

// ── メンバー ──

export async function setProjectMembers(
  projectId: string,
  members: PipelineMember[],
): Promise<MemberDirectoryResponse> {
  const body: SetMembersRequest = { members };
  const { data } = await apiClient.put<MemberDirectoryResponse>(`/api/projects/${projectId}/members`, body);
  return data;
}

export async function fetchProjectMembers(projectId: string): Promise<MemberDirectoryResponse> {
  const { data } = await apiClient.get<MemberDirectoryResponse>(`/api/projects/${projectId}/members`);
  return data;
}

// ── 生成ジョブ ──

/** POST /api/documents/parse のレスポンス（backend/services/parser.py の ParsedDocument） */
export interface ParsedDocument {
  filename: string;
  text: string;
  char_count: number;
  page_count: number | null;
  truncated: boolean;
}

/** PDF / Word(.docx) をバックエンドで本文テキストに変換する（DBには保存されない）。 */
export async function parseDocument(file: File): Promise<ParsedDocument> {
  const form = new FormData();
  form.append("file", file);
  const { data } = await apiClient.post<ParsedDocument>("/api/documents/parse", form);
  return data;
}

export async function startGeneration(
  projectId: string,
  body: GenerateRequest = {},
): Promise<GenerateResponse> {
  const { data } = await apiClient.post<GenerateResponse>(`/api/projects/${projectId}/generate`, body);
  setActiveJobId(data.job_id);
  invalidateProjectResultCache();
  return data;
}

export async function getJobStatus(jobId: string): Promise<JobStatusResponse> {
  const { data } = await apiClient.get<JobStatusResponse>(`/api/jobs/${jobId}`);
  return data;
}

export async function getJobError(jobId: string): Promise<ErrorDetail | null> {
  try {
    const { data } = await apiClient.get<ErrorDetail>(`/api/jobs/${jobId}/error`);
    return data;
  } catch (err) {
    // バックエンドは「失敗していないジョブ」に対して 404 NO_ERROR を返す
    // （実機で確認済み）。これはエラーではなく「エラーが無い」という
    // 正常な状態なので null を返す。
    const apiErr = err as ApiError | undefined;
    if (apiErr?.code === "NO_ERROR") return null;
    throw err;
  }
}

// ── 更新（前回の分析結果を再利用して、メンバー変更・仕様変更を反映する）──

/** POST /api/projects/{id}/update のリクエスト（backend/models/job_schemas.py UpdateRequest） */
export interface UpdateRequestBody {
  source_job_id: string;
  mode: "members" | "spec";
  document_text?: string | null;
  reassign_scope?: "unassigned" | "all" | "selected";
  task_ids?: string[];
  /** 画面で手動変更した担当者（タスクID → メンバーID、未割当にした場合は null） */
  current_assignments?: Record<string, string | null>;
}

export interface UpdateItemRef {
  id: string;
  title: string;
}

/** GET /api/jobs/{id}/update-summary（backend/jobs/updates.py UpdateSummary） */
export interface UpdateSummary {
  mode: "members" | "spec";
  source_job_id: string;
  reassign_scope: "unassigned" | "all" | "selected";
  requirements_unchanged: number;
  requirements_changed: UpdateItemRef[];
  requirements_added: UpdateItemRef[];
  requirements_removed: UpdateItemRef[];
  tasks_unchanged: number;
  tasks_updated: UpdateItemRef[];
  tasks_added: UpdateItemRef[];
  tasks_removal_candidates: UpdateItemRef[];
  assignments_kept: number;
  assignments_changed: { task_id: string; before: string | null; after: string | null }[];
  unassigned_after: string[];
  llm_requirement_calls: number;
  llm_task_calls: number;
  notes: string[];
}

export async function startUpdate(projectId: string, body: UpdateRequestBody): Promise<GenerateResponse> {
  const { data } = await apiClient.post<GenerateResponse>(`/api/projects/${projectId}/update`, body);
  setActiveJobId(data.job_id);
  invalidateProjectResultCache();
  return data;
}

/** 更新ジョブでなければ（404 NOT_AN_UPDATE）null を返す */
export async function getUpdateSummary(jobId: string): Promise<UpdateSummary | null> {
  try {
    const { data } = await apiClient.get<UpdateSummary>(`/api/jobs/${jobId}/update-summary`);
    return data;
  } catch (err) {
    const apiErr = err as ApiError | undefined;
    if (apiErr?.code === "NOT_AN_UPDATE") return null;
    throw err;
  }
}

// ── パイプライン結果（Requirements〜Final JSON）──

// 直近取得したジョブ結果のメモリキャッシュ。1画面内で複数のサービス
// （taskService, dependencyService, assignmentService...）がそれぞれ
// getProjectResult() を呼んでも、同じジョブに対して毎回HTTPリクエストを
// 発生させないようにする。ジョブIDが変わる（=新しい生成が始まる）と
// 自動的に無効化される。
let cachedJobId: string | null = null;
let cachedResult: FinalProjectOutput | null = null;

export async function getProjectResult(): Promise<FinalProjectOutput> {
  const jobId = getActiveJobId();
  if (!jobId) {
    return Promise.reject({
      code: "NO_ACTIVE_JOB",
      message: "まだタスク生成が実行されていません。「タスク生成」画面からAIタスク生成を開始してください。",
    } as ApiError);
  }

  if (cachedJobId === jobId && cachedResult) {
    return cachedResult;
  }

  const { data } = await apiClient.get<FinalProjectOutput>(`/api/jobs/${jobId}/result`);
  cachedJobId = jobId;
  cachedResult = data;
  return data;
}

// 同じジョブの最新結果を強制的に再取得したい場合に使う（キャッシュを無視する）。
export function invalidateProjectResultCache(): void {
  cachedJobId = null;
  cachedResult = null;
}
