// src/specToTasks/app.ts
//
// 画面: Spec to Tasks（仕様書 → 要件抽出 → タスク分解 → 自動割当 → Kanban）の
// 11ステップ・ウィザード。claude.ai/design「Spec to Tasks.dc.html」のUIを、
// 実際のバックエンドAPI（変更なし）に接続したもの。
//
// 使うAPI（すべて src/services/projectService.ts 経由）:
//   POST /api/projects, GET /api/projects/{id}
//   PUT/GET /api/projects/{id}/members
//   POST /api/projects/{id}/generate → GET /api/jobs/{job_id}（ポーリング）
//   GET /api/jobs/{job_id}/result, GET /api/jobs/{job_id}/error
//
// バックエンドに保存APIが無いもの（担当者の手動変更・警告の確認済み・Kanbanの
// ステータス）は、ジョブごとにこのブラウザの localStorage に保存する。
import "../style.css";
import "./industry.css";
import "./spec-to-tasks.css";
import {
  createProject,
  fetchProjectMembers,
  getActiveJobId,
  getActiveProjectId,
  getJobError,
  getJobStatus,
  getProject,
  getProjectResult,
  getSampleProjectResult,
  invalidateProjectResultCache,
  setActiveJobId,
  setProjectMembers,
  startGeneration,
} from "../services/projectService";
import { extractErrorMessage } from "../pipeline/format";
import { PIPELINE_STEPS } from "../types/taskGenerationProgress";
import type { JobStatusResponse } from "../types/job";
import type { PipelineMember } from "../types/pipeline";
import {
  CAT_NOTE, LOAD_MAX, LOW_CONF, SKILL_MAX, WARN, WARN_BG, WARN_FG,
  aiScoreOf, buildModel, dependencyInfo, formatSkills, hoursOf, levelOf, missingSkills,
  norm, parseSkills, pctOf, rejectedReasons, scoreOf, unassignedReason,
} from "./model";
import type { Assignment, Model, VMember, VRequirement, VTask } from "./model";

// ─── 定数 ────────────────────────────────────────────────────────────────

interface Step { n: number; t: string; g: number; d: string }

const STEPS: Step[] = [
  { n: 1, t: "仕様書をアップロード", g: 0, d: "要件定義書・仕様書の本文を読み込みます" },
  { n: 2, t: "AI分析開始", g: 0, d: "チームと分析条件を確認して開始します" },
  { n: 3, t: "進捗表示", g: 0, d: "AIが仕様書を読み進めています" },
  { n: 4, t: "要件抽出", g: 1, d: `仕様書から要件を抽出しました。信頼度${LOW_CONF}%未満の項目は要確認です` },
  { n: 5, t: "タスク分解", g: 1, d: "各要件を実装タスクに分解し、工数と必要スキルを見積もりました" },
  { n: 6, t: "依存関係", g: 1, d: "着手順序とクリティカルパス" },
  { n: 7, t: "スキル・負荷", g: 2, d: "メンバーごとのスキルレベルと、既存業務を含めた負荷" },
  { n: 8, t: "自動割り当て", g: 2, d: "スキル適合度と負荷のバランスで担当者を割り当てました" },
  { n: 9, t: "未割当・警告", g: 2, d: "人の判断が必要な項目です。提案をクリックするとすぐ反映されます" },
  { n: 10, t: "出典を確認", g: 3, d: "すべてのタスクは仕様書の該当箇所に紐づいています" },
  { n: 11, t: "Kanban", g: 3, d: "ドラッグ、または → でステータスを更新" },
];
const GROUPS = ["取り込み", "分析", "割り当て", "管理"];
const VARIANTS: Record<number, string[]> = {
  4: ["テーブル", "原文と並列", "カテゴリ別"],
  7: ["スキル表", "メンバーカード", "負荷バー"],
  8: ["割当テーブル", "メンバー別", "根拠つき"],
  9: ["警告リスト", "サマリー"],
};
const KANBAN_COLS = ["未着手", "進行中", "レビュー", "完了"] as const;
type KanbanCol = (typeof KANBAN_COLS)[number];

const TEXT_EXT = /\.(txt|md|markdown|csv|tsv|json|html?|xml|ya?ml)$/i;
const BINARY_EXT = /\.(pdf|docx?|pptx?|xlsx?|rtf)$/i;
const MAX_FILE_BYTES = 50 * 1024 * 1024;
const POLL_INTERVAL_MS = 1500;

/** 動作確認用の短いサンプル仕様書（バックエンドで実際に分析される） */
const SAMPLE_SPEC = `1. 概要
本書は、ECサイト「minato store」のリニューアルにおける要件を定義する。
本システムは2027年3月末までに本番リリースすること。段階リリースは行わない。

3. 機能要件
利用者はメールアドレスまたはSNSアカウント（Google / LINE）で会員登録・ログインできること。

キーワード検索に加え、カテゴリ・価格帯・在庫有無による絞り込みを提供する。

カートへの追加・数量変更・削除を行い、3ステップ以内で購入を完了できること。

クレジットカードおよびコンビニ決済に対応する。カード情報は自社サーバーに保持しない。

会員は過去の注文履歴と配送状況をマイページで確認できること。

4. 管理機能
管理者は商品の登録・編集・公開設定を管理画面から行える。

5. 非機能要件
ページは高速に表示されること。

PC・スマートフォン・タブレットで最適に表示されること。

決済に関わる処理はPCI DSSに準拠した構成とする。`;

// ─── 状態 ────────────────────────────────────────────────────────────────

interface MemberDraft { id: string; name: string; skills: string; cap: number; base: number; days: string[]; raw?: PipelineMember }
interface LogLine { t: string; msg: string }

interface State {
  step: number;
  maxStep: number;
  docText: string;
  fileName: string;
  fileNote: { kind: "ok" | "error"; text: string } | null;
  projectId: string | null;
  projectName: string;
  newProject: boolean;
  members: MemberDraft[];
  membersNote: string | null;
  optLlmReason: boolean;
  optDupLlm: boolean;
  starting: boolean;
  startError: string | null;
  jobId: string | null;
  job: JobStatusResponse | null;
  jobError: string | null;
  logs: LogLine[];
  model: Model | null;
  loadingResult: boolean;
  variant: Record<number, number>;
  assign: Assignment;
  acked: Record<string, boolean>;
  selReq: string;
  selTask: string;
  kb: Record<string, KanbanCol>;
  demo: boolean;
}

const state: State = {
  step: 1,
  maxStep: 2,
  docText: "",
  fileName: "",
  fileNote: null,
  projectId: null,
  projectName: "",
  newProject: false,
  members: [],
  membersNote: null,
  optLlmReason: false,
  optDupLlm: false,
  starting: false,
  startError: null,
  jobId: null,
  job: null,
  jobError: null,
  logs: [],
  model: null,
  loadingResult: false,
  variant: { 4: 0, 7: 0, 8: 0, 9: 0 },
  assign: {},
  acked: {},
  selReq: "",
  selTask: "",
  kb: {},
  demo: false,
};

let root: HTMLElement;
let pollToken = 0;
let jobStartedAt = 0;
let userLabel = "";

function setState(patch: Partial<State>): void {
  Object.assign(state, patch);
  render();
}

// ─── ローカル保存（バックエンドに保存APIが無い情報のみ） ───────────────────

const LS = {
  get(key: string): string | null {
    try { return localStorage.getItem(key); } catch { return null; }
  },
  set(key: string, value: string | null): void {
    try {
      if (value == null) localStorage.removeItem(key);
      else localStorage.setItem(key, value);
    } catch { /* 容量超過・プライベートモード等。保存できなくても動作は続ける */ }
  },
};
const DRAFT_KEY = "tasumiru.s2t.draft";
const docKey = (jobId: string) => `tasumiru.s2t.doc.${jobId}`;
const workKey = (jobId: string) => `tasumiru.s2t.work.${jobId}`;

function saveDraft(): void {
  LS.set(DRAFT_KEY, JSON.stringify({ text: state.docText, fileName: state.fileName }));
}

function saveWork(): void {
  if (!state.jobId || state.demo) return;
  const overrides: Assignment = {};
  const M = state.model;
  if (M) {
    M.tasks.forEach((t) => {
      if (state.assign[t.id] !== M.aiAssign[t.id]) overrides[t.id] = state.assign[t.id] ?? "";
    });
  }
  LS.set(workKey(state.jobId), JSON.stringify({ overrides, acked: state.acked, kb: state.kb }));
}

function loadWork(jobId: string, M: Model): Pick<State, "assign" | "acked" | "kb"> {
  const assign: Assignment = { ...M.aiAssign };
  const kb: Record<string, KanbanCol> = Object.fromEntries(M.tasks.map((t) => [t.id, "未着手" as KanbanCol]));
  let acked: Record<string, boolean> = {};
  try {
    const raw = JSON.parse(LS.get(workKey(jobId)) || "null");
    if (raw) {
      Object.entries(raw.overrides || {}).forEach(([tid, mid]) => {
        if (!M.TK[tid]) return;
        if (!mid) delete assign[tid];
        else if (M.MEM[mid as string]) assign[tid] = mid as string;
      });
      Object.entries(raw.kb || {}).forEach(([tid, col]) => {
        if (M.TK[tid] && (KANBAN_COLS as readonly string[]).includes(col as string)) kb[tid] = col as KanbanCol;
      });
      acked = raw.acked || {};
    }
  } catch { /* 壊れた保存データは無視 */ }
  return { assign, acked, kb };
}

// ─── ナビゲーション ──────────────────────────────────────────────────────

function canEnter(n: number): boolean {
  if (n <= 2) return true;
  if (n === 3) return !!state.jobId;
  return !!state.model;
}

function go(n: number): void {
  n = Math.max(1, Math.min(11, n));
  if (!canEnter(n)) return;
  setState({ step: n, maxStep: Math.max(state.maxStep, n) });
  window.scrollTo(0, 0);
}

function setAssign(tid: string, mid: string): void {
  setState({ assign: { ...state.assign, [tid]: mid || undefined }, selTask: tid });
  saveWork();
}

function ack(key: string): void {
  setState({ acked: { ...state.acked, [key]: true } });
  saveWork();
}

function openSource(tid: string): void {
  state.selTask = tid;
  go(10);
}

// ─── 共通ヘルパー ────────────────────────────────────────────────────────

const esc = (v: unknown): string =>
  String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]!);

const CORNERS = '<i class="corner tl"></i><i class="corner tr"></i><i class="corner bl"></i><i class="corner br"></i>';
const ACC = "var(--color-accent)";
/** 負荷% → バー幅（125% を満幅とし、上限線が 80% 位置に来るようにする） */
const W = (p: number) => ((Math.max(0, Math.min(125, p)) / 125) * 100).toFixed(1) + "%";
const fmtH = (h: number) => `${Math.round(h * 10) / 10}h`;

const act = (name: string, a?: string | number, b?: string | number): string =>
  `data-act="${name}"` + (a != null ? ` data-a="${esc(a)}"` : "") + (b != null ? ` data-b="${esc(b)}"` : "");

const firstName = (name: string) => name.split(/[\s　]/)[0] || name;
const skillTag = (t: VTask) =>
  t.skills.length
    ? t.skills.slice(0, 2).map((s) => `<span class="tag tag-outline">${esc(s)}</span>`).join("") + (t.skills.length > 2 ? `<span class="tag tag-outline">+${t.skills.length - 2}</span>` : "")
    : `<span class="tag tag-outline" style="color:var(--color-neutral-600)">スキル指定なし</span>`;
const srcLabel = (sec: string, page: number | null) =>
  [sec, page != null ? `p.${page}` : ""].filter(Boolean).join(" ") || "原文";
const docName = () => state.fileName || (state.model ? state.model.name : "貼り付けたテキスト");

function empty(title: string, sub: string, button?: string): string {
  return `<div class="blueprint" style="padding:28px;display:flex;flex-direction:column;gap:10px;align-items:flex-start">${CORNERS}
    <h3 style="margin:0;font-size:24px">${esc(title)}</h3>
    <div style="font-size:13px;color:var(--color-neutral-700)">${esc(sub)}</div>${button ?? ""}</div>`;
}

// ─── 派生データ ──────────────────────────────────────────────────────────

interface MemberView {
  id: string; name: string; ini: string; role: string; pct: number; hTxt: string; cap: number;
  baseW: string; newW: string; barBg: string; pctFg: string; status: string; stBg: string; stFg: string;
  bp: number; over: boolean; mine: VTask[];
}

function memberViews(M: Model, a: Assignment): MemberView[] {
  return M.members.map((m) => {
    const h = hoursOf(M, m.id, a);
    const p = pctOf(M, m.id, a);
    const bp = m.cap > 0 ? Math.round((m.base / m.cap) * 100) : 0;
    const over = p > 100;
    return {
      id: m.id, name: m.name, ini: m.ini, role: m.role, pct: p, hTxt: `${fmtH(h)} / ${fmtH(m.cap)}`, cap: m.cap,
      baseW: W(bp), newW: W(Math.min(p, 125) - Math.min(bp, 125)), barBg: over ? WARN : ACC, pctFg: over ? WARN : "var(--color-text)",
      status: p > 100 ? "過負荷" : p > 85 ? "高負荷" : p >= 60 ? "適正" : "余裕あり",
      stBg: over ? WARN_BG : p > 85 ? "var(--color-accent-200)" : "var(--color-neutral-100)",
      stFg: over ? WARN_FG : "var(--color-accent-800)",
      bp, over, mine: M.tasks.filter((t) => a[t.id] === m.id),
    };
  });
}

