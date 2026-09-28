// src/specToTasks/model.ts
//
// Spec to Tasks 画面の表示用モデル。
// バックエンドの GET /api/jobs/{job_id}/result（FinalProjectOutput）と、
// ユーザーが入力した仕様書本文から、画面が扱いやすい形に変換する。
//
// 【方針】バックエンドのデータ・計算方法はそのまま使い、値を捏造しない。
//   - 負荷は backend/pipeline/validation/workload.py と同じく
//     「割当タスクの見積り合計 / available_hours_per_week」に、
//     Phase 6 の current_assigned_hours（既存業務）を加えて表示する。
//     バックエンドが納期を考慮して計画期間ベースで負荷を計算した場合
//     （workload_summaries[].basis === "period"）は、上限をその期間の稼働可能時間に、
//     既存業務（週あたり）も同じ期間分に換算して表示する。
//   - スキル不足は backend/pipeline/validation/skill_mismatch.py と同じく
//     「必要スキルを保有していない（要求レベル1未満）」で判定する
//     （Task.required_skills は要求レベルを持たないため）。
//   - 画面上で担当者を変更した場合の再計算だけをフロント側で行う。
//     バックエンドには割当の上書きを保存するAPIが無いため、変更は
//     このブラウザ内（localStorage）にのみ保存される。
import type {
  AssignmentResult,
  FinalProjectOutput,
  PipelineMember,
  PipelineTask,
  Requirement,
  RequirementType,
  ValidationSummary,
} from "../types/pipeline";

export const WARN = "oklch(0.55 0.180 25)";
export const WARN_BG = "oklch(0.95 0.042 25)";
export const WARN_FG = "oklch(0.45 0.156 25)";
/** 信頼度がこの値（%）未満の要件・タスクは「要確認」として扱う */
export const LOW_CONF = 80;

/** taskId -> memberId */
export type Assignment = Record<string, string | undefined>;

export interface VMember {
  id: string;
  name: string;
  ini: string;
  /** 上位スキルから作る表示用の肩書き */
  role: string;
  /** 稼働上限。週あたり稼働可能時間、または納期考慮時は計画期間内の稼働可能時間 */
  cap: number;
  /** 既存業務の時間（current_assigned_hours。納期考慮時は計画期間分に換算） */
  base: number;
  /** 正規化スキル名 -> レベル(1-5) */
  sk: Record<string, number>;
  /** 正規化スキル名 -> 表示名 */
  skName: Record<string, string>;
  raw: PipelineMember;
}

export interface VRequirement {
  id: string;
  title: string;
  detail: string;
  cat: string;
  pri: string;
  conf: number;
  sec: string;
  page: number | null;
  srcText: string;
  inferred: boolean;
}

export interface VTask {
  id: string;
  title: string;
  desc: string;
  req: string | null;
  reqIds: string[];
  /** 必要スキル（表示名。'unknown' は除外済み） */
  skills: string[];
  h: number;
  hKnown: boolean;
  deps: string[];
  pri: string;
  conf: number;
  needsReview: boolean;
  reviewReasons: string[];
  acceptance: string[];
  srcText: string;
  sec: string;
  page: number | null;
}

export interface DocPara {
  id: string;
  t: string;
  heading: boolean;
  reqs: string[];
}

export interface Model {
  name: string;
  documentId: string;
  reqs: VRequirement[];
  tasks: VTask[];
  members: VMember[];
  REQ: Record<string, VRequirement>;
  TK: Record<string, VTask>;
  MEM: Record<string, VMember>;
  /** AIの割当（FinalAssignment.assigned_member_id） */
  aiAssign: Assignment;
  rec: Record<string, AssignmentResult>;
  doc: DocPara[];
  /** 本文が無い場合 true（原文ビューは要件の引用文から組み立てる） */
  docFromQuotes: boolean;
  /** スキル表の列（正規化スキル名） */
  skillCols: string[];
  skillLabel: Record<string, string>;
  validation: ValidationSummary;
  dependencyCount: number;
  generatedAt: string | null;
  /** 納期考慮時の計画期間（負荷の上限の基準）。週ベースなら null */
  period: { start: string; end: string } | null;
}

export const norm = (s: string): string => s.trim().toLowerCase().replace(/\s+/g, " ");
const isUnknownSkill = (s: string) => !s || norm(s) === "unknown";