interface TaskRow {
  t: VTask; who: string; whoShort: string; ini: string; whoFg: string;
  score: number | "—"; reason: string; deps: string; assigned: boolean;
}

function skillSummary(m: VMember, t: VTask): string {
  if (!t.skills.length) return "必要スキルの指定なし";
  return t.skills.slice(0, 3).map((s) => { const lv = levelOf(m, s); return lv ? `${s} Lv${lv}` : `${s} 未保有`; }).join(" · ");
}

function taskRow(M: Model, t: VTask, a: Assignment): TaskRow {
  const mid = a[t.id];
  const m = mid ? M.MEM[mid] : undefined;
  const sc = m ? scoreOf(M, m, t, a) : null;
  return {
    t,
    who: m ? m.name : "未割当",
    whoShort: m ? firstName(m.name) : "未割当",
    ini: m ? m.ini : "?",
    whoFg: m ? "var(--color-text)" : WARN,
    score: sc ? sc.total : "—",
    reason: m && sc
      ? `${skillSummary(m, t)} · ${firstName(m.name)}の負荷 ${pctOf(M, m.id, a)}%` + (sc.missing.length ? " · スキル不足" : "")
      : unassignedReason(M, t.id),
    deps: t.deps.length ? t.deps.join(", ") : "なし",
    assigned: !!m,
  };
}

/** 候補者を「必要スキルを満たす人 → 適合度の高い順」に並べる */
function rankCandidates(M: Model, t: VTask, a: Assignment, exclude?: string) {
  return M.members
    .filter((m) => m.id !== exclude)
    .map((m) => ({ m, s: scoreOf(M, m, t, a) }))
    .sort((x, y) => x.s.missing.length - y.s.missing.length || y.s.total - x.s.total);
}

interface WarnAction { label: string; sub: string; attrs: string }
interface Warning { kind: string; sev: 0 | 1 | 2; title: string; detail: string; actions: WarnAction[]; bg: string; fg: string }

const WARN_KINDS: [string, 0 | 1 | 2][] = [["未割当", 0], ["過負荷", 0], ["スキル不足", 1], ["検証エラー", 1], ["要件が曖昧", 2], ["要レビュー", 2], ["重複の可能性", 2]];

function buildWarnings(M: Model, a: Assignment): Warning[] {
  const warns: Omit<Warning, "bg" | "fg">[] = [];
  const wa = (label: string, sub: string, attrs: string): WarnAction => ({ label, sub, attrs });
  const cand = (x: { m: VMember; s: ReturnType<typeof scoreOf> }) =>
    `適合 ${x.s.total} · 負荷→${x.s.after}%` + (x.s.missing.length ? ` · 不足 ${x.s.missing.length}` : "");

  M.tasks.filter((t) => !a[t.id]).forEach((t) => {
    warns.push({
      kind: "未割当", sev: 0, title: `${t.id} ${t.title}`,
      detail: unassignedReason(M, t.id),
      actions: rankCandidates(M, t, a).slice(0, 2).map((x) => wa(`${x.m.name}に割当`, cand(x), act("assign", t.id, x.m.id))),
    });
  });

  M.members.forEach((m) => {
    const p = pctOf(M, m.id, a);
    if (p <= 100) return;
    const mine = M.tasks.filter((t) => a[t.id] === m.id).sort((x, y) => x.h - y.h);
    warns.push({
      kind: "過負荷", sev: 0, title: `${m.name}の負荷が${p}%`,
      detail: `上限 ${fmtH(m.cap)} に対し ${fmtH(hoursOf(M, m.id, a))}（既存 ${fmtH(m.base)} + ${mine.map((t) => t.id).join("・") || "なし"}）`,
      actions: mine.slice(0, 2).flatMap((t) => {
        const alt = rankCandidates(M, t, a, m.id)[0];
        return alt ? [wa(`${t.id}を${alt.m.name}へ`, cand(alt), act("assign", t.id, alt.m.id))] : [];
      }),
    });
  });

  M.tasks.forEach((t) => {
    const mid = a[t.id];
    if (!mid || state.acked[`skill:${t.id}`]) return;
    const m = M.MEM[mid];
    if (!m) return;
    const miss = missingSkills(m, t);
    if (!miss.length) return;
    const alt = rankCandidates(M, t, a, mid).filter((x) => !x.s.missing.length).slice(0, 1);
    warns.push({
      kind: "スキル不足", sev: 1, title: `${t.id} ${t.title}`,
      detail: `${m.name}：${miss.join("・")} を未保有`,
      actions: alt
        .map((x) => wa(`${x.m.name}に変更`, cand(x), act("assign", t.id, x.m.id)))
        .concat([wa("このまま進める", "レビュー担当を付ける", act("ack", `skill:${t.id}`))]),
    });
  });

  const rep = M.validation?.report;
  if (rep) {
    const taskLink = (ids: string[]) => ids.find((id) => M.TK[id]);
    const pushV = (kind: string, sev: 0 | 1 | 2, key: string, title: string, detail: string, ids: string[]) => {
      if (state.acked[key]) return;
      const tid = taskLink(ids);
      warns.push({
        kind, sev, title, detail,
        actions: (tid ? [wa("出典を確認", tid, act("openSource", tid))] : []).concat([wa("確認済みにする", "この警告を閉じる", act("ack", key))]),
      });
    };
    rep.missing_requirements?.forEach((x) => {
      const r = M.REQ[x.requirement_id];
      const tid = M.tasks.find((t) => t.reqIds.includes(x.requirement_id))?.id;
      pushV("検証エラー", 1, `miss:${x.requirement_id}`, `${x.requirement_id} ${r?.title ?? ""}`, x.message, tid ? [tid] : []);
    });
    rep.dependency_errors?.forEach((x, i) => pushV("検証エラー", 1, `dep:${x.code}:${i}`, x.task_ids.join(" → ") || x.code, x.message, x.task_ids));
    rep.constraint_violations?.forEach((x) => pushV("検証エラー", 1, `cv:${x.task_id}:${x.member_id}`, `${x.task_id} ${M.TK[x.task_id]?.title ?? ""}`, x.message, [x.task_id]));
    rep.duplicate_tasks?.forEach((x) =>
      pushV("重複の可能性", 2, `dup:${x.task_ids.join(",")}`, x.task_ids.map((id) => `${id} ${M.TK[id]?.title ?? ""}`).join(" / "),
        `類似度 ${Math.round(x.similarity * 100)}% · ${x.reason}`, x.task_ids));
  }

  M.reqs.filter((r) => r.conf < LOW_CONF && !state.acked[`req:${r.id}`]).forEach((r) => {
    const tid = M.tasks.find((t) => t.reqIds.includes(r.id))?.id;
    warns.push({
      kind: "要件が曖昧", sev: 2, title: `${r.id} ${r.title}`,
      detail: `信頼度 ${r.conf}%` + (r.srcText ? ` — 原文「${r.srcText.slice(0, 60)}${r.srcText.length > 60 ? "…" : ""}」` : ""),
      actions: (tid ? [wa("出典を確認", srcLabel(r.sec, r.page), act("openSource", tid))] : []).concat([wa("確認済みにする", "顧客に確認依頼済み", act("ack", `req:${r.id}`))]),
    });
  });

  M.tasks.filter((t) => t.needsReview && !state.acked[`rev:${t.id}`]).forEach((t) => {
    warns.push({
      kind: "要レビュー", sev: 2, title: `${t.id} ${t.title}`,
      detail: t.reviewReasons.join(" / ") || "AIが人による確認を推奨しています",
      actions: [wa("出典を確認", srcLabel(t.sec, t.page), act("openSource", t.id)), wa("確認済みにする", "内容を確認した", act("ack", `rev:${t.id}`))],
    });
  });

  const SEV: [string, string][] = [[WARN_BG, WARN_FG], ["var(--color-accent-200)", "var(--color-accent-800)"], ["var(--color-neutral-200)", "var(--color-neutral-800)"]];
  return warns.map((w) => ({ ...w, bg: SEV[w.sev][0], fg: w.sev === 0 ? WARN : SEV[w.sev][1] }));
}

/** 種類ごとに表示件数を絞る（大きな仕様書では数百件になり得るため） */
const WARN_LIMIT = 30;
function limitWarnings(warns: Warning[]): { shown: Warning[]; hidden: Record<string, number> } {
  const count: Record<string, number> = {};
  const hidden: Record<string, number> = {};
  const shown = warns.filter((w) => {
    count[w.kind] = (count[w.kind] || 0) + 1;
    if (count[w.kind] <= WARN_LIMIT) return true;
    hidden[w.kind] = (hidden[w.kind] || 0) + 1;
    return false;
  });
  return { shown, hidden };
}

// ─── レイアウト ──────────────────────────────────────────────────────────

function railHtml(): string {
  return GROUPS.map((title, gi) => `
    <div style="display:flex;flex-direction:column;gap:1px">
      <div style="font-size:10px;letter-spacing:.12em;color:var(--color-neutral-600);padding:0 10px 5px">${esc(title)}</div>
      ${STEPS.filter((s) => s.g === gi).map((s) => {
        const cur = s.n === state.step;
        const ok = s.n <= state.maxStep && canEnter(s.n);
        const done = s.n < state.step && ok;
        const v = VARIANTS[s.n];
        return `
        <div ${ok ? act("go", s.n) : ""} style="display:flex;align-items:center;gap:10px;padding:6px 10px;cursor:${ok ? "pointer" : "default"};background:${cur ? "var(--color-accent-100)" : "transparent"};opacity:${ok || cur ? 1 : 0.45}">
          <span style="width:22px;height:22px;flex:none;display:grid;place-items:center;font:600 12px var(--font-heading);border:1px solid ${cur || done ? ACC : "var(--color-divider)"};background:${cur ? "var(--color-accent-800)" : "transparent"};color:${cur ? "#fff" : done ? "var(--color-accent-700)" : "var(--color-neutral-600)"}">${s.n}</span>
          <span style="flex:1;font-size:13px;color:${cur ? "var(--color-accent-800)" : "var(--color-text)"};font-weight:${cur ? 600 : 400}">${esc(s.t)}</span>
          ${v ? `<span style="font-size:10px;padding:1px 5px;border:1px solid var(--color-accent-300);color:var(--color-accent-700)">${v.length}案</span>` : ""}
        </div>`;
      }).join("")}
    </div>`).join("");
}

function nextDisabled(): boolean {
  const s = state.step;
  if (s === 1) return !state.docText.trim();
  return !canEnter(s + 1);
}

function headerHtml(): string {
  const step = state.step;
  const S = STEPS[step - 1];
  const variants = state.model ? VARIANTS[step] : undefined;
  const hasNext = step < 11 && step !== 2;
  return `
  <header style="position:sticky;top:0;z-index:5;background:var(--color-bg);border-bottom:1px solid var(--color-divider)">
    <div style="display:flex;align-items:center;gap:18px;padding:16px 28px 14px;flex-wrap:wrap">
      <div style="flex:1;min-width:260px;display:flex;flex-direction:column;gap:2px">
        <div style="font-size:11px;letter-spacing:.1em;color:var(--color-accent-700)">STEP ${step} / 11 · ${esc(docName())}</div>
        <h1 style="margin:0;font-size:30px;line-height:1.1">${esc(S.t)}</h1>
        <div style="font-size:13px;color:var(--color-neutral-700)">${esc(S.d)}</div>
      </div>
      ${variants ? `
      <div style="display:flex;flex-direction:column;gap:4px">
        <span style="font-size:10px;letter-spacing:.1em;color:var(--color-neutral-600)">表示案</span>
        <div style="display:flex;border:1px solid var(--color-divider)">
          ${variants.map((l, i) => {
            const on = state.variant[step] === i;
            return `<button ${act("variant", i)} style="border:0;border-right:1px solid var(--color-divider);padding:7px 12px;font:500 12.5px 'Barlow','Noto Sans JP',sans-serif;cursor:pointer;background:${on ? "var(--color-accent-800)" : "transparent"};color:${on ? "#fff" : "var(--color-text)"}">${"ABC"[i]}&nbsp;&nbsp;${esc(l)}</button>`;
          }).join("")}
        </div>
      </div>` : ""}
      <div style="display:flex;gap:8px">
        ${step > 1 ? `<button class="btn btn-secondary" ${act("go", step - 1)}>← 戻る</button>` : ""}
        ${hasNext ? `<button class="btn btn-primary blueprint" data-next ${nextDisabled() ? "disabled" : ""} ${act("go", step + 1)}>${CORNERS}次へ：${esc(STEPS[step].t)} →</button>` : ""}
      </div>
    </div>
    <div style="display:grid;grid-template-columns:repeat(11,1fr);gap:2px;padding:0 28px 0">
      ${STEPS.map((s) => `<div style="height:3px;background:${s.n <= step ? ACC : "var(--color-divider)"}"></div>`).join("")}
    </div>
  </header>`;
}

// ─── STEP 1: アップロード ─────────────────────────────────────────────────

function step1(): string {
  const readRow = (n: string, title: string, sub: string) => `
    <div style="display:grid;grid-template-columns:28px 1fr;gap:10px;padding:12px 0;border-bottom:1px solid var(--color-divider)"><span style="font:600 16px var(--font-heading);color:var(--color-accent)">${n}</span><div><div style="font-weight:500">${title}</div><div style="font-size:12.5px;color:var(--color-neutral-700)">${sub}</div></div></div>`;
  const has = !!state.docText.trim();
  const chars = state.docText.length.toLocaleString();
  const note = state.fileNote
    ? `<div style="font-size:12.5px;padding:8px 10px;${state.fileNote.kind === "error" ? `background:${WARN_BG};color:${WARN_FG}` : "background:var(--color-accent-100);color:var(--color-accent-800)"}">${esc(state.fileNote.text)}</div>`
    : "";
  return `
  <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(320px,1fr));gap:32px;align-items:start">
    <div style="display:flex;flex-direction:column;gap:14px">
      <div class="blueprint s2t-drop" ${act("pickFile")} style="min-height:220px;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:12px;cursor:pointer;border-style:dashed;padding:28px;text-align:center">
        ${CORNERS}
        ${!has ? `
        <span style="color:var(--color-accent)"><svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path><polyline points="17 8 12 3 7 8"></polyline><line x1="12" y1="3" x2="12" y2="15"></line></svg></span>
        <h2 style="margin:0;font-size:28px">仕様書をここにドロップ</h2>
        <div style="font-size:13px;color:var(--color-neutral-700)">テキスト / Markdown ファイル · 最大 50MB</div>
        <div style="display:flex;gap:10px;margin-top:6px;flex-wrap:wrap;justify-content:center"><span class="btn btn-secondary">ファイルを選択</span><span class="btn btn-ghost" ${act("sample")}>サンプル仕様書で試す</span></div>` : `
        <div class="blueprint" style="width:96px;height:120px;display:flex;flex-direction:column;justify-content:flex-end;padding:10px;background:repeating-linear-gradient(0deg,transparent 0 11px,var(--color-accent-200) 11px 12px)">
          ${CORNERS}
          <span style="font:600 14px var(--font-heading);background:var(--color-accent-800);color:#fff;align-self:flex-start;padding:1px 6px">${esc((state.fileName.split(".").pop() || "TXT").toUpperCase().slice(0, 4))}</span>
        </div>
        <div style="font:600 20px var(--font-heading)">${esc(docName())}</div>
        <div style="font-size:13px;color:var(--color-neutral-700)">${chars}字</div>
        <div style="display:flex;gap:8px;align-items:center"><span class="tag tag-accent">✓ 読み込み完了</span><span class="btn btn-ghost" ${act("clearDoc")} style="font-size:12.5px">クリア</span></div>`}
      </div>
      ${note}
      <div class="field">
        <label for="s2t-doc">仕様書の本文（直接貼り付け・編集もできます）</label>
        <textarea id="s2t-doc" class="input" data-bind="docText" style="min-height:220px;font-size:13px;line-height:1.6" placeholder="要件定義書・仕様書・RFP の本文をここに貼り付けてください">${esc(state.docText)}</textarea>
      </div>
    </div>
    <div style="display:flex;flex-direction:column;gap:18px;padding-top:6px">
      <h3 style="margin:0;font-size:22px">AIが読み取るもの</h3>
      <div style="display:flex;flex-direction:column;border-top:1px solid var(--color-divider)">
        ${readRow("01", "機能・非機能要件と制約", "文章から要件を切り出し、優先度と信頼度を付与")}
        ${readRow("02", "出典（章・段落）", "すべてのタスクに原文の該当箇所を紐づけ")}
        ${readRow("03", "曖昧な記述", "信頼度の低い要件・レビューが必要なタスクを「要確認」として検出")}
      </div>
      <div style="font-size:12.5px;color:var(--color-neutral-700);line-height:1.7">PDF / Word は、バックエンドの分析APIがテキスト本文のみを受け付けるため、本文をコピーして上の欄に貼り付けてください。</div>
    </div>
  </div>`;
}

// ─── STEP 2: 分析条件 ────────────────────────────────────────────────────

function step2(): string {
  const row = (label: string, body: string, last = false, pad = "14px 20px") => `
    <div style="display:grid;grid-template-columns:minmax(100px,150px) minmax(0,1fr);${last ? "" : "border-bottom:1px solid var(--color-divider)"}"><div style="padding:16px 20px;font-size:12px;color:var(--color-neutral-700)">${label}</div><div style="padding:${pad}">${body}</div></div>`;
  const inputCss = "min-height:32px;padding:4px 8px;font-size:13px";
  const memberRows = state.members.map((m, i) => `
    <div style="display:grid;grid-template-columns:minmax(90px,1fr) minmax(140px,2fr) 64px 64px 28px;gap:6px;align-items:center">
      <input class="input" style="${inputCss}" data-mi="${i}" data-mf="name" value="${esc(m.name)}" placeholder="氏名">
      <input class="input" style="${inputCss}" data-mi="${i}" data-mf="skills" value="${esc(m.skills)}" placeholder="Python:4, React:3">
      <input class="input" style="${inputCss}" data-mi="${i}" data-mf="cap" type="number" min="0" step="1" value="${m.cap}" title="週あたり稼働可能時間">
      <input class="input" style="${inputCss}" data-mi="${i}" data-mf="base" type="number" min="0" step="1" value="${m.base}" title="既存業務の時間">
      <button class="btn btn-ghost" ${act("delMember", i)} title="削除" style="padding:2px 6px">×</button>
    </div>`).join("");
  const ready = !!state.docText.trim() && state.members.some((m) => m.name.trim());
  const busy = state.starting;
  return `
  <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(340px,1fr));gap:32px;align-items:start">
    <div class="blueprint" style="padding:0">
      ${CORNERS}
      ${row("対象の仕様書", `<span style="font-weight:500">${esc(docName())}</span> <span style="font-weight:400;color:var(--color-neutral-600);font-size:12.5px">· ${state.docText.length.toLocaleString()}字</span>`)}
      ${row("プロジェクト", `<div style="display:flex;flex-direction:column;gap:8px">
        ${state.projectId ? `<label class="radio"><input type="radio" name="proj" value="current" ${!state.newProject ? "checked" : ""}><span class="dot"></span>現在のプロジェクト：${esc(state.projectName || "無題")}</label>
        <label class="radio"><input type="radio" name="proj" value="new" ${state.newProject ? "checked" : ""}><span class="dot"></span>新しいプロジェクトを作成</label>` : ""}
        ${!state.projectId || state.newProject ? `<input class="input" style="${inputCss}" data-bind="projectName" value="${esc(state.projectName)}" placeholder="プロジェクト名（例：ECサイト リニューアル）">` : ""}
      </div>`)}
      ${row("割当対象チーム", `<div style="display:flex;flex-direction:column;gap:8px">
        <div style="display:grid;grid-template-columns:minmax(90px,1fr) minmax(140px,2fr) 64px 64px 28px;gap:6px;font-size:11px;color:var(--color-neutral-600)"><span>氏名</span><span>スキル:レベル(1〜5)</span><span>稼働h/週</span><span>既存h</span><span></span></div>
        ${memberRows || `<div style="font-size:12.5px;color:var(--color-neutral-600)">メンバーがいません。1人以上追加してください。</div>`}
        <div><button class="btn btn-secondary" ${act("addMember")} style="font-size:12.5px;padding:4px 10px">＋ メンバーを追加</button></div>
        ${state.membersNote ? `<div style="font-size:12px;color:var(--color-neutral-700)">${esc(state.membersNote)}</div>` : ""}
      </div>`)}
      ${row("オプション", `<div style="display:flex;flex-direction:column;gap:8px;font-size:13px">
        <label style="display:flex;gap:8px;align-items:center;cursor:pointer"><input type="checkbox" data-bind-check="optLlmReason" ${state.optLlmReason ? "checked" : ""}>割当理由をAIで補足する（時間がかかります）</label>
        <label style="display:flex;gap:8px;align-items:center;cursor:pointer"><input type="checkbox" data-bind-check="optDupLlm" ${state.optDupLlm ? "checked" : ""}>重複タスクの判定にAIを使う</label>
      </div>`, true)}
    </div>
    <div style="display:flex;flex-direction:column;gap:16px">
      <h3 style="margin:0;font-size:22px">${ready ? "準備ができました" : "あと少しです"}</h3>
      <p style="margin:0;font-size:13.5px;color:var(--color-neutral-700)">分析には仕様書の長さに応じて数分かかります。完了後、要件・タスク・割当案を順に確認できます。割当はあとから自由に変更できます。</p>
      ${!state.docText.trim() ? `<div style="font-size:12.5px;color:${WARN_FG}">STEP 1 で仕様書の本文を入力してください。</div>` : ""}
      ${state.startError ? `<div style="font-size:12.5px;padding:10px 12px;background:${WARN_BG};color:${WARN_FG}">${esc(state.startError)}</div>` : ""}
      ${state.demo ? `<div style="font-size:12.5px;color:var(--color-neutral-700)">デモモード（バックエンド未接続）のため分析は実行できません。STEP 4 以降でサンプル結果を確認できます。</div>` : ""}
      <button class="btn btn-primary blueprint" ${act("start")} ${!ready || busy || state.demo ? "disabled" : ""} style="padding:16px 20px;font-size:18px">${CORNERS}${busy ? "開始しています…" : "AI分析を開始 →"}</button>
    </div>
  </div>`;
}

// ─── STEP 3: 進捗 ────────────────────────────────────────────────────────