const CAT_LABEL: Record<RequirementType, string> = {
  functional: "機能",
  non_functional: "非機能",
  constraint: "制約",
  system_purpose: "目的",
  target_user: "対象ユーザー",
  assumption: "前提",
  deliverable: "成果物",
  technical: "技術",
  business_rule: "業務ルール",
};
const PRI_LABEL: Record<string, string> = { high: "高", medium: "中", low: "低", unknown: "—" };

export const CAT_NOTE: Record<string, string> = {
  機能: "ユーザー・管理者の操作",
  非機能: "品質・性能・セキュリティ",
  制約: "期限・条件",
  目的: "システムの目的",
  対象ユーザー: "利用者像",
  前提: "前提条件",
  成果物: "納品物",
  技術: "技術的な指定",
  業務ルール: "業務上の決まり",
};

function secText(section: string | null | undefined, paragraph: string | null | undefined): string {
  if (section) return section;
  if (paragraph && !/^chunk_/i.test(paragraph)) return paragraph;
  return "";
}

function initialOf(name: string): string {
  const t = name.trim();
  return t ? Array.from(t)[0] : "?";
}

function toMember(m: PipelineMember): VMember {
  const sk: Record<string, number> = {};
  const skName: Record<string, string> = {};
  (m.skills || []).forEach((s) => {
    if (!s.skill) return;
    const k = norm(s.skill);
    sk[k] = Math.max(sk[k] || 0, s.level || 0);
    skName[k] = s.skill;
  });
  const top = Object.keys(sk).sort((a, b) => sk[b] - sk[a]).slice(0, 2).map((k) => skName[k]);
  return {
    id: m.id,
    name: m.name,
    ini: initialOf(m.name),
    role: top.length ? top.join(" / ") : "スキル未登録",
    cap: m.availability?.available_hours_per_week ?? 0,
    base: m.availability?.current_assigned_hours ?? 0,
    sk,
    skName,
    raw: m,
  };
}

function toReq(r: Requirement): VRequirement {
  const src = r.source_reference;
  return {
    id: r.id,
    title: r.title,
    detail: r.description,
    cat: CAT_LABEL[r.type] ?? r.type,
    pri: PRI_LABEL[r.priority] ?? r.priority,
    conf: Math.round((r.confidence ?? 0) * 100),
    sec: secText(src?.section, src?.paragraph),
    page: src?.page ?? null,
    srcText: src?.source_text ?? "",
    inferred: r.origin === "inferred",
  };
}

function toTask(t: PipelineTask, deps: string[]): VTask {
  const src = t.source_reference;
  return {
    id: t.id,
    title: t.title,
    desc: t.description,
    req: t.requirement_ids?.[0] ?? null,
    reqIds: t.requirement_ids ?? [],
    skills: (t.required_skills ?? []).filter((s) => !isUnknownSkill(s)),
    h: t.estimated_hours ?? 0,
    hKnown: t.estimated_hours != null,
    deps,
    pri: PRI_LABEL[t.priority] ?? t.priority,
    conf: Math.round((t.confidence ?? 0) * 100),
    needsReview: !!t.needs_review,
    reviewReasons: t.review_reasons ?? [],
    acceptance: t.acceptance_criteria ?? [],
    srcText: src?.source_text ?? "",
    sec: secText(src?.section, src?.paragraph),
    page: src?.page ?? null,
  };
}

const squash = (s: string) => s.replace(/\s+/g, "");