function step3(): string {
  const j = state.job;
  if (!state.jobId) return empty("分析はまだ開始されていません", "STEP 2 から AI分析を開始してください。", `<button class="btn btn-secondary" ${act("go", 2)}>STEP 2 へ</button>`);
  const status = j?.status ?? "queued";
  const done = status === "completed";
  const failed = status === "failed" || status === "cancelled";
  const p = done ? 100 : Math.max(0, Math.min(100, j?.progress ?? 0));
  const curIdx = PIPELINE_STEPS.findIndex((s) => s.id === j?.current_step);
  const phaseNow = done ? "分析完了" : failed ? "分析失敗" : status === "queued" ? "開始待ち" : (PIPELINE_STEPS[curIdx]?.label ?? j?.message ?? "処理中");
  const M = state.model;
  const counters: [string, string][] = [
    ["要件", M ? String(M.reqs.length) : "—"],
    ["タスク", M ? String(M.tasks.length) : "—"],
    ["依存関係", M ? String(M.dependencyCount) : "—"],
    ["割当", M ? String(Object.values(M.aiAssign).filter(Boolean).length) : "—"],
  ];
  const warnCount = M ? buildWarnings(M, state.assign).length : 0;
  return `
  <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(360px,1fr));gap:32px;align-items:start">
    <div style="display:flex;flex-direction:column;gap:22px">
      <div style="display:flex;align-items:flex-end;gap:16px"><span style="font:600 104px/0.9 var(--font-heading);letter-spacing:-.02em;color:${failed ? WARN : "var(--color-text)"}">${Math.round(p)}</span><span style="font:600 32px var(--font-heading);color:var(--color-neutral-600);padding-bottom:8px">%</span><span style="flex:1"></span><span style="font-size:13px;color:${failed ? WARN : "var(--color-accent-700)"};padding-bottom:10px;white-space:nowrap">${esc(phaseNow)}</span></div>
      <div style="height:8px;border:1px solid var(--color-divider);position:relative"><div style="position:absolute;inset:0 auto 0 0;width:${p}%;background:${failed ? WARN : ACC};transition:width .4s"></div></div>
      <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(120px,1fr));gap:14px">
        ${counters.map(([label, val]) => `<div class="blueprint" style="padding:14px 16px;display:flex;flex-direction:column;gap:2px">${CORNERS}<span style="font-size:11px;color:var(--color-neutral-700)">${label}</span><span style="font:600 40px/1 var(--font-heading)">${val}</span></div>`).join("")}
      </div>
      <div style="display:flex;flex-direction:column;border-top:1px solid var(--color-divider)">
        ${PIPELINE_STEPS.map((s, i) => {
          const sDone = done || (curIdx >= 0 && i < curIdx);
          const active = !done && !failed && i === curIdx;
          const err = failed && i === curIdx;
          const on = sDone || active || err;
          return `<div style="display:flex;align-items:center;gap:12px;padding:10px 0;border-bottom:1px solid var(--color-divider);color:${on ? "var(--color-text)" : "var(--color-neutral-500)"}"><span style="width:20px;height:20px;display:grid;place-items:center;font-size:11px;border:1px solid ${err ? WARN : on ? ACC : "var(--color-divider)"};background:${sDone ? ACC : err ? WARN : "transparent"};color:${sDone || err ? "#fff" : ACC}">${sDone ? "✓" : err ? "!" : active ? "●" : ""}</span><span style="flex:1;font-size:14px;font-weight:${active ? 600 : 400}">${esc(s.label)}</span><span style="font-size:12px">${sDone ? "完了" : err ? "エラー" : active ? "処理中…" : "待機"}</span></div>`;
        }).join("")}
      </div>
      ${failed ? `<div style="display:flex;flex-direction:column;gap:10px;padding:12px 14px;background:${WARN_BG};color:${WARN_FG};font-size:13px">${esc(state.jobError || j?.message || "分析中にエラーが発生しました")}<div style="display:flex;gap:8px"><button class="btn btn-secondary" ${act("go", 2)}>条件を見直して再実行</button></div></div>` : ""}
      ${done && M ? `<div style="display:flex;gap:10px;align-items:center;flex-wrap:wrap"><button class="btn btn-primary blueprint" ${act("go", 4)}>${CORNERS}抽出された要件を確認 →</button><span style="font-size:13px;color:var(--color-neutral-700)">要件${M.reqs.length}件 · タスク${M.tasks.length}件 · 割当${counters[3][1]}件 · 要対応${warnCount}件</span></div>` : ""}
      ${done && !M ? `<div style="font-size:13px;color:var(--color-neutral-700)">${state.loadingResult ? "分析結果を読み込んでいます…" : `<button class="btn btn-secondary" ${act("reloadResult")}>分析結果を読み込む</button>`}</div>` : ""}
    </div>
    <div class="blueprint" style="padding:16px 18px;display:flex;flex-direction:column;gap:10px;min-height:420px">${CORNERS}
      <div style="font-size:10px;letter-spacing:.12em;color:var(--color-neutral-600)">分析ログ</div>
      ${state.logs.length ? state.logs.map((l) => `<div style="display:grid;grid-template-columns:44px 1fr;gap:8px;font-size:12.5px;line-height:1.5"><span style="font-family:var(--font-heading);color:var(--color-accent-700)">${esc(l.t)}</span><span>${esc(l.msg)}</span></div>`).join("") : `<div style="font-size:12.5px;color:var(--color-neutral-600)">バックエンドからの進捗を待っています…</div>`}
    </div>
  </div>`;
}

// ─── STEP 4〜11: 結果 ────────────────────────────────────────────────────

/** 原文ビュー。reqId の段落をハイライトし、段落クリックで actName(reqId) を発火 */
function docHtml(M: Model, reqId: string, actName: string): string {
  if (!M.doc.length) return `<div style="font-size:13px;color:var(--color-neutral-600)">原文の情報がありません。</div>`;
  const note = M.docFromQuotes ? `<div style="font-size:11.5px;color:var(--color-neutral-600)">このブラウザに仕様書の本文が保存されていないため、要件の引用文のみ表示しています。</div>` : "";
  return note + M.doc.map((p) => {
    if (p.heading && !p.reqs.length) return `<h4 style="margin:6px 0 0;font-size:19px">${esc(p.t)}</h4>`;
    const hl = p.reqs.includes(reqId);
    const r0 = hl ? reqId : p.reqs[0];
    return `<div ${r0 ? act(actName, r0) : ""} ${hl ? 'data-hl="1"' : ""} style="display:grid;grid-template-columns:56px 1fr;gap:10px;padding:8px 10px;font-size:14px;line-height:1.75;white-space:pre-wrap;background:${hl ? "var(--color-accent-200)" : "transparent"};cursor:${r0 ? "pointer" : "default"};outline:${hl ? "1px solid var(--color-accent)" : "none"}"><span style="font:600 12px/2.2 var(--font-heading);color:var(--color-accent-700);white-space:normal">${esc(p.reqs.slice(0, 2).join(" "))}</span><span>${esc(p.t)}</span></div>`;
  }).join("");
}

const confFg = (c: number) => (c < LOW_CONF ? WARN : "var(--color-text)");

function step4(M: Model): string {
  const v = state.variant[4];
  const cats = [...new Set(M.reqs.map((r) => r.cat))];
  const lowN = M.reqs.filter((r) => r.conf < LOW_CONF).length;
  const head = `<div style="display:flex;gap:10px;flex-wrap:wrap;align-items:center"><span class="tag tag-accent">要件 ${M.reqs.length}件</span><span class="tag tag-neutral">${cats.map((c) => `${esc(c)} ${M.reqs.filter((r) => r.cat === c).length}`).join(" · ")}</span>${lowN ? `<span class="tag" style="background:${WARN_BG};color:${WARN_FG}">要確認 ${lowN}件（信頼度${LOW_CONF}%未満）</span>` : ""}</div>`;
  if (!M.reqs.length) return head + empty("要件が抽出されませんでした", "仕様書の本文を見直して、もう一度分析してください。");
  const srcBtn = (r: VRequirement) => `<button class="btn btn-ghost" ${act("openSourceReq", r.id)} style="font-size:13px;white-space:nowrap">${esc(srcLabel(r.sec, r.page))} ↗</button>`;
  let body = "";
  if (v === 0) {
    body = `
    <table class="table">
      <thead><tr><th style="width:84px">ID</th><th>要件</th><th style="width:96px">区分</th><th style="width:70px">優先度</th><th style="width:170px">信頼度</th><th style="width:130px">出典</th></tr></thead>
      <tbody>
        ${M.reqs.map((r) => `<tr><td style="font:600 14px var(--font-heading);color:var(--color-accent-700)">${esc(r.id)}</td><td><div style="font-weight:500">${esc(r.title)}${r.inferred ? ` <span class="tag tag-neutral" style="font-size:10.5px">推定</span>` : ""}</div><div style="font-size:12px;color:var(--color-neutral-700)">${esc(r.detail)}</div></td><td><span class="tag tag-neutral">${esc(r.cat)}</span></td><td>${esc(r.pri)}</td><td><div style="display:flex;align-items:center;gap:8px"><div style="flex:1;height:4px;background:var(--color-neutral-200)"><div style="height:100%;width:${r.conf}%;background:${r.conf < LOW_CONF ? WARN : ACC}"></div></div><span style="font:600 14px var(--font-heading);width:34px;color:${confFg(r.conf)}">${r.conf}%</span></div></td><td>${srcBtn(r)}</td></tr>`).join("")}
      </tbody>
    </table>`;
  } else if (v === 1) {
    const sel = state.selReq && M.REQ[state.selReq] ? state.selReq : M.reqs[0].id;
    body = `
    <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(340px,1fr));gap:24px;align-items:start">
      <div class="blueprint" data-scroll="doc4" style="padding:28px 32px;max-height:640px;overflow:auto;display:flex;flex-direction:column;gap:12px">${CORNERS}
        <div style="font-size:10px;letter-spacing:.12em;color:var(--color-neutral-600)">原文 · ${esc(docName())}</div>
        ${docHtml(M, sel, "selReq")}
      </div>
      <div data-scroll="list4" style="display:flex;flex-direction:column;border-top:1px solid var(--color-divider);max-height:640px;overflow:auto">
        ${M.reqs.map((r) => `<div ${act("selReq", r.id)} style="display:grid;grid-template-columns:68px 1fr 48px;gap:10px;align-items:center;padding:10px 12px;border-bottom:1px solid var(--color-divider);cursor:pointer;background:${sel === r.id ? "var(--color-accent-100)" : "transparent"}"><span style="font:600 14px var(--font-heading);color:var(--color-accent-700)">${esc(r.id)}</span><div><div style="font-weight:500;font-size:14px">${esc(r.title)}</div><div style="font-size:12px;color:var(--color-neutral-700)">${esc([r.cat, r.sec, r.detail].filter(Boolean).join(" · "))}</div></div><span style="font:600 15px var(--font-heading);text-align:right;color:${confFg(r.conf)}">${r.conf}%</span></div>`).join("")}
      </div>
    </div>`;
  } else {
    body = `
    <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:24px;align-items:start">
      ${cats.map((c) => {
        const items = M.reqs.filter((r) => r.cat === c);
        return `
        <div style="display:flex;flex-direction:column;gap:14px">
          <div style="display:flex;align-items:baseline;gap:10px;border-bottom:2px solid var(--color-text);padding-bottom:6px"><h3 style="margin:0;font-size:24px">${esc(c)}</h3><span style="font:600 24px var(--font-heading);color:var(--color-accent)">${items.length}</span><span style="font-size:12px;color:var(--color-neutral-700)">${esc(CAT_NOTE[c] ?? "")}</span></div>
          ${items.map((r) => `
          <div class="card blueprint">${CORNERS}
            <div style="display:flex;justify-content:space-between;align-items:center"><span class="card-kicker">${esc(r.id)} · 優先度 ${esc(r.pri)}</span><span style="font:600 15px var(--font-heading);color:${confFg(r.conf)}">${r.conf}%</span></div>
            <div class="card-title">${esc(r.title)}</div>
            <p class="card-body">${esc(r.detail)}</p>
            <div class="card-meta"><span ${act("openSourceReq", r.id)} style="cursor:pointer">${esc(srcLabel(r.sec, r.page))} ↗</span><span style="flex:1"></span>${r.conf < LOW_CONF ? `<span style="color:oklch(0.5 0.168 25)">要確認</span>` : ""}</div>
          </div>`).join("")}
        </div>`;
      }).join("")}
    </div>`;
  }
  return head + body;
}

function step5(M: Model): string {
  const total = M.tasks.reduce((s, t) => s + t.h, 0);
  const unknownH = M.tasks.filter((t) => !t.hKnown).length;
  const groups = M.reqs.map((r) => ({ id: r.id, title: r.title, tasks: M.tasks.filter((t) => t.req === r.id) })).filter((g) => g.tasks.length);
  const orphan = M.tasks.filter((t) => !t.req || !M.REQ[t.req]);
  if (orphan.length) groups.push({ id: "—", title: "要件に紐づかないタスク", tasks: orphan });
  const review = M.tasks.filter((t) => t.needsReview).length;
  return `
  <div style="display:flex;gap:10px;flex-wrap:wrap"><span class="tag tag-accent">タスク ${M.tasks.length}件</span><span class="tag tag-neutral">見積り合計 ${fmtH(total)}</span>${unknownH ? `<span class="tag tag-neutral">見積りなし ${unknownH}件</span>` : ""}${review ? `<span class="tag" style="background:${WARN_BG};color:${WARN_FG}">要レビュー ${review}件</span>` : ""}</div>
  ${M.tasks.length ? "" : empty("タスクがありません", "要件からタスクが分解されませんでした。")}
  <div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(min(420px,100%),1fr));gap:24px 28px;align-items:start">
    ${groups.map(({ id, title, tasks }) => `
    <div style="display:flex;flex-direction:column">
      <div style="display:flex;align-items:baseline;gap:10px;padding-bottom:6px;border-bottom:2px solid var(--color-text)"><span style="font:600 15px var(--font-heading);color:var(--color-accent-700)">${esc(id)}</span><span style="flex:1;font-weight:500">${esc(title)}</span><span style="font-size:12px;color:var(--color-neutral-700);white-space:nowrap">${tasks.length}タスク · ${fmtH(tasks.reduce((s, t) => s + t.h, 0))}</span></div>
      ${tasks.map((t) => `<div style="display:grid;grid-template-columns:70px 1fr auto 44px;gap:10px;align-items:center;padding:9px 0;border-bottom:1px solid var(--color-divider);font-size:13.5px"><span style="font:600 13px var(--font-heading);color:var(--color-neutral-600)">${esc(t.id)}</span><div><div>${esc(t.title)}${t.needsReview ? ` <span style="font-size:11px;color:${WARN}">要レビュー</span>` : ""}</div><div style="font-size:11.5px;color:var(--color-neutral-600)">依存: ${esc(t.deps.length ? t.deps.join(", ") : "なし")}</div></div><span style="display:flex;gap:4px;flex-wrap:wrap;justify-content:flex-end">${skillTag(t)}</span><span style="font:600 15px var(--font-heading);text-align:right">${t.hKnown ? fmtH(t.h) : "—"}</span></div>`).join("")}
    </div>`).join("")}
  </div>`;
}

function step6(M: Model): string {
  const { depth, chain, total } = dependencyInfo(M);
  const crit = new Set(chain.length > 1 ? chain : []);
  const maxD = Math.max(0, ...Object.values(depth));
  const cols = Array.from({ length: maxD + 1 }, (_, d) => ({ d, items: M.tasks.filter((t) => (depth[t.id] ?? 0) === d) })).filter((c) => c.items.length);
  const card = (t: VTask) => `
      <div class="blueprint" style="padding:10px 12px;display:flex;flex-direction:column;gap:4px;border:${crit.has(t.id) ? "2px solid var(--color-accent)" : "1px solid var(--color-divider)"}">${CORNERS}
        <div style="display:flex;justify-content:space-between"><span style="font:600 13px var(--font-heading);color:var(--color-accent-700)">${esc(t.id)}</span><span style="font:600 13px var(--font-heading)">${t.hKnown ? fmtH(t.h) : "—"}</span></div>
        <div style="font-size:13.5px;font-weight:500">${esc(t.title)}</div>
        <div style="font-size:11.5px;color:var(--color-neutral-700)">← ${esc(t.deps.length ? t.deps.join(", ") : "依存なし")}</div>
      </div>`;
  const head = crit.size
    ? `<div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap"><span style="font-size:12px;color:var(--color-neutral-700)">クリティカルパス</span>
    ${chain.map((id, i) => `<span style="display:flex;align-items:center;gap:8px"><span class="tag" style="background:var(--color-accent-800);color:#fff">${esc(id)} ${esc(M.TK[id]?.title ?? "")}</span><span style="color:var(--color-neutral-500)">${i < chain.length - 1 ? "→" : "="}</span></span>`).join("")}
    <span style="font:600 18px var(--font-heading)">${fmtH(total)}</span></div>`
    : `<div style="font-size:13px;color:var(--color-neutral-700)">タスク間の依存関係は検出されませんでした。すべてのタスクに並行して着手できます。</div>`;
  if (cols.length <= 1) {
    return head + `<div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(240px,1fr));gap:12px">${M.tasks.map(card).join("")}</div>`;
  }
  return head + `
  <div style="display:grid;grid-template-columns:repeat(${cols.length},minmax(220px,1fr));gap:0;overflow-x:auto;border-top:1px solid var(--color-divider)">
    ${cols.map(({ d, items }) => `
    <div style="display:flex;flex-direction:column;gap:12px;padding:16px;border-right:1px solid var(--color-divider)">
      <div style="display:flex;flex-direction:column"><span style="font:600 20px var(--font-heading)">レベル ${d + 1}</span><span style="font-size:11.5px;color:var(--color-neutral-700)">${d === 0 ? "すぐ着手可能" : `レベル${d}の完了後`} · ${items.length}件</span></div>
      ${items.map(card).join("")}
    </div>`).join("")}
  </div>`;
}

const RAMP = ["transparent", "var(--color-accent-100)", "var(--color-accent-200)", "var(--color-accent-300)", "var(--color-accent-500)", "var(--color-accent-700)"];

function step7(M: Model): string {
  const a = state.assign;
  if (!M.members.length) return empty("メンバーがいません", "STEP 2 でチームメンバーを登録してから分析してください。");
  const mv = memberViews(M, a);
  const v = state.variant[7];
  const capLine = (top: number) => `<div style="position:absolute;top:-${top}px;bottom:-${top}px;left:80%;width:1px;background:var(--color-text)"></div>`;
  const sortedSkills = (m: VMember) => Object.keys(m.sk).sort((x, y) => m.sk[y] - m.sk[x]);
  const legend = `<div style="display:flex;gap:18px;padding:12px 8px;border-top:1px solid var(--color-divider);font-size:11.5px;color:var(--color-neutral-700);flex-wrap:wrap"><span>数字 = スキルレベル（1〜5）</span><span style="display:flex;align-items:center;gap:6px"><i style="width:12px;height:8px;background:var(--color-neutral-300)"></i>既存業務</span><span style="display:flex;align-items:center;gap:6px"><i style="width:12px;height:8px;background:var(--color-accent)"></i>今回の割当</span><span>縦線 = 稼働上限（週あたり稼働可能時間）</span></div>`;

  if (v === 0) {
    const sk = M.skillCols;
    const cols = `170px repeat(${Math.max(1, sk.length)},minmax(56px,1fr)) minmax(240px,1.6fr)`;
    const minW = 170 + Math.max(1, sk.length) * 60 + 260;
    return `
    <div style="display:flex;flex-direction:column;border-top:1px solid var(--color-divider);overflow-x:auto">
      <div style="display:grid;grid-template-columns:${cols};min-width:${minW}px">
        <div style="padding:10px 8px;font-size:11px;letter-spacing:.08em;color:var(--color-neutral-700)">メンバー</div>
        ${sk.length ? sk.map((k) => `<div style="padding:10px 4px;font-size:11px;text-align:center;color:var(--color-neutral-700);overflow:hidden;text-overflow:ellipsis;white-space:nowrap" title="${esc(M.skillLabel[k])}">${esc(M.skillLabel[k])}</div>`).join("") : `<div style="padding:10px 4px;font-size:11px;color:var(--color-neutral-600)">スキル未登録</div>`}
        <div style="padding:10px 8px;font-size:11px;color:var(--color-neutral-700)">負荷（既存 + 今回割当）</div>
      </div>
      ${mv.map((m) => `
      <div style="display:grid;grid-template-columns:${cols};min-width:${minW}px;border-top:1px solid var(--color-divider);align-items:stretch">
        <div style="padding:10px 8px;display:flex;flex-direction:column;justify-content:center"><span style="font-weight:500">${esc(m.name)}</span><span style="font-size:11.5px;color:var(--color-neutral-700)">${esc(m.role)}</span></div>
        ${sk.length ? sk.map((k) => {
          const lv = M.MEM[m.id].sk[k] || 0;
          return `<div style="margin:3px;display:grid;place-items:center;font:600 18px var(--font-heading);background:${RAMP[Math.min(5, lv)]};color:${lv >= 4 ? "#fff" : lv ? "var(--color-accent-900)" : "var(--color-neutral-400)"}">${lv || "·"}</div>`;
        }).join("") : "<div></div>"}
        <div style="padding:10px 8px;display:flex;align-items:center;gap:10px"><div style="flex:1;height:14px;position:relative;border:1px solid var(--color-divider)"><div style="position:absolute;top:0;bottom:0;left:0;width:${m.baseW};background:var(--color-neutral-300)"></div><div style="position:absolute;top:0;bottom:0;left:${m.baseW};width:${m.newW};background:${m.barBg}"></div>${capLine(4)}</div><span style="font:600 17px var(--font-heading);width:52px;text-align:right;color:${m.pctFg}">${m.pct}%</span></div>
      </div>`).join("")}
      ${legend}
    </div>`;
  }

  if (v === 1) {
    return `
    <div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:24px">
      ${mv.map((m) => {
        const mm = M.MEM[m.id];
        return `
      <div class="card blueprint" style="gap:12px;padding:16px">${CORNERS}
        <div style="display:flex;align-items:center;gap:10px"><span style="width:36px;height:36px;display:grid;place-items:center;border:1px solid var(--color-divider);font-size:15px">${esc(m.ini)}</span><div style="flex:1;min-width:0"><div class="card-title">${esc(m.name)}</div><div style="font-size:12px;color:var(--color-neutral-700)">${esc(m.role)}</div></div><span class="tag" style="background:${m.stBg};color:${m.stFg}">${m.status}</span></div>
        <div style="display:flex;align-items:flex-end;gap:6px"><span style="font:600 52px/0.9 var(--font-heading);color:${m.pctFg}">${m.pct}</span><span style="font:600 20px var(--font-heading);color:var(--color-neutral-600)">%</span><span style="flex:1"></span><span style="font-size:12px;color:var(--color-neutral-700)">${m.hTxt}</span></div>
        <div style="height:6px;position:relative;background:var(--color-neutral-200)"><div style="position:absolute;top:0;bottom:0;left:0;width:${m.baseW};background:var(--color-neutral-400)"></div><div style="position:absolute;top:0;bottom:0;left:${m.baseW};width:${m.newW};background:${m.barBg}"></div>${capLine(3)}</div>
        <div style="display:flex;flex-direction:column;gap:4px">
          ${sortedSkills(mm).map((k) => { const lv = Math.min(5, mm.sk[k]); return `<div style="display:flex;justify-content:space-between;font-size:12.5px"><span>${esc(mm.skName[k])}</span><span style="letter-spacing:2px;color:var(--color-accent)">${"●".repeat(lv)}${"○".repeat(5 - lv)}</span></div>`; }).join("") || `<span style="font-size:12px;color:var(--color-neutral-600)">スキル未登録</span>`}
        </div>
        <div class="card-meta" style="flex-wrap:wrap;gap:4px">今回: ${m.mine.slice(0, 12).map((t) => `<span class="tag tag-neutral">${esc(t.id)}</span>`).join("")}${m.mine.length > 12 ? `<span>ほか${m.mine.length - 12}件</span>` : ""}${m.mine.length ? "" : "<span>なし</span>"}</div>
      </div>`;
      }).join("")}
    </div>`;
  }

  return `
  <div style="display:flex;flex-direction:column;gap:6px">
    <div style="display:grid;grid-template-columns:160px 1fr 60px;gap:14px;font-size:11px;color:var(--color-neutral-700)"><span></span><div style="position:relative;height:16px"><span style="position:absolute;left:0">0%</span><span style="position:absolute;left:40%;transform:translateX(-50%)">50%</span><span style="position:absolute;left:80%;transform:translateX(-50%);color:var(--color-text);font-weight:500">上限 100%</span></div><span></span></div>
    ${mv.map((m) => {
      const mm = M.MEM[m.id];
      const cap = mm.cap || 1;
      const segs = [{ w: W(m.bp), bg: "var(--color-neutral-300)", fg: "var(--color-neutral-800)", label: "既存", tip: `既存業務 ${fmtH(mm.base)}` }].concat(
        m.mine.map((t, i) => ({
          w: W((t.h / cap) * 100),
          bg: m.over ? (i % 2 ? WARN : "oklch(0.62 0.156 25)") : i % 2 ? "var(--color-accent-700)" : ACC,
          fg: "#fff", label: t.id, tip: `${t.id} ${t.title} ${fmtH(t.h)}`,
        })),
      );
      const top = sortedSkills(mm).slice(0, 2).map((k) => `${mm.skName[k]} ${mm.sk[k]}`).join(" · ");
      return `
      <div style="display:grid;grid-template-columns:160px 1fr 60px;gap:14px;align-items:center;padding:8px 0;border-top:1px solid var(--color-divider)">
        <div style="display:flex;flex-direction:column"><span style="font-weight:500">${esc(m.name)}</span><span style="font-size:11.5px;color:var(--color-neutral-700)">${esc(top || "スキル未登録")}</span></div>
        <div style="position:relative;height:34px;display:flex;overflow:hidden">${segs.map((sg) => `<div title="${esc(sg.tip)}" style="width:${sg.w};flex:none;height:100%;background:${sg.bg};color:${sg.fg};border-right:1px solid var(--color-bg);display:flex;align-items:center;padding:0 6px;font:600 12px var(--font-heading);overflow:hidden;white-space:nowrap">${esc(sg.label)}</div>`).join("")}<div style="position:absolute;top:0;bottom:0;left:80%;width:1px;background:var(--color-text)"></div></div>
        <span style="font:600 20px var(--font-heading);text-align:right;color:${m.pctFg}">${m.pct}%</span>
      </div>`;
    }).join("")}
  </div>`;
}