/** 仕様書本文を段落に分け、要件の引用文（source_text）が含まれる段落に要件IDを紐づける */
function buildDoc(text: string, reqs: VRequirement[]): { doc: DocPara[]; fromQuotes: boolean } {
  const body = text.replace(/\r\n?/g, "\n").trim();
  if (!body) {
    // 本文が手元に無い（別のブラウザで生成した等）場合は、要件の引用文だけで組み立てる
    const seen = new Map<string, DocPara>();
    reqs.forEach((r) => {
      const t = r.srcText.trim();
      if (!t) return;
      const p = seen.get(t);
      if (p) p.reqs.push(r.id);
      else seen.set(t, { id: `Q${seen.size + 1}`, t, heading: false, reqs: [r.id] });
    });
    return { doc: [...seen.values()], fromQuotes: true };
  }

  const isHeading = (t: string) => /^#{1,6}\s/.test(t) || (t.length <= 40 && !/[。．.、,]$/.test(t) && !t.includes("。"));
  let blocks = body.split(/\n\s*\n/).map((b) => b.trim()).filter(Boolean);
  // 空行がほとんど無い文書は行単位で分ける
  if (blocks.length < 4) blocks = body.split("\n").map((b) => b.trim()).filter(Boolean);
  // 「見出し行 + 本文」がひと塊になっている場合は見出しを切り離す
  blocks = blocks.flatMap((b) => {
    const [first, ...rest] = b.split("\n");
    return rest.length && isHeading(first.trim()) ? [first.trim(), rest.join("\n").trim()] : [b];
  });

  const doc: DocPara[] = blocks.map((t, i) => ({ id: `P${i + 1}`, t, heading: isHeading(t), reqs: [] }));
  doc.forEach((p) => { if (p.heading) p.t = p.t.replace(/^#{1,6}\s+/, ""); });

  const flat = doc.map((p) => squash(p.t));
  reqs.forEach((r) => {
    const q = squash(r.srcText);
    if (!q) return;
    let idx = flat.findIndex((p) => p.includes(q));
    // 引用文が「見出し + 本文」など隣り合う段落にまたがっている場合
    if (idx < 0) {
      idx = flat.findIndex((p, i) => i + 1 < flat.length && (p + flat[i + 1]).includes(q));
      if (idx >= 0 && doc[idx].heading) idx += 1;
    }
    // 引用文の方が長く、段落を丸ごと含んでいる場合
    if (idx < 0) idx = flat.findIndex((p, i) => !doc[i].heading && p.length >= 8 && q.includes(p));
    if (idx < 0 && q.length > 16) {
      const head = q.slice(0, 16);
      idx = flat.findIndex((p) => p.includes(head));
    }
    if (idx >= 0) doc[idx].reqs.push(r.id);
  });
  return { doc, fromQuotes: false };
}

export function buildModel(out: FinalProjectOutput, documentText: string): Model {
  const members = (out.members ?? []).map(toMember);
  const reqs = (out.requirements ?? []).map(toReq);

  // 依存関係: from_task_id の完了後に to_task_id に着手できる
  const depMap: Record<string, string[]> = {};
  (out.dependencies ?? []).forEach((d) => {
    (depMap[d.to_task_id] ||= []).includes(d.from_task_id) || depMap[d.to_task_id].push(d.from_task_id);
  });
  const taskIds = new Set((out.tasks ?? []).map((t) => t.id));
  const tasks = (out.tasks ?? []).map((t) => toTask(t, (depMap[t.id] ?? []).filter((id) => taskIds.has(id) && id !== t.id)));

  const aiAssign: Assignment = {};
  const rec: Record<string, AssignmentResult> = {};
  (out.assignments ?? []).forEach((a) => {
    if (a.assigned_member_id) aiAssign[a.task_id] = a.assigned_member_id;
    if (a.ai_recommendation) rec[a.task_id] = a.ai_recommendation;
  });

  // スキル表の列: メンバーの保有スキル（多い順）→ タスクで必要だが誰も持っていないスキル
  const count: Record<string, number> = {};
  const skillLabel: Record<string, string> = {};
  members.forEach((m) => Object.keys(m.sk).forEach((k) => { count[k] = (count[k] || 0) + 1; skillLabel[k] = m.skName[k]; }));
  const skillCols = Object.keys(count).sort((a, b) => count[b] - count[a] || a.localeCompare(b));
  tasks.forEach((t) => t.skills.forEach((s) => { const k = norm(s); skillLabel[k] ||= s; }));

  const { doc, fromQuotes } = buildDoc(documentText, reqs);

  // 納期考慮: バックエンドが計画期間ベースで負荷を計算した場合は、その上限を使う
  let period: Model["period"] = null;
  (out.validation?.report?.workload_summaries ?? []).forEach((s) => {
    const m = members.find((x) => x.id === s.member_id);
    if (!m || s.basis !== "period" || !s.weekly_available_hours || !s.period_start || !s.period_end) return;
    const factor = s.available_hours / s.weekly_available_hours;
    m.cap = s.available_hours;
    m.base = Math.round(m.base * factor * 10) / 10;
    period ||= { start: s.period_start, end: s.period_end };
  });

  return {
    name: out.project?.name || "無題のプロジェクト",
    documentId: out.project?.document_id ?? "",
    reqs,
    tasks,
    members,
    REQ: Object.fromEntries(reqs.map((r) => [r.id, r])),
    TK: Object.fromEntries(tasks.map((t) => [t.id, t])),
    MEM: Object.fromEntries(members.map((m) => [m.id, m])),
    aiAssign,
    rec,
    doc,
    docFromQuotes: fromQuotes,
    skillCols,
    skillLabel,
    validation: out.validation,
    dependencyCount: (out.dependencies ?? []).length,
    generatedAt: out.metadata?.generated_at ?? null,
    period,
  };
}

/** 負荷の上限が何を表すか（凡例・説明用） */
export function capLabel(M: Model): string {
  return M.period ? `${M.period.start}〜${M.period.end}の稼働可能時間` : "週あたり稼働可能時間";
}

// ─── 負荷・適合度の計算 ─────────────────────────────────────────────────────

/** 既存業務 + 割当タスクの合計工数。ex を指定するとそのタスクを除いて計算する */
export function hoursOf(M: Model, mid: string, a: Assignment, ex?: string): number {
  let h = M.MEM[mid]?.base ?? 0;
  M.tasks.forEach((t) => {
    if (a[t.id] === mid && t.id !== ex) h += t.h;
  });
  return Math.round(h * 10) / 10;
}

export function pctFor(cap: number, hours: number): number {
  if (cap > 0) return Math.round((hours / cap) * 100);
  return hours > 0 ? 100 : 0;
}

export function pctOf(M: Model, mid: string, a: Assignment): number {
  return pctFor(M.MEM[mid]?.cap ?? 0, hoursOf(M, mid, a));
}

export const levelOf = (m: VMember, skill: string): number => m.sk[norm(skill)] || 0;

/** 担当者が保有していない必要スキル */
export function missingSkills(m: VMember, t: VTask): string[] {
  return t.skills.filter((s) => levelOf(m, s) < 1);
}

export interface Score {
  total: number;
  /** スキル一致（最大60） */
  skill: number;
  /** 負荷の余裕（最大40） */
  load: number;
  /** 必要スキルのうち最も低い保有レベル */
  minLv: number;
  /** 割当後の負荷% */
  after: number;
  missing: string[];
}

export const SKILL_MAX = 60;
export const LOAD_MAX = 40;

/**
 * 画面上の「適合度」。バックエンドの scoring.py と同じ考え方
 * （スキル一致 = 必要スキルごとの level/5 の平均、負荷 = 割当後に残る稼働の割合）を、
 * 担当変更のたびに再計算できるよう 60:40 の2要素に絞ったもの。
 * バックエンドが算出したAIスコアは rec[taskId].candidate_scores に別途保持している。
 */
export function scoreOf(M: Model, m: VMember, t: VTask, a: Assignment): Score {
  const lvs = t.skills.map((s) => levelOf(m, s));
  const skillMatch = lvs.length ? lvs.reduce((s, l) => s + Math.min(l, 5) / 5, 0) / lvs.length : 1;
  const hoursAfter = hoursOf(M, m.id, a, t.id) + t.h;
  const after = pctFor(m.cap, hoursAfter);
  const loadRatio = m.cap > 0 ? Math.max(0, Math.min(1, (m.cap - hoursAfter) / m.cap)) : 0;
  const skill = skillMatch * SKILL_MAX;
  const load = loadRatio * LOAD_MAX;
  return {
    total: Math.max(0, Math.min(100, Math.round(skill + load))),
    skill: Math.round(skill),
    load: Math.round(load),
    minLv: lvs.length ? Math.min(...lvs) : 0,
    after,
    missing: missingSkills(m, t),
  };
}

/** バックエンドが算出したAIスコア（0-100）。候補外なら null */
export function aiScoreOf(M: Model, taskId: string, memberId: string): number | null {
  const c = M.rec[taskId]?.candidate_scores?.find((x) => x.member_id === memberId);
  return c ? Math.round(c.score) : null;
}

/** バックエンドが候補から除外した理由 */
export function rejectedReasons(M: Model, taskId: string, memberId: string): string[] {
  return M.rec[taskId]?.rejected_candidates?.find((x) => x.member_id === memberId)?.reasons ?? [];
}

/** backend/pipeline/validation/unassigned.py の _REASON_MESSAGES と同じ文言 */
const UNASSIGNED_REASON_MESSAGES: Record<string, string> = {
  NO_CANDIDATE: "メンバーが1人も登録されていません",
  HARD_CONSTRAINT: "明示的な制約を満たす候補者がいませんでした",
  NO_REQUIRED_SKILL: "必要スキルを持つ候補者がいませんでした",
  NO_AVAILABILITY: "稼働可能な候補者がいませんでした",
  WORKLOAD_TOO_HIGH: "見積り工数が全候補者の残りキャパシティを超えていました",
  DEADLINE_INFEASIBLE: "期限までに完了できる稼働時間を持つ候補者がいませんでした",
  INVALID_MEMBER_DATA: "メンバーデータの読み込みエラーにより候補者が存在しませんでした",
  UNKNOWN: "未割当の理由を特定できませんでした",
};

/** 未割当タスクの理由（バックエンドの判定をそのまま使う） */
export function unassignedReason(M: Model, taskId: string): string {
  const r = M.rec[taskId] as (AssignmentResult & { unassigned_reason?: string | null }) | undefined;
  if (!r) return "割当結果がありません";
  const reasons = [...new Set((r.rejected_candidates ?? []).flatMap((x) => x.reasons))];
  const detail = reasons.length
    ? reasons.slice(0, 2).join(" / ") + (reasons.length > 2 ? ` ほか${reasons.length - 2}件` : "")
    : "";
  const head = r.unassigned_reason
    ? UNASSIGNED_REASON_MESSAGES[r.unassigned_reason] ?? r.unassigned_reason
    : (r.warnings ?? []).join(" / ");
  if (head && detail) return `${head}（${detail}）`;
  return head || detail || "条件を満たす候補がいません";
}

/** 依存の深さ（着手レベル）と、見積り工数で見た最長経路（クリティカルパス） */
export function dependencyInfo(M: Model): { depth: Record<string, number>; chain: string[]; total: number } {
  const depth: Record<string, number> = {};
  const fin: Record<string, number> = {};
  const prev: Record<string, string | null> = {};
  const visiting = new Set<string>();

  // 循環依存があっても無限再帰しないよう、訪問中のノードは 0 として扱う
  const depthOf = (id: string): number => {
    if (depth[id] != null) return depth[id];
    if (visiting.has(id)) return 0;
    visiting.add(id);
    const t = M.TK[id];
    const d = t && t.deps.length ? 1 + Math.max(...t.deps.map(depthOf)) : 0;
    visiting.delete(id);
    return (depth[id] = d);
  };
  const finOf = (id: string): number => {
    if (fin[id] != null) return fin[id];
    if (visiting.has(id)) return 0;
    visiting.add(id);
    const t = M.TK[id];
    let best = 0;
    let bp: string | null = null;
    (t?.deps ?? []).forEach((d) => {
      const f = finOf(d);
      if (f > best) { best = f; bp = d; }
    });
    visiting.delete(id);
    prev[id] = bp;
    return (fin[id] = best + (t?.h ?? 0));
  };
  M.tasks.forEach((t) => { depthOf(t.id); finOf(t.id); });
  if (!M.tasks.length) return { depth, chain: [], total: 0 };
  const end = M.tasks.reduce((b, t) => (fin[t.id] > fin[b.id] ? t : b), M.tasks[0]).id;
  const chain: string[] = [];
  const guard = new Set<string>();
  for (let c: string | null = end; c && !guard.has(c); c = prev[c] ?? null) {
    guard.add(c);
    chain.unshift(c);
  }
  return { depth, chain, total: Math.round(fin[end] * 10) / 10 };
}

// ─── 入力（メンバー編集）のパース ─────────────────────────────────────────────

/** "Python:4, React:3, SQL" → スキル配列（レベル省略時は3） */
export function parseSkills(text: string): { skill: string; level: number }[] {
  const out: { skill: string; level: number }[] = [];
  text.split(/[,、，\n]/).forEach((part) => {
    const s = part.trim();
    if (!s) return;
    const m = s.match(/^(.*?)[\s:：]*(?:lv\.?\s*)?([1-5])$/i);
    const name = (m ? m[1] : s).trim();
    const level = m ? Number(m[2]) : 3;
    if (name) out.push({ skill: name, level });
  });
  return out;
}

export function formatSkills(m: PipelineMember): string {
  return (m.skills || []).map((s) => `${s.skill}:${s.level}`).join(", ");
}