function step8(M: Model): string {
  const a = state.assign;
  const v = state.variant[8];
  const rows = M.tasks.map((t) => taskRow(M, t, a));
  const un = rows.filter((r) => !r.assigned);
  const changed = M.tasks.filter((t) => a[t.id] !== M.aiAssign[t.id]).length;
  const head = `<div style="display:flex;gap:10px;flex-wrap:wrap;align-items:center"><span class="tag tag-accent">割当済 ${M.tasks.length - un.length} / ${M.tasks.length}</span>${un.length ? `<span class="tag" style="background:${WARN_BG};color:${WARN_FG}">未割当 ${un.length}</span>` : ""}${changed ? `<span class="tag tag-neutral">手動変更 ${changed}件</span><button class="btn btn-ghost" ${act("resetAssign")} style="font-size:12px;padding:2px 8px">AIの割当に戻す</button>` : ""}<span style="font-size:12.5px;color:var(--color-neutral-700)">適合度 = スキル一致（最大${SKILL_MAX}） + 負荷の余裕（最大${LOAD_MAX}）</span></div>`;
  if (!M.tasks.length) return head + empty("タスクがありません", "割り当てるタスクがありません。");

  if (v === 0) {
    return head + `
    <table class="table">
      <thead><tr><th style="width:84px">ID</th><th>タスク</th><th style="width:150px">必要スキル</th><th style="width:170px">担当</th><th style="width:150px">適合度</th><th>根拠</th></tr></thead>
      <tbody>
        ${rows.map((r) => `<tr style="background:${r.assigned ? "transparent" : WARN_BG}"><td style="font:600 13px var(--font-heading);color:var(--color-accent-700)">${esc(r.t.id)}</td><td><div style="font-weight:500">${esc(r.t.title)}</div><div style="font-size:11.5px;color:var(--color-neutral-600)">${esc(r.t.req ?? "—")} · ${r.t.hKnown ? fmtH(r.t.h) : "見積りなし"}</div></td><td><span style="display:flex;gap:4px;flex-wrap:wrap">${skillTag(r.t)}</span></td><td><select class="input" data-assign="${esc(r.t.id)}" style="min-height:30px;padding:3px 6px;font-size:13px;font-weight:500;color:${r.whoFg}"><option value="">未割当</option>${M.members.map((m) => `<option value="${esc(m.id)}" ${a[r.t.id] === m.id ? "selected" : ""}>${esc(m.name)}</option>`).join("")}</select></td><td><div style="display:flex;align-items:center;gap:8px"><div style="flex:1;height:4px;background:var(--color-neutral-200)"><div style="height:100%;width:${r.assigned ? r.score : 0}%;background:var(--color-accent)"></div></div><span style="font:600 15px var(--font-heading);width:24px">${r.score}</span></div></td><td style="font-size:12.5px;color:var(--color-neutral-800)">${esc(r.reason)}</td></tr>`).join("")}
      </tbody>
    </table>`;
  }

  if (v === 1) {
    const mv = memberViews(M, a);
    const card = (r: TaskRow) => `<div ${act("selTask8", r.t.id)} style="padding:8px 10px;border:1px solid var(--color-divider);background:var(--color-bg);display:flex;flex-direction:column;gap:3px;cursor:pointer"><div style="display:flex;justify-content:space-between"><span style="font:600 12px var(--font-heading);color:var(--color-accent-700)">${esc(r.t.id)}</span><span style="font:600 12px var(--font-heading)">${r.t.hKnown ? fmtH(r.t.h) : "—"}</span></div><div style="font-size:12.5px;font-weight:500">${esc(r.t.title)}</div><div style="font-size:11px;color:var(--color-neutral-600)">${esc(r.t.skills.slice(0, 2).join(" · ") || "スキル指定なし")} · 適合 ${r.score}</div></div>`;
    const lane = (ini: string, name: string, pctTxt: string, pctFg: string, barW: string, barBg: string, bg: string, tasks: TaskRow[]) => `
      <div style="display:flex;flex-direction:column;gap:8px;padding:10px;border:1px solid var(--color-divider);background:${bg};min-height:420px;max-height:760px;overflow:auto">
        <div style="display:flex;align-items:center;gap:8px"><span style="width:26px;height:26px;display:grid;place-items:center;border:1px solid var(--color-divider);font-size:12px">${esc(ini)}</span><span style="flex:1;font-weight:500;font-size:13.5px">${esc(name)}</span><span style="font:600 16px var(--font-heading);color:${pctFg}">${pctTxt}</span></div>
        <div style="height:4px;background:var(--color-neutral-200);position:relative"><div style="position:absolute;inset:0 auto 0 0;width:${barW};background:${barBg}"></div></div>
        ${tasks.map(card).join("")}
      </div>`;
    return head + `
    <div style="display:grid;grid-template-columns:repeat(${mv.length + 1},minmax(190px,1fr));gap:12px;overflow-x:auto;padding-bottom:8px">
      ${mv.map((m) => lane(m.ini, m.name, m.pct + "%", m.pctFg, Math.min(100, m.pct) + "%", m.barBg, "transparent", rows.filter((r) => a[r.t.id] === m.id))).join("")}
      ${lane("?", "未割当", un.length + "件", WARN, "0%", WARN, WARN_BG, un)}
    </div>`;
  }

  const tSel = M.TK[state.selTask] || M.tasks[0];
  const sel = taskRow(M, tSel, a);
  const rec = M.rec[tSel.id];
  const cands = M.members.map((m) => ({ m, s: scoreOf(M, m, tSel, a), ai: aiScoreOf(M, tSel.id, m.id), rej: rejectedReasons(M, tSel.id, m.id), chosen: a[tSel.id] === m.id }))
    .sort((x, y) => x.s.missing.length - y.s.missing.length || y.s.total - x.s.total);
  const cols = "minmax(96px,1.3fr) minmax(36px,1fr) minmax(36px,1fr) 48px 36px 40px 92px";
  return head + `
  <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:28px;align-items:start">
    <div data-scroll="list8" style="display:flex;flex-direction:column;border-top:1px solid var(--color-divider);max-height:680px;overflow:auto">
      ${rows.map((r) => `<div ${act("selTask", r.t.id)} style="display:grid;grid-template-columns:66px 1fr auto;gap:8px;align-items:center;padding:8px 10px;border-bottom:1px solid var(--color-divider);cursor:pointer;background:${tSel.id === r.t.id ? "var(--color-accent-100)" : "transparent"}"><span style="font:600 12.5px var(--font-heading);color:var(--color-accent-700)">${esc(r.t.id)}</span><span style="font-size:13px">${esc(r.t.title)}</span><span style="font-size:12px;color:${r.whoFg}">${esc(r.whoShort)}</span></div>`).join("")}
    </div>
    <div class="blueprint" style="padding:20px 22px;display:flex;flex-direction:column;gap:16px;overflow-x:auto">${CORNERS}
      <div style="display:flex;flex-direction:column;gap:4px"><span style="font-size:11px;letter-spacing:.1em;color:var(--color-accent-700)">${esc(tSel.id)} · ${esc(tSel.req ?? "—")} · ${tSel.hKnown ? fmtH(tSel.h) : "見積りなし"}</span><h2 style="margin:0;font-size:28px">${esc(tSel.title)}</h2><span style="font-size:13px;color:var(--color-neutral-700)">必要スキル: ${esc(tSel.skills.join("・") || "指定なし")} · 依存: ${esc(sel.deps)}</span></div>
      <div style="display:grid;grid-template-columns:${cols};gap:10px;font-size:11px;color:var(--color-neutral-700);border-bottom:1px solid var(--color-divider);padding-bottom:6px"><span>候補</span><span>スキル一致</span><span>負荷の余裕</span><span>割当後</span><span>適合</span><span title="バックエンドが算出したスコア">AI</span><span></span></div>
      ${cands.map(({ m, s, ai, rej, chosen }) => `
      <div style="display:grid;grid-template-columns:${cols};gap:10px;align-items:center;padding:4px 0;background:${chosen ? "var(--color-accent-100)" : "transparent"}" title="${esc(rej.join(" / "))}">
        <div style="display:flex;flex-direction:column;padding-left:6px;min-width:0"><span style="font-weight:500;font-size:13.5px">${esc(m.name)}</span><span style="font-size:11px;color:${s.missing.length ? WARN : "var(--color-neutral-600)"};overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${esc(s.missing.length ? `${s.missing.join("・")} 未保有` : skillSummary(m, tSel))}</span></div>
        <div style="height:8px;background:var(--color-neutral-200)"><div style="height:100%;width:${(s.skill / SKILL_MAX) * 100}%;background:var(--color-accent-700)"></div></div>
        <div style="height:8px;background:var(--color-neutral-200)"><div style="height:100%;width:${(s.load / LOAD_MAX) * 100}%;background:var(--color-accent-400)"></div></div>
        <span style="font:600 15px var(--font-heading);color:${s.after > 100 ? WARN : "var(--color-text)"}">${s.after}%</span>
        <span style="font:600 20px var(--font-heading)">${s.total}</span>
        <span style="font:600 14px var(--font-heading);color:var(--color-neutral-700)">${ai ?? (rej.length ? "除外" : "—")}</span>
        ${chosen
          ? `<span class="tag tag-accent" style="justify-self:start">現在の担当</span>`
          : `<button class="btn btn-secondary" ${act("assign", tSel.id, m.id)} style="font-size:12px;padding:4px 8px;justify-self:start;white-space:nowrap">この人にする</button>`}
      </div>`).join("")}
      ${a[tSel.id] ? `<div><button class="btn btn-ghost" ${act("assign", tSel.id, "")} style="font-size:12.5px">担当を外す</button></div>` : ""}
      <div style="font-size:12.5px;color:var(--color-neutral-700);border-top:1px solid var(--color-divider);padding-top:10px;display:flex;flex-direction:column;gap:4px">
        <span>${esc(sel.reason)}</span>
        ${rec?.reasons?.length ? `<span style="font-size:11px;letter-spacing:.1em;color:var(--color-neutral-600);margin-top:4px">AIの割当根拠</span>${rec.reasons.map((x) => `<span>・${esc(x)}</span>`).join("")}` : ""}
        ${rec?.warnings?.length ? rec.warnings.map((x) => `<span style="color:${WARN_FG}">・${esc(x)}</span>`).join("") : ""}
      </div>
    </div>
  </div>`;
}

function step9(M: Model): string {
  const all = buildWarnings(M, state.assign);
  if (!all.length) {
    return `<div class="blueprint" style="padding:28px;display:flex;align-items:center;gap:16px">${CORNERS}<span style="font:600 40px var(--font-heading);color:var(--color-accent)">✓</span><div><h3 style="margin:0;font-size:24px">要対応の項目はありません</h3><div style="font-size:13px;color:var(--color-neutral-700)">すべてのタスクが割り当てられ、負荷・スキルの条件を満たしています。</div></div></div>`;
  }
  const { shown, hidden } = limitWarnings(all);
  const hiddenNote = Object.keys(hidden).length
    ? `<div style="font-size:12.5px;color:var(--color-neutral-700)">表示を種類ごとに${WARN_LIMIT}件までに絞っています（${Object.entries(hidden).map(([k, n]) => `${esc(k)} ほか${n}件`).join(" · ")}）。対応すると次の項目が表示されます。</div>`
    : "";
  const subFont = "font:400 11px 'Barlow','Noto Sans JP',sans-serif;color:var(--color-neutral-600)";

  if (state.variant[9] === 0) {
    return `
    <div style="display:flex;flex-direction:column;border-top:1px solid var(--color-divider)">
      ${shown.map((w) => `
      <div style="display:grid;grid-template-columns:110px minmax(0,1fr) auto;gap:18px;align-items:center;padding:14px 4px;border-bottom:1px solid var(--color-divider)">
        <span class="tag" style="justify-self:start;background:${w.bg};color:${w.fg}">${esc(w.kind)}</span>
        <div><div style="font-weight:500">${esc(w.title)}</div><div style="font-size:12.5px;color:var(--color-neutral-700)">${esc(w.detail)}</div></div>
        <div style="display:flex;gap:8px;flex-wrap:wrap;justify-content:flex-end">
          ${w.actions.map((x) => `<button class="btn btn-secondary" ${x.attrs} style="flex-direction:column;align-items:flex-start;gap:0;padding:6px 12px"><span style="font-size:13px">${esc(x.label)}</span><span style="${subFont}">${esc(x.sub)}</span></button>`).join("")}
        </div>
      </div>`).join("")}
    </div>${hiddenNote}`;
  }

  const kinds = WARN_KINDS.filter(([k]) => all.some((w) => w.kind === k));
  return `
  <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:18px">
    ${kinds.map(([k, sev]) => `<div class="blueprint" style="padding:16px 18px;display:flex;flex-direction:column;gap:2px">${CORNERS}<span style="font-size:12px;color:var(--color-neutral-700)">${esc(k)}</span><span style="font:600 56px/1 var(--font-heading);color:${sev === 0 ? WARN : sev === 1 ? "var(--color-accent-700)" : "var(--color-neutral-700)"}">${all.filter((w) => w.kind === k).length}</span></div>`).join("")}
  </div>
  <div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(320px,1fr));gap:22px">
    ${shown.map((w) => `
    <div class="card blueprint" style="gap:10px;padding:16px">${CORNERS}
      <div style="height:3px;margin:-16px -16px 6px;background:${w.fg}"></div>
      <span class="card-kicker" style="color:${w.fg}">${esc(w.kind)}</span>
      <div class="card-title">${esc(w.title)}</div>
      <p class="card-body">${esc(w.detail)}</p>
      <div style="display:flex;flex-direction:column;gap:6px">
        ${w.actions.map((x) => `<button class="btn btn-secondary" ${x.attrs} style="justify-content:space-between;width:100%;gap:10px"><span>${esc(x.label)}</span><span style="${subFont}">${esc(x.sub)}</span></button>`).join("")}
      </div>
    </div>`).join("")}
  </div>${hiddenNote}`;
}

function step10(M: Model): string {
  if (!M.tasks.length) return empty("タスクがありません", "出典を表示するタスクがありません。");
  const a = state.assign;
  const tSel = M.TK[state.selTask] || M.tasks[0];
  const r = tSel.req ? M.REQ[tSel.req] : undefined;
  const quote = tSel.srcText || r?.srcText || "";
  const mid = a[tSel.id];
  const conf = r?.conf ?? tSel.conf;
  const low = conf < LOW_CONF || tSel.needsReview;
  const note = tSel.needsReview && tSel.reviewReasons.length
    ? tSel.reviewReasons.join(" / ")
    : "記述が抽象的なため、実装範囲・数値目標などを顧客に確認することを推奨します。";
  return `
  <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:24px;align-items:start">
    <div data-scroll="list10" style="display:flex;flex-direction:column;border-top:1px solid var(--color-divider);max-height:680px;overflow:auto">
      ${M.tasks.map((t) => `<div ${act("selTask", t.id)} style="display:grid;grid-template-columns:66px 1fr;gap:6px;padding:8px 10px;border-bottom:1px solid var(--color-divider);cursor:pointer;background:${tSel.id === t.id ? "var(--color-accent-100)" : "transparent"}"><span style="font:600 12.5px var(--font-heading);color:var(--color-accent-700)">${esc(t.id)}</span><span style="font-size:12.5px">${esc(t.title)}</span></div>`).join("")}
    </div>
    <div class="blueprint" data-scroll="doc10" style="padding:28px 32px;display:flex;flex-direction:column;gap:12px;max-height:680px;overflow:auto">${CORNERS}
      <div style="font-size:10px;letter-spacing:.12em;color:var(--color-neutral-600)">原文 · ${esc(docName())}</div>
      ${docHtml(M, tSel.req ?? "", "selTaskByReq")}
    </div>
    <div style="display:flex;flex-direction:column;gap:14px">
      <div style="font-size:10px;letter-spacing:.12em;color:var(--color-neutral-600)">抽出の根拠</div>
      <div style="display:flex;flex-direction:column;gap:2px"><span style="font:600 14px var(--font-heading);color:var(--color-accent-700)">${esc(tSel.id)}</span><h3 style="margin:0;font-size:22px">${esc(tSel.title)}</h3></div>
      ${tSel.desc ? `<div style="font-size:13px;color:var(--color-neutral-800)">${esc(tSel.desc)}</div>` : ""}
      ${quote ? `<div style="padding:12px 14px;background:var(--color-accent-100);font-size:13.5px;line-height:1.7">「${esc(quote)}」</div>` : `<div style="font-size:12.5px;color:var(--color-neutral-600)">原文の引用はありません。</div>`}
      <div style="display:grid;grid-template-columns:80px 1fr;gap:6px 10px;font-size:13px">
        <span style="color:var(--color-neutral-700)">出典</span><span>${esc(srcLabel(tSel.sec || r?.sec || "", tSel.page ?? r?.page ?? null))}</span>
        <span style="color:var(--color-neutral-700)">要件</span><span>${r ? `${esc(r.id)} ${esc(r.title)}` : esc(tSel.reqIds.join(", ") || "—")}</span>
        <span style="color:var(--color-neutral-700)">信頼度</span><span style="color:${confFg(conf)};font-weight:500">${conf}%</span>
        <span style="color:var(--color-neutral-700)">同要件</span><span>${esc(M.tasks.filter((x) => x.req && x.req === tSel.req).map((x) => x.id).join(" · ") || "—")}</span>
        <span style="color:var(--color-neutral-700)">担当</span><span>${mid && M.MEM[mid] ? esc(M.MEM[mid].name) : "未割当"}</span>
        ${tSel.acceptance.length ? `<span style="color:var(--color-neutral-700)">完了条件</span><span>${tSel.acceptance.map((x) => esc(x)).join("<br>")}</span>` : ""}
      </div>
      ${low ? `<div style="padding:10px 12px;border:1px solid oklch(0.75 0.120 25);font-size:12.5px;color:oklch(0.42 0.156 25)">${esc(note)}</div>` : ""}
    </div>
  </div>`;
}

function step11(M: Model): string {
  const a = state.assign;
  return `
  <div style="display:flex;gap:10px;align-items:center;flex-wrap:wrap;font-size:12.5px;color:var(--color-neutral-700)"><span>ステータスはこのブラウザに保存されます（バックエンドに保存APIが無いため）。</span><span style="flex:1"></span><button class="btn btn-secondary" ${act("exportJson")} style="font-size:12.5px;padding:4px 10px">JSONをダウンロード</button></div>
  <div style="display:grid;grid-template-columns:repeat(4,minmax(220px,1fr));gap:14px;overflow-x:auto">
    ${KANBAN_COLS.map((c, ci) => {
      const cards = M.tasks.filter((t) => (state.kb[t.id] ?? "未着手") === c);
      return `
      <div class="s2t-kb-col" data-col="${c}" style="display:flex;flex-direction:column;gap:8px;padding:10px;min-height:520px;border:1px solid var(--color-divider);background:transparent">
        <div style="display:flex;align-items:baseline;gap:8px;padding:2px 2px 6px;border-bottom:2px solid var(--color-text)"><span style="font:600 20px var(--font-heading)">${c}</span><span style="font:600 16px var(--font-heading);color:var(--color-accent)">${cards.length}</span></div>
        ${cards.map((t) => {
          const mid = a[t.id];
          const m = mid ? M.MEM[mid] : undefined;
          const whoFg = m ? "var(--color-text)" : WARN;
          return `
          <div draggable="true" data-task="${esc(t.id)}" class="blueprint s2t-kb-card" style="padding:10px 12px;display:flex;flex-direction:column;gap:6px;background:var(--color-bg);cursor:grab">${CORNERS}
            <div style="display:flex;justify-content:space-between;align-items:center"><span style="font:600 12.5px var(--font-heading);color:var(--color-accent-700)">${esc(t.id)}${t.req ? ` · ${esc(t.req)}` : ""}</span><span style="font:600 12.5px var(--font-heading)">${t.hKnown ? fmtH(t.h) : "—"}</span></div>
            <div style="font-size:13.5px;font-weight:500">${esc(t.title)}</div>
            <div style="display:flex;align-items:center;gap:6px"><span style="width:22px;height:22px;display:grid;place-items:center;border:1px solid var(--color-divider);font-size:11px;color:${whoFg}">${m ? esc(m.ini) : "?"}</span><span style="font-size:12px;color:${whoFg}">${m ? esc(m.name) : "未割当"}</span><span style="flex:1"></span><button class="btn btn-ghost" ${act("openSource", t.id)} style="font-size:11.5px;padding:2px 4px">出典</button>${ci < 3 ? `<button class="btn btn-ghost" ${act("kbMove", t.id, KANBAN_COLS[ci + 1])} style="font-size:12px;padding:2px 6px">→</button>` : ""}</div>
          </div>`;
        }).join("")}
      </div>`;
    }).join("")}
  </div>`;
}

const RESULT_RENDERERS = [step4, step5, step6, step7, step8, step9, step10, step11];

function stepBody(): string {
  if (state.step === 1) return step1();
  if (state.step === 2) return step2();
  if (state.step === 3) return step3();
  const M = state.model;
  if (!M) {
    return empty(
      state.loadingResult ? "分析結果を読み込んでいます…" : "分析結果がありません",
      "STEP 1 で仕様書を入力し、AI分析を実行すると結果が表示されます。",
      state.loadingResult ? "" : `<button class="btn btn-secondary" ${act("go", 1)}>STEP 1 へ</button>`,
    );
  }
  return RESULT_RENDERERS[state.step - 4](M);
}

// ─── 描画 ────────────────────────────────────────────────────────────────

function sidebarFooter(): string {
  const M = state.model;
  const members = M ? M.members.map((m) => ({ name: m.name, ini: m.ini })) : state.members.filter((m) => m.name.trim()).map((m) => ({ name: m.name, ini: Array.from(m.name.trim())[0] ?? "?" }));
  return `
  <div style="margin-top:auto;padding:12px 10px;border-top:1px solid var(--color-divider);display:flex;flex-direction:column;gap:8px">
    <div style="font-size:10px;letter-spacing:.12em;color:var(--color-neutral-600)">プロジェクト</div>
    <div style="font:600 16px var(--font-heading)">${esc(M?.name || state.projectName || "未作成")}</div>
    <div style="display:flex;gap:4px;flex-wrap:wrap">${members.slice(0, 10).map((m) => `<span title="${esc(m.name)}" style="width:22px;height:22px;display:grid;place-items:center;font-size:11px;border:1px solid var(--color-divider)">${esc(m.ini)}</span>`).join("")}${members.length > 10 ? `<span style="font-size:11px;color:var(--color-neutral-600)">+${members.length - 10}</span>` : ""}</div>
    ${M || state.jobId ? `<button class="btn btn-secondary" ${act("newSpec")} style="font-size:12px;padding:5px 8px">＋ 新しい仕様書で分析</button>` : ""}
    <div style="border-top:1px solid var(--color-divider);margin-top:4px;padding-top:8px;display:flex;flex-direction:column;gap:6px">
      ${userLabel ? `<div style="font-size:11.5px;color:var(--color-neutral-700)">${esc(userLabel)}</div>` : ""}
      <div style="display:flex;gap:6px;flex-wrap:wrap">
        ${!state.demo ? `<button class="btn btn-ghost" ${act("team")} style="font-size:12px;padding:3px 6px">チームメンバー</button>` : ""}
        <a class="btn btn-ghost" href="./legacy.html" style="font-size:12px;padding:3px 6px">旧画面</a>
      </div>
    </div>
  </div>`;
}

function render(): void {
  // 再描画で内部スクロール位置・入力フォーカスが失われないよう退避・復元する
  const scrolls: Record<string, number> = {};
  root.querySelectorAll<HTMLElement>("[data-scroll]").forEach((el) => (scrolls[el.dataset.scroll!] = el.scrollTop));
  const active = document.activeElement as HTMLInputElement | null;
  const focusKey = active && root.contains(active) ? (active.id || (active.dataset.mi != null ? `m${active.dataset.mi}-${active.dataset.mf}` : "")) : "";
  const caret = focusKey && typeof active!.selectionStart === "number" ? [active!.selectionStart, active!.selectionEnd] : null;

  root.innerHTML = `
  <div style="display:flex;min-height:100vh;color:var(--color-text)">
    <aside style="width:232px;flex:none;border-right:1px solid var(--color-divider);padding:18px 12px;display:flex;flex-direction:column;gap:20px;position:sticky;top:0;height:100vh;overflow:auto">
      <div style="display:flex;align-items:center;gap:10px;padding:0 8px">
        <div class="blueprint" style="width:28px;height:28px;display:grid;place-items:center;font:600 13px var(--font-heading);background:var(--color-accent-800);color:#fff;border-color:var(--color-accent)">タ</div>
        <div style="display:flex;flex-direction:column;line-height:1.1"><span style="font:600 18px var(--font-heading)">タスみる</span><span style="font-size:10.5px;color:var(--color-neutral-600)">仕様書 → タスク自動割当</span></div>
      </div>
      ${railHtml()}
      ${sidebarFooter()}
    </aside>
    <main style="flex:1;min-width:0;display:flex;flex-direction:column">
      ${headerHtml()}
      <div style="padding:28px;display:flex;flex-direction:column;gap:24px">
        ${stepBody()}
      </div>
    </main>
  </div>
  <input type="file" id="s2t-file" accept=".txt,.md,.markdown,.csv,.tsv,.json,.html,.htm,.xml,.yaml,.yml,.pdf,.doc,.docx,text/*" style="display:none">`;

  root.querySelectorAll<HTMLElement>("[data-scroll]").forEach((el) => {
    const top = scrolls[el.dataset.scroll!];
    if (top != null) el.scrollTop = top;
  });
  if (focusKey) {
    const el = (document.getElementById(focusKey) ||
      root.querySelector(`[data-mi="${focusKey.slice(1).split("-")[0]}"][data-mf="${focusKey.split("-")[1]}"]`)) as HTMLInputElement | null;
    if (el) {
      el.focus();
      if (caret) try { el.setSelectionRange(caret[0], caret[1]); } catch { /* number入力等 */ }
    }
  }
}

// ─── ファイル読み込み ────────────────────────────────────────────────────

async function readFile(file: File): Promise<void> {
  if (file.size > MAX_FILE_BYTES) {
    setState({ fileNote: { kind: "error", text: "ファイルサイズが 50MB を超えています。" } });
    return;
  }
  if (BINARY_EXT.test(file.name)) {
    setState({
      fileNote: {
        kind: "error",
        text: `${file.name} は PDF / Office 形式です。バックエンドの分析APIはテキスト本文のみを受け付けるため、ファイルを開いて本文をコピーし、下の欄に貼り付けてください。`,
      },
    });
    return;
  }
  if (!TEXT_EXT.test(file.name) && file.type && !file.type.startsWith("text/")) {
    setState({ fileNote: { kind: "error", text: `${file.name} はテキストとして読み込めない形式です。` } });
    return;
  }
  try {
    const text = await file.text();
    if (!text.trim()) {
      setState({ fileNote: { kind: "error", text: `${file.name} は空のファイルです。` } });
      return;
    }
    setState({ docText: text, fileName: file.name, fileNote: { kind: "ok", text: `${file.name} を読み込みました（${text.length.toLocaleString()}字）。` } });
    saveDraft();
  } catch {
    setState({ fileNote: { kind: "error", text: `${file.name} を読み込めませんでした。` } });
  }
}

// ─── バックエンド連携 ────────────────────────────────────────────────────

const DEFAULT_DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri"];

function toDraft(m: PipelineMember): MemberDraft {
  return {
    id: m.id,
    name: m.name,
    skills: formatSkills(m),
    cap: m.availability?.available_hours_per_week ?? 40,
    base: m.availability?.current_assigned_hours ?? 0,
    days: m.availability?.working_days?.length ? m.availability.working_days : DEFAULT_DAYS,
    raw: m,
  };
}

/** 編集フォームの内容を Phase 6 の Member スキーマに変換する（元のレコードの他の項目は保持） */
function fromDraft(d: MemberDraft): PipelineMember {
  const prevLevels = new Map((d.raw?.skills ?? []).map((s) => [norm(s.skill), s]));
  return {
    id: d.id,
    name: d.name.trim(),
    skills: parseSkills(d.skills).map((s) => ({
      skill: s.skill,
      level: s.level,
      experience_years: prevLevels.get(norm(s.skill))?.experience_years ?? null,
    })),
    experience_years: d.raw?.experience_years ?? null,
    availability: {
      available_hours_per_week: Math.max(0, Number(d.cap) || 0),
      working_days: d.days,
      current_assigned_hours: Math.max(0, Number(d.base) || 0),
    },
    constraints: d.raw?.constraints ?? [],
  };
}

async function loadProjectAndMembers(): Promise<void> {
  const pid = getActiveProjectId();
  if (!pid) return;
  try {
    const p = await getProject(pid);
    state.projectId = p.id;
    state.projectName = p.name ?? "";
    const dir = await fetchProjectMembers(p.id);
    state.members = dir.members.map(toDraft);
    state.membersNote = dir.members.length ? `プロジェクトに登録済みのメンバー ${dir.members.length}名を読み込みました。` : null;
  } catch {
    // 保存されていたプロジェクトが存在しない等。新規作成から始める
    state.projectId = null;
  }
  render();
}

async function startAnalysis(): Promise<void> {
  if (state.starting) return;
  const text = state.docText.trim();
  const members = state.members.filter((m) => m.name.trim());
  if (!text || !members.length) return;
  setState({ starting: true, startError: null });
  try {
    let projectId = state.projectId;
    if (!projectId || state.newProject) {
      const p = await createProject({ name: state.projectName.trim() || null });
      projectId = p.id;
      state.projectId = p.id;
      state.projectName = p.name ?? "";
      state.newProject = false;
    }
    const saved = await setProjectMembers(projectId, members.map(fromDraft));
    state.members = saved.members.map(toDraft);
    const { job_id } = await startGeneration(projectId, {
      document_text: text,
      use_assignment_llm_reasoning: state.optLlmReason,
      use_duplicate_llm_verification: state.optDupLlm,
    });
    LS.set(docKey(job_id), JSON.stringify({ text: state.docText, fileName: state.fileName }));
    jobStartedAt = Date.now();
    setState({
      starting: false, jobId: job_id, job: null, jobError: null, logs: [], model: null,
      assign: {}, acked: {}, kb: {}, selReq: "", selTask: "", maxStep: 3,
    });
    go(3);
    pollJob(job_id);
  } catch (err) {
    setState({ starting: false, startError: extractErrorMessage(err, "分析の開始に失敗しました。") });
  }
}

function elapsed(): string {
  const s = Math.max(0, Math.round((Date.now() - (jobStartedAt || Date.now())) / 1000));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

function addLog(msg: string | null | undefined): void {
  const m = (msg || "").trim();
  if (!m || state.logs[state.logs.length - 1]?.msg === m) return;
  state.logs = [...state.logs, { t: elapsed(), msg: m }].slice(-40);
}

async function pollJob(jobId: string): Promise<void> {
  const token = ++pollToken;
  for (;;) {
    if (token !== pollToken) return;
    let st: JobStatusResponse;
    try {
      st = await getJobStatus(jobId);
    } catch (err) {
      if (token !== pollToken) return;
      setState({ jobError: extractErrorMessage(err, "ジョブ状態の取得に失敗しました。"), job: state.job ? { ...state.job, status: "failed" } : null });
      return;
    }
    if (token !== pollToken) return;
    if (!jobStartedAt) jobStartedAt = Date.parse(st.started_at || st.created_at) || Date.now();
    const stepLabel = PIPELINE_STEPS.find((s) => s.id === st.current_step)?.label;
    addLog(st.message || (stepLabel ? `${stepLabel}…` : null));

    if (st.status === "completed") {
      addLog("分析が完了しました");
      setState({ job: st });
      await loadResult(jobId);
      return;
    }
    if (st.status === "failed" || st.status === "cancelled") {
      let msg = st.error?.message ?? st.message ?? null;
      try {
        const e = await getJobError(jobId);
        if (e?.message) msg = e.message;
      } catch { /* エラー詳細が取れなくても status の情報で表示する */ }
      addLog(msg || "分析に失敗しました");
      setState({ job: st, jobError: msg || "分析中にエラーが発生しました。" });
      return;
    }
    setState({ job: st });
    await new Promise((r) => setTimeout(r, POLL_INTERVAL_MS));
  }
}

function restoreDoc(jobId: string): void {
  try {
    const d = JSON.parse(LS.get(docKey(jobId)) || "null");
    if (d && typeof d.text === "string") {
      state.docText = d.text;
      state.fileName = d.fileName || "";
    }
  } catch { /* 無視 */ }
}

async function loadResult(jobId: string): Promise<void> {
  setState({ loadingResult: true });
  try {
    invalidateProjectResultCache();
    const out = await getProjectResult();
    let docText = "";
    try { docText = JSON.parse(LS.get(docKey(jobId)) || "null")?.text ?? ""; } catch { /* 無視 */ }
    const M = buildModel(out, docText);
    const work = loadWork(jobId, M);
    setState({
      model: M, loadingResult: false, maxStep: 11,
      ...work,
      selReq: M.reqs[0]?.id ?? "",
      selTask: M.tasks[0]?.id ?? "",
    });
  } catch (err) {
    setState({ loadingResult: false, jobError: extractErrorMessage(err, "分析結果の取得に失敗しました。") });
  }
}

function exportJson(): void {
  const M = state.model;
  if (!M) return;
  const data = {
    project: { name: M.name, document_id: M.documentId, job_id: state.jobId, exported_at: new Date().toISOString() },
    tasks: M.tasks.map((t) => ({
      id: t.id, title: t.title, requirement_ids: t.reqIds, estimated_hours: t.hKnown ? t.h : null,
      required_skills: t.skills, depends_on: t.deps,
      assigned_member_id: state.assign[t.id] ?? null,
      assigned_member_name: state.assign[t.id] ? M.MEM[state.assign[t.id]!]?.name ?? null : null,
      ai_assigned_member_id: M.aiAssign[t.id] ?? null,
      status: state.kb[t.id] ?? "未着手",
    })),
    members: M.members.map((m) => ({ id: m.id, name: m.name, available_hours_per_week: m.cap, workload_percentage: pctOf(M, m.id, state.assign) })),
  };
  const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = `tasumiru_${(M.name || "project").replace(/[\\/:*?"<>|\s]+/g, "_")}.json`;
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

function newSpec(): void {
  pollToken++;
  state.jobId = null;
  setActiveJobId(null);
  invalidateProjectResultCache();
  jobStartedAt = 0;
  setState({
    step: 1, maxStep: 2, model: null, job: null, jobError: null, logs: [],
    assign: {}, acked: {}, kb: {}, docText: "", fileName: "", fileNote: null, startError: null,
  });
  saveDraft();
}

// ─── イベント（委譲） ─────────────────────────────────────────────────────

let onTeam: (() => void) | null = null;

function bindEvents(): void {
  root.addEventListener("click", (e) => {
    const el = (e.target as HTMLElement).closest<HTMLElement>("[data-act]");
    if (!el || (el as HTMLButtonElement).disabled) return;
    const a = el.dataset.a ?? "";
    const b = el.dataset.b ?? "";
    const M = state.model;
    switch (el.dataset.act) {
      case "go":
        go(Number(a));
        break;
      case "variant":
        setState({ variant: { ...state.variant, [state.step]: Number(a) } });
        break;
      case "pickFile":
        (root.querySelector("#s2t-file") as HTMLInputElement | null)?.click();
        break;
      case "sample":
        e.stopPropagation();
        setState({ docText: SAMPLE_SPEC, fileName: "サンプル仕様書（ECサイト）.txt", fileNote: { kind: "ok", text: "サンプル仕様書を読み込みました。実際にバックエンドで分析されます。" } });
        saveDraft();
        break;
      case "clearDoc":
        e.stopPropagation();
        setState({ docText: "", fileName: "", fileNote: null });
        saveDraft();
        break;
      case "addMember":
        setState({ members: [...state.members, { id: `m_${Date.now()}`, name: "", skills: "", cap: 40, base: 0, days: DEFAULT_DAYS }] });
        break;
      case "delMember":
        setState({ members: state.members.filter((_, i) => i !== Number(a)) });
        break;
      case "start":
        startAnalysis();
        break;
      case "reloadResult":
        if (state.jobId) loadResult(state.jobId);
        break;
      case "selReq":
        setState({ selReq: a });
        break;
      case "selTask":
        setState({ selTask: a });
        break;
      case "selTask8":
        setState({ selTask: a, variant: { ...state.variant, 8: 2 } });
        break;
      case "selTaskByReq": {
        const t = M?.tasks.find((x) => x.reqIds.includes(a));
        if (t) setState({ selTask: t.id });
        break;
      }
      case "openSource":
        openSource(a);
        break;
      case "openSourceReq": {
        const t = M?.tasks.find((x) => x.reqIds.includes(a));
        if (t) openSource(t.id);
        else { state.selReq = a; state.variant[4] = 1; setState({}); }
        break;
      }
      case "assign":
        setAssign(a, b);
        break;
      case "resetAssign":
        if (M) { setState({ assign: { ...M.aiAssign } }); saveWork(); }
        break;
      case "ack":
        ack(a);
        break;
      case "kbMove":
        setState({ kb: { ...state.kb, [a]: b as KanbanCol } });
        saveWork();
        break;
      case "exportJson":
        exportJson();
        break;
      case "newSpec":
        newSpec();
        break;
      case "team":
        onTeam?.();
        break;
    }
  });

  // テキスト入力は再描画せずに状態だけ更新する（入力中のフォーカスを保つため）
  root.addEventListener("input", (e) => {
    const t = e.target as HTMLInputElement;
    if (t.dataset.bind === "docText") {
      state.docText = t.value;
      if (!t.value) state.fileName = "";
      const next = root.querySelector<HTMLButtonElement>("[data-next]");
      if (next) next.disabled = nextDisabled();
      saveDraft();
    } else if (t.dataset.bind === "projectName") {
      state.projectName = t.value;
    } else if (t.dataset.mi != null) {
      const m = state.members[Number(t.dataset.mi)];
      if (!m) return;
      const f = t.dataset.mf as "name" | "skills" | "cap" | "base";
      if (f === "cap" || f === "base") m[f] = Number(t.value) || 0;
      else m[f] = t.value;
    }
  });

  root.addEventListener("change", (e) => {
    const t = e.target as HTMLInputElement;
    if (t.id === "s2t-file") {
      const f = t.files?.[0];
      if (f) readFile(f);
      t.value = "";
    } else if (t.name === "proj") {
      setState({ newProject: t.value === "new", projectName: t.value === "new" ? "" : state.projectName });
    } else if (t.dataset.bindCheck) {
      (state as unknown as Record<string, boolean>)[t.dataset.bindCheck] = t.checked;
    } else if (t.dataset.assign) {
      setAssign(t.dataset.assign, t.value);
    }
    // 注意: テキスト入力の change（フォーカスが外れた時）では再描画しない。
    // 「入力してすぐボタンを押す」操作で mousedown と mouseup の間に DOM が
    // 差し替わり、クリックが失われるため。表示は次の操作時に更新される。
  });

  // Kanban のドラッグ＆ドロップ、および仕様書ファイルのドロップ。
  // ドラッグ中に innerHTML を差し替えるとドラッグ元要素が消えて操作が中断されるため、
  // ハイライトはクラス切替のみで行う。
  let dragging: string | null = null;
  const colOf = (e: Event) => (e.target as HTMLElement).closest<HTMLElement>(".s2t-kb-col");
  const dropOf = (e: Event) => (e.target as HTMLElement).closest<HTMLElement>(".s2t-drop");

  root.addEventListener("dragstart", (e) => {
    const card = (e.target as HTMLElement).closest<HTMLElement>(".s2t-kb-card");
    if (!card) return;
    dragging = card.dataset.task!;
    e.dataTransfer?.setData("text/plain", dragging);
    card.classList.add("is-dragging");
  });
  root.addEventListener("dragend", () => {
    dragging = null;
    root.querySelectorAll(".is-dragging, .is-hover").forEach((el) => el.classList.remove("is-dragging", "is-hover"));
  });
  root.addEventListener("dragover", (e) => {
    const drop = dropOf(e);
    if (drop) {
      e.preventDefault();
      drop.classList.add("is-hover");
      return;
    }
    const col = colOf(e);
    if (!col) return;
    e.preventDefault();
    if (!col.classList.contains("is-hover")) {
      root.querySelectorAll(".s2t-kb-col.is-hover").forEach((el) => el.classList.remove("is-hover"));
      col.classList.add("is-hover");
    }
  });
  root.addEventListener("dragleave", (e) => {
    const drop = dropOf(e);
    if (drop && !drop.contains(e.relatedTarget as Node)) drop.classList.remove("is-hover");
  });
  root.addEventListener("drop", (e) => {
    const drop = dropOf(e);
    if (drop) {
      e.preventDefault();
      drop.classList.remove("is-hover");
      const f = e.dataTransfer?.files?.[0];
      if (f) readFile(f);
      return;
    }
    const col = colOf(e);
    if (!col) return;
    e.preventDefault();
    const id = e.dataTransfer?.getData("text/plain") || dragging;
    dragging = null;
    if (id && state.model?.TK[id]) {
      setState({ kb: { ...state.kb, [id]: col.dataset.col as KanbanCol } });
      saveWork();
    }
  });
}

// ─── 起動 ────────────────────────────────────────────────────────────────

export interface MountOptions {
  /** 表示中のユーザー（サイドバーに表示） */
  userLabel?: string;
  /** バックエンド未接続のデモモード（サンプル結果を表示） */
  demo?: boolean;
  /** 「チームメンバー」ボタン */
  onTeam?: () => void;
}

let mounted = false;

export async function mountSpecToTasks(el: HTMLElement, opts: MountOptions = {}): Promise<void> {
  userLabel = opts.userLabel ?? "";
  onTeam = opts.onTeam ?? null;
  if (mounted) { render(); return; }
  mounted = true;
  root = el;
  state.demo = !!opts.demo;
  bindEvents();

  try {
    const d = JSON.parse(LS.get(DRAFT_KEY) || "null");
    if (d && typeof d.text === "string") { state.docText = d.text; state.fileName = d.fileName || ""; }
  } catch { /* 無視 */ }

  if (state.demo) {
    const out = await getSampleProjectResult();
    const M = buildModel(out, "");
    Object.assign(state, {
      model: M, step: 4, maxStep: 11, assign: { ...M.aiAssign },
      kb: Object.fromEntries(M.tasks.map((t) => [t.id, "未着手"])),
      selReq: M.reqs[0]?.id ?? "", selTask: M.tasks[0]?.id ?? "",
      members: M.members.map((m) => toDraft(m.raw)),
    });
    render();
    return;
  }

  render();
  await loadProjectAndMembers();

  // 直前に実行した分析があれば復元する（バックエンドに「最新ジョブ一覧」APIが
  // 無いため、localStorage に保存した直近の job_id だけを手がかりにする）
  const jobId = getActiveJobId();
  if (!jobId) return;
  try {
    const st = await getJobStatus(jobId);
    state.jobId = jobId;
    state.job = st;
    restoreDoc(jobId);
    jobStartedAt = Date.parse(st.started_at || st.created_at) || Date.now();
    if (st.status === "completed") {
      state.step = 4;
      await loadResult(jobId);
    } else if (st.status === "queued" || st.status === "running") {
      setState({ step: 3, maxStep: 3 });
      pollJob(jobId);
    } else {
      state.jobError = st.error?.message ?? st.message ?? "前回の分析は失敗しました。";
      setState({ step: 3, maxStep: 3 });
    }
  } catch {
    // 保存されていた job_id がもう存在しない等。最初から始める
    setActiveJobId(null);
  }
}
