// src/specToTasks/main.ts
//
// 画面: Spec to Tasks（仕様書 → 要件抽出 → タスク分解 → 自動割当 → Kanban）の
// 11ステップ・ウィザード。claude.ai/design「Spec to Tasks.dc.html」の実装。
// 現状はサンプルデータ（./data.ts）のみで動作するフロントエンド単体デモ。
//
// URLパラメータ（デザインの props に対応）:
//   ?step=1..11  開始ステップ（4以上は分析完了済みとして開く）
//   ?secs=2..20  分析アニメーションの秒数（既定 6）
//   ?auto=1      分析完了後に要件抽出へ自動で進む
import "./industry.css";
import "./spec-to-tasks.css";
import {
  CAP, DOC, FILE_NAME, GROUPS, INIT_ASSIGN, KANBAN_COLS, KANBAN_INIT, LOGS, MEM, MEMBERS,
  PARA, PHASES, RAMP, REQ, REQS, SK, SKK, STEPS, TASKS, TK, UNASSIGNED_REASON, VARIANTS,
  WARN, WARN_BG, WARN_FG, hoursOf, pctOf, scoreOf,
} from "./data";
import type { Assignment, KanbanCol, Requirement, Task } from "./data";

// ─── 設定・状態 ──────────────────────────────────────────────────────────

const params = new URLSearchParams(location.search);
const clampInt = (v: string | null, def: number, min: number, max: number): number => {
  const n = v == null ? NaN : parseInt(v, 10);
  return Number.isFinite(n) ? Math.max(min, Math.min(max, n)) : def;
};
const START_STEP = clampInt(params.get("step"), 1, 1, 11);
const ANALYSIS_SECONDS = clampInt(params.get("secs"), 6, 2, 20);
const AUTO_ADVANCE = params.get("auto") === "1";

interface State {
  step: number;
  maxStep: number;
  file: boolean;
  prog: number;
  policy: string;
  variant: Record<number, number>;
  assign: Assignment;
  acked: Record<string, boolean>;
  selReq: string;
  selTask: string;
  kb: Record<string, KanbanCol>;
}

const pre = START_STEP >= 4;
const state: State = {
  step: START_STEP,
  maxStep: pre ? 11 : START_STEP,
  file: START_STEP >= 2,
  prog: pre ? 100 : 0,
  policy: "バランス",
  variant: { 4: 0, 7: 0, 8: 0, 9: 0 },
  assign: { ...INIT_ASSIGN },
  acked: {},
  selReq: "R-01",
  selTask: "T-03",
  kb: { ...KANBAN_INIT },
};

let timer: number | null = null;

function setState(patch: Partial<State>): void {
  Object.assign(state, patch);
  render();
}

function go(n: number): void {
  n = Math.max(1, Math.min(11, n));
  setState({ step: n, maxStep: Math.max(state.maxStep, n) });
  window.scrollTo(0, 0);
  if (n === 3 && state.prog < 100) runAnalysis();
}

function runAnalysis(): void {
  if (timer != null) return;
  const inc = 100 / ((ANALYSIS_SECONDS * 1000) / 60);
  timer = window.setInterval(() => {
    const p = Math.min(100, state.prog + inc);
    if (p >= 100) {
      window.clearInterval(timer!);
      timer = null;
      setState({ prog: p, maxStep: 11 });
      if (AUTO_ADVANCE) window.setTimeout(() => { if (state.step === 3) go(4); }, 900);
    } else {
      setState({ prog: p });
    }
  }, 60);
}

function setAssign(tid: string, mid: string): void {
  setState({ assign: { ...state.assign, [tid]: mid }, selTask: tid });
}

function ack(key: string): void {
  setState({ acked: { ...state.acked, [key]: true } });
}

function openSource(tid: string): void {
  state.selTask = tid;
  go(10);
}

// ─── 共通ヘルパー ────────────────────────────────────────────────────────

const esc = (v: unknown): string =>
  String(v).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]!);

const CORNERS = '<i class="corner tl"></i><i class="corner tr"></i><i class="corner bl"></i><i class="corner br"></i>';
const ACC = "var(--color-accent)";
const clamp01 = (x: number) => Math.max(0, Math.min(1, x));
/** 負荷% → バー幅（125% を満幅とし、80h 上限線が 80% 位置に来るようにする） */
const W = (p: number) => ((Math.max(0, p) / 125) * 100).toFixed(1) + "%";

/** data-act 付きのクリック属性 */
const act = (name: string, a?: string | number, b?: string | number): string =>
  `data-act="${name}"` + (a != null ? ` data-a="${esc(a)}"` : "") + (b != null ? ` data-b="${esc(b)}"` : "");

const firstName = (name: string) => name.split(" ")[0];

// ─── 派生データ ──────────────────────────────────────────────────────────

interface MemberView {
  id: string; name: string; ini: string; role: string; pct: number; hTxt: string;
  baseW: string; newW: string; barBg: string; pctFg: string; status: string; stBg: string; stFg: string;
  bp: number; over: boolean; mine: Task[];
}

function memberViews(a: Assignment): MemberView[] {
  return MEMBERS.map((m) => {
    const h = hoursOf(m.id, a);
    const p = Math.round((h / CAP) * 100);
    const bp = Math.round((m.base / CAP) * 100);
    const over = p > 100;
    return {
      id: m.id, name: m.name, ini: m.ini, role: m.role, pct: p, hTxt: `${h}h / ${CAP}h`,
      baseW: W(bp), newW: W(p - bp), barBg: over ? WARN : ACC, pctFg: over ? WARN : "var(--color-text)",
      status: p > 100 ? "過負荷" : p > 85 ? "高負荷" : p >= 60 ? "適正" : "余裕あり",
      stBg: over ? WARN_BG : p > 85 ? "var(--color-accent-200)" : "var(--color-neutral-100)",
      stFg: over ? WARN_FG : "var(--color-accent-800)",
      bp, over, mine: TASKS.filter((t) => a[t.id] === m.id),
    };
  });
}

interface TaskRow {
  t: Task; who: string; whoShort: string; ini: string; whoFg: string;
  score: number | "—"; reason: string; deps: string; assigned: boolean;
}

function taskRow(t: Task, a: Assignment): TaskRow {
  const mid = a[t.id];
  const m = mid ? MEM[mid] : undefined;
  const sc = m ? scoreOf(m, t, a) : null;
  return {
    t,
    who: m ? m.name : "未割当",
    whoShort: m ? firstName(m.name) : "未割当",
    ini: m ? m.ini : "?",
    whoFg: m ? "var(--color-text)" : WARN,
    score: sc ? sc.total : "—",
    reason: m && sc
      ? `${SK[t.sk]} Lv${sc.lv}（必要 Lv${t.lv}）· ${firstName(m.name)}の負荷 ${pctOf(m.id, a)}%` + (sc.lv < t.lv ? " · スキル不足" : "")
      : UNASSIGNED_REASON[t.id] || "条件を満たす候補がいません",
    deps: t.deps.length ? t.deps.join(", ") : "なし",
    assigned: !!m,
  };
}

interface WarnAction { label: string; sub: string; attrs: string }
interface Warning { kind: string; sev: 0 | 1 | 2; title: string; detail: string; actions: WarnAction[]; bg: string; fg: string }

function buildWarnings(a: Assignment): Warning[] {
  const warns: Omit<Warning, "bg" | "fg">[] = [];
  const wa = (label: string, sub: string, attrs: string): WarnAction => ({ label, sub, attrs });

  TASKS.filter((t) => !a[t.id]).forEach((t) => {
    const c = MEMBERS.map((m) => ({ m, s: scoreOf(m, t, a) })).sort((x, y) => y.s.total - x.s.total).slice(0, 2);
    warns.push({
      kind: "未割当", sev: 0, title: `${t.id} ${t.title}`,
      detail: UNASSIGNED_REASON[t.id] || "条件を満たす候補がいません",
      actions: c.map((x) => wa(`${x.m.name}に割当`, `適合 ${x.s.total} · 負荷→${x.s.after}%`, act("assign", t.id, x.m.id))),
    });
  });

  MEMBERS.forEach((m) => {
    const p = pctOf(m.id, a);
    if (p <= 100) return;
    const mine = TASKS.filter((t) => a[t.id] === m.id).sort((x, y) => x.h - y.h);
    warns.push({
      kind: "過負荷", sev: 0, title: `${m.name}の負荷が${p}%`,
      detail: `上限 ${CAP}h に対し ${hoursOf(m.id, a)}h（${mine.map((t) => t.id).join("・")}）`,
      actions: mine.slice(0, 2).map((t) => {
        const alt = MEMBERS.filter((o) => o.id !== m.id)
          .map((o) => ({ o, s: scoreOf(o, t, a) }))
          .sort((x, y) => y.s.total - x.s.total)[0];
        return wa(`${t.id}を${alt.o.name}へ`, `適合 ${alt.s.total} · 負荷→${alt.s.after}%`, act("assign", t.id, alt.o.id));
      }),
    });
  });

  TASKS.forEach((t) => {
    const mid = a[t.id];
    if (!mid || state.acked[t.id]) return;
    const m = MEM[mid];
    const lv = m.sk[t.sk] || 0;
    if (lv >= t.lv) return;
    const alt = MEMBERS.filter((o) => o.id !== mid && (o.sk[t.sk] || 0) >= t.lv)
      .map((o) => ({ o, s: scoreOf(o, t, a) }))
      .sort((x, y) => y.s.total - x.s.total)
      .slice(0, 1);
    warns.push({
      kind: "スキル不足", sev: 1, title: `${t.id} ${t.title}`,
      detail: `${m.name}：${SK[t.sk]} Lv${lv}（必要 Lv${t.lv}）`,
      actions: alt
        .map((x) => wa(`${x.o.name}に変更`, `適合 ${x.s.total} · 負荷→${x.s.after}%`, act("assign", t.id, x.o.id)))
        .concat([wa("このまま進める", "レビュー担当を付ける", act("ack", t.id))]),
    });
  });

  if (!state.acked["R-07"]) {
    warns.push({
      kind: "要件が曖昧", sev: 2, title: "R-07 ページ表示の高速化",
      detail: "原文「ページは高速に表示されること」— 数値目標がありません",
      actions: [wa("出典を確認", "§5.1 p.12", act("openSource", "T-12")), wa("確認済みにする", "顧客に確認依頼済み", act("ack", "R-07"))],
    });
  }

  const SEV: [string, string][] = [[WARN_BG, WARN_FG], ["var(--color-accent-200)", "var(--color-accent-800)"], ["var(--color-neutral-200)", "var(--color-neutral-800)"]];
  return warns.map((w) => ({ ...w, bg: SEV[w.sev][0], fg: w.sev === 0 ? WARN : SEV[w.sev][1] }));
}

/** 依存の深さ（着手レベル）と、最長経路（クリティカルパス） */
function dependencyInfo() {
  const depth: Record<string, number> = {};
  const fin: Record<string, number> = {};
  const prev: Record<string, string | null> = {};
  const depthOf = (t: Task): number => {
    if (depth[t.id] != null) return depth[t.id];
    return (depth[t.id] = t.deps.length ? 1 + Math.max(...t.deps.map((d) => depthOf(TK[d]))) : 0);
  };
  const finOf = (t: Task): number => {
    if (fin[t.id] != null) return fin[t.id];
    let best = 0;
    let bp: string | null = null;
    t.deps.forEach((d) => {
      const f = finOf(TK[d]);
      if (f > best) { best = f; bp = d; }
    });
    prev[t.id] = bp;
    return (fin[t.id] = best + t.h);
  };
  TASKS.forEach((t) => { depthOf(t); finOf(t); });
  const end = TASKS.reduce((b, t) => (fin[t.id] > fin[b.id] ? t : b), TASKS[0]).id;
  const chain: string[] = [];
  for (let c: string | null = end; c; c = prev[c]) chain.unshift(c);
  return { depth, chain, total: fin[end] };
}

// ─── レイアウト ──────────────────────────────────────────────────────────

function railHtml(): string {
  return GROUPS.map((title, gi) => `
    <div style="display:flex;flex-direction:column;gap:1px">
      <div style="font-size:10px;letter-spacing:.12em;color:var(--color-neutral-600);padding:0 10px 5px">${esc(title)}</div>
      ${STEPS.filter((s) => s.g === gi).map((s) => {
        const cur = s.n === state.step;
        const ok = s.n <= state.maxStep;
        const done = s.n < state.step && ok;
        const v = VARIANTS[s.n];
        return `
        <div ${ok ? act("go", s.n) : ""} style="display:flex;align-items:center;gap:10px;padding:6px 10px;cursor:${ok ? "pointer" : "default"};background:${cur ? "var(--color-accent-100)" : "transparent"};opacity:${ok ? 1 : 0.45}">
          <span style="width:22px;height:22px;flex:none;display:grid;place-items:center;font:600 12px var(--font-heading);border:1px solid ${cur || done ? ACC : "var(--color-divider)"};background:${cur ? "var(--color-accent-800)" : "transparent"};color:${cur ? "#fff" : done ? "var(--color-accent-700)" : "var(--color-neutral-600)"}">${s.n}</span>
          <span style="flex:1;font-size:13px;color:${cur ? "var(--color-accent-800)" : "var(--color-text)"};font-weight:${cur ? 600 : 400}">${esc(s.t)}</span>
          ${v ? `<span style="font-size:10px;padding:1px 5px;border:1px solid var(--color-accent-300);color:var(--color-accent-700)">${v.length}案</span>` : ""}
        </div>`;
      }).join("")}
    </div>`).join("");
}

function headerHtml(): string {
  const step = state.step;
  const S = STEPS[step - 1];
  const variants = VARIANTS[step];
  const hasNext = step < 11 && step !== 2;
  const nextDisabled = (step === 1 && !state.file) || (step === 3 && state.prog < 100);
  return `
  <header style="position:sticky;top:0;z-index:5;background:var(--color-bg);border-bottom:1px solid var(--color-divider)">
    <div style="display:flex;align-items:center;gap:18px;padding:16px 28px 14px;flex-wrap:wrap">
      <div style="flex:1;min-width:260px;display:flex;flex-direction:column;gap:2px">
        <div style="font-size:11px;letter-spacing:.1em;color:var(--color-accent-700)">STEP ${step} / 11 · ${esc(FILE_NAME)}</div>
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
        ${hasNext ? `<button class="btn btn-primary blueprint" ${nextDisabled ? "disabled" : ""} ${act("go", step + 1)}>${CORNERS}次へ：${esc(STEPS[Math.min(10, step)].t)} →</button>` : ""}
      </div>
    </div>
    <div style="display:grid;grid-template-columns:repeat(11,1fr);gap:2px;padding:0 28px 0">
      ${STEPS.map((s) => `<div style="height:3px;background:${s.n <= step ? ACC : "var(--color-divider)"}"></div>`).join("")}
    </div>
  </header>`;
}

// ─── 各ステップ ──────────────────────────────────────────────────────────

function step1(): string {
  const readRow = (n: string, title: string, sub: string) => `
    <div style="display:grid;grid-template-columns:28px 1fr;gap:10px;padding:12px 0;border-bottom:1px solid var(--color-divider)"><span style="font:600 16px var(--font-heading);color:var(--color-accent)">${n}</span><div><div style="font-weight:500">${title}</div><div style="font-size:12.5px;color:var(--color-neutral-700)">${sub}</div></div></div>`;
  return `
  <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(320px,1fr));gap:32px;align-items:start">
    <div class="blueprint s2t-drop" ${act("pickFile")} style="min-height:380px;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:14px;cursor:pointer;border-style:dashed;padding:40px;text-align:center">
      ${CORNERS}
      ${!state.file ? `
      <div style="display:flex;flex-direction:column;align-items:center;gap:14px">
        <span style="color:var(--color-accent)"><svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path><polyline points="17 8 12 3 7 8"></polyline><line x1="12" y1="3" x2="12" y2="15"></line></svg></span>
        <h2 style="margin:0;font-size:28px">仕様書をここにドロップ</h2>
        <div style="font-size:13px;color:var(--color-neutral-700)">PDF / Word / Markdown · 最大 50MB</div>
        <div style="display:flex;gap:10px;margin-top:6px"><span class="btn btn-secondary">ファイルを選択</span><span class="btn btn-ghost">サンプル仕様書で試す</span></div>
      </div>` : `
      <div style="display:flex;flex-direction:column;align-items:center;gap:12px">
        <div class="blueprint" style="width:120px;height:150px;display:flex;flex-direction:column;justify-content:flex-end;padding:10px;background:repeating-linear-gradient(0deg,transparent 0 11px,var(--color-accent-200) 11px 12px)">
          ${CORNERS}
          <span style="font:600 14px var(--font-heading);background:var(--color-accent-800);color:#fff;align-self:flex-start;padding:1px 6px">PDF</span>
        </div>
        <div style="font:600 20px var(--font-heading)">${esc(FILE_NAME)}</div>
        <div style="font-size:13px;color:var(--color-neutral-700)">24ページ · 1.8MB · 5章 32節</div>
        <span class="tag tag-accent">✓ 読み込み完了</span>
      </div>`}
    </div>
    <div style="display:flex;flex-direction:column;gap:18px;padding-top:6px">
      <h3 style="margin:0;font-size:22px">AIが読み取るもの</h3>
      <div style="display:flex;flex-direction:column;border-top:1px solid var(--color-divider)">
        ${readRow("01", "機能・非機能要件と制約", "文章から要件を切り出し、優先度と信頼度を付与")}
        ${readRow("02", "章番号とページ", "すべてのタスクに出典として紐づけ")}
        ${readRow("03", "曖昧な記述", "数値目標のない要件などを「要確認」として検出")}
      </div>
    </div>
  </div>`;
}

function step2(): string {
  const row = (label: string, body: string, last = false, pad = "16px 20px") => `
    <div style="display:grid;grid-template-columns:minmax(100px,150px) minmax(0,1fr);${last ? "" : "border-bottom:1px solid var(--color-divider)"}"><div style="padding:16px 20px;font-size:12px;color:var(--color-neutral-700)">${label}</div><div style="padding:${pad}">${body}</div></div>`;
  const policies = ["スキル優先", "バランス", "負荷平準化"];
  return `
  <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(340px,1fr));gap:32px;align-items:start">
    <div class="blueprint" style="padding:0">
      ${CORNERS}
      ${row("対象ファイル", `<span style="font-weight:500">${esc(FILE_NAME)}</span> <span style="font-weight:400;color:var(--color-neutral-600);font-size:12.5px">· 24ページ</span>`)}
      ${row("割当対象チーム", `<div style="display:flex;flex-direction:column;gap:8px"><span style="font-weight:500">ECリニューアルチーム（${MEMBERS.length}名）</span><div style="display:flex;flex-wrap:wrap;gap:6px">${MEMBERS.map((m) => `<span class="tag tag-neutral">${esc(m.name)} · ${esc(m.role)}</span>`).join("")}</div></div>`, false, "14px 20px")}
      ${row("対象期間", "2026/10/01 – 2027/03/31（開発フェーズ）")}
      ${row("1人あたり稼働上限", `${CAP}h / フェーズ（既存業務の負荷を差し引いて計算）`)}
      ${row("割当の方針", `<div class="seg">${policies.map((p) => `<label class="seg-opt"><input type="radio" name="pol" value="${p}" ${state.policy === p ? "checked" : ""}>${p}</label>`).join("")}</div>`, true, "12px 20px")}
    </div>
    <div style="display:flex;flex-direction:column;gap:16px">
      <h3 style="margin:0;font-size:22px">準備ができました</h3>
      <p style="margin:0;font-size:13.5px;color:var(--color-neutral-700)">分析には通常1〜2分かかります。完了後、要件・タスク・割当案を順に確認できます。割当はあとから自由に変更できます。</p>
      <button class="btn btn-primary blueprint" ${act("go", 3)} style="padding:16px 20px;font-size:18px">${CORNERS}AI分析を開始 →</button>
    </div>
  </div>`;
}

function step3(): string {
  const p = state.prog;
  const phaseNow = (PHASES.find(([, , e]) => p < e) || ["分析完了"])[0];
  const counters: [string, number][] = [
    ["要件", Math.round(10 * clamp01((p - 32) / 18))],
    ["タスク", Math.round(16 * clamp01((p - 52) / 14))],
    ["依存関係", Math.round(10 * clamp01((p - 68) / 12))],
    ["割当", Math.round(13 * clamp01((p - 82) / 16))],
  ];
  const logTime = (v: number) => `${Math.floor((v * 0.9) / 60)}:${String(Math.round(v * 0.9) % 60).padStart(2, "0")}`;
  return `
  <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(360px,1fr));gap:32px;align-items:start">
    <div style="display:flex;flex-direction:column;gap:22px">
      <div style="display:flex;align-items:flex-end;gap:16px"><span style="font:600 104px/0.9 var(--font-heading);letter-spacing:-.02em">${Math.round(p)}</span><span style="font:600 32px var(--font-heading);color:var(--color-neutral-600);padding-bottom:8px">%</span><span style="flex:1"></span><span style="font-size:13px;color:var(--color-accent-700);padding-bottom:10px;white-space:nowrap">${esc(phaseNow)}</span></div>
      <div style="height:8px;border:1px solid var(--color-divider);position:relative"><div style="position:absolute;inset:0 auto 0 0;width:${p}%;background:var(--color-accent)"></div></div>
      <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(120px,1fr));gap:14px">
        ${counters.map(([label, val]) => `<div class="blueprint" style="padding:14px 16px;display:flex;flex-direction:column;gap:2px">${CORNERS}<span style="font-size:11px;color:var(--color-neutral-700)">${label}</span><span style="font:600 40px/1 var(--font-heading)">${val}</span></div>`).join("")}
      </div>
      <div style="display:flex;flex-direction:column;border-top:1px solid var(--color-divider)">
        ${PHASES.map(([name, s, e]) => {
          const done = p >= e;
          const active = !done && p >= s;
          return `<div style="display:flex;align-items:center;gap:12px;padding:10px 0;border-bottom:1px solid var(--color-divider);color:${done || active ? "var(--color-text)" : "var(--color-neutral-500)"}"><span style="width:20px;height:20px;display:grid;place-items:center;font-size:11px;border:1px solid ${done || active ? ACC : "var(--color-divider)"};background:${done ? ACC : "transparent"};color:${done ? "#fff" : ACC}">${done ? "✓" : active ? "●" : ""}</span><span style="flex:1;font-size:14px;font-weight:${active ? 600 : 400}">${name}</span><span style="font-size:12px">${done ? "完了" : active ? "処理中…" : "待機"}</span></div>`;
        }).join("")}
      </div>
      ${p >= 100 ? `<div style="display:flex;gap:10px;align-items:center"><button class="btn btn-primary blueprint" ${act("go", 4)}>${CORNERS}抽出された要件を確認 →</button><span style="font-size:13px;color:var(--color-neutral-700)">要件10件 · タスク16件 · 割当13件 · 要対応4件</span></div>` : ""}
    </div>
    <div class="blueprint" style="padding:16px 18px;display:flex;flex-direction:column;gap:10px;min-height:420px">${CORNERS}
      <div style="font-size:10px;letter-spacing:.12em;color:var(--color-neutral-600)">分析ログ</div>
      ${LOGS.filter(([at]) => p >= at).map(([at, msg]) => `<div style="display:grid;grid-template-columns:44px 1fr;gap:8px;font-size:12.5px;line-height:1.5"><span style="font-family:var(--font-heading);color:var(--color-accent-700)">${logTime(at)}</span><span>${esc(msg)}</span></div>`).join("")}
    </div>
  </div>`;
}

/** 原文ビュー。reqId の段落をハイライトし、段落クリックで actName(reqId) を発火 */
function docHtml(reqId: string, actName: string): string {
  return DOC.map((d) => `
    <div style="display:flex;flex-direction:column;gap:8px"><h4 style="margin:0;font-size:19px">${esc(d.h)}</h4>
      ${d.paras.map((p) => {
        const hl = !!p.r && p.r === reqId;
        return `<div ${p.r ? act(actName, p.r) : ""} style="display:grid;grid-template-columns:48px 1fr;gap:10px;padding:8px 10px;font-size:14px;line-height:1.75;background:${hl ? "var(--color-accent-200)" : "transparent"};cursor:${p.r ? "pointer" : "default"};outline:${hl ? "1px solid var(--color-accent)" : "none"}"><span style="font:600 12px/2.2 var(--font-heading);color:var(--color-accent-700)">${esc(p.r || "")}</span><span>${esc(p.t)}</span></div>`;
      }).join("")}
    </div>`).join("");
}

const confFg = (r: Requirement) => (r.conf < 80 ? WARN : "var(--color-text)");

function step4(): string {
  const v = state.variant[4];
  const head = `<div style="display:flex;gap:10px;flex-wrap:wrap;align-items:center"><span class="tag tag-accent">要件 ${REQS.length}件</span><span class="tag tag-neutral">機能 ${REQS.filter((r) => r.cat === "機能").length} · 非機能 ${REQS.filter((r) => r.cat === "非機能").length} · 制約 ${REQS.filter((r) => r.cat === "制約").length}</span><span class="tag" style="background:${WARN_BG};color:${WARN_FG}">要確認 ${REQS.filter((r) => r.conf < 80).length}件（信頼度80%未満）</span></div>`;
  let body = "";
  if (v === 0) {
    body = `
    <table class="table">
      <thead><tr><th style="width:64px">ID</th><th>要件</th><th style="width:80px">区分</th><th style="width:70px">優先度</th><th style="width:170px">信頼度</th><th style="width:120px">出典</th></tr></thead>
      <tbody>
        ${REQS.map((r) => `<tr><td style="font:600 14px var(--font-heading);color:var(--color-accent-700)">${r.id}</td><td><div style="font-weight:500">${esc(r.title)}</div><div style="font-size:12px;color:var(--color-neutral-700)">${esc(r.detail)}</div></td><td><span class="tag tag-neutral">${r.cat}</span></td><td>${r.pri}</td><td><div style="display:flex;align-items:center;gap:8px"><div style="flex:1;height:4px;background:var(--color-neutral-200)"><div style="height:100%;width:${r.conf}%;background:${r.conf < 80 ? WARN : ACC}"></div></div><span style="font:600 14px var(--font-heading);width:34px;color:${confFg(r)}">${r.conf}%</span></div></td><td><button class="btn btn-ghost" ${act("openSourceReq", r.id)} style="font-size:13px">${r.sec} p.${r.page} ↗</button></td></tr>`).join("")}
      </tbody>
    </table>`;
  } else if (v === 1) {
    body = `
    <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(340px,1fr));gap:24px;align-items:start">
      <div class="blueprint" data-scroll="doc4" style="padding:28px 32px;max-height:640px;overflow:auto;display:flex;flex-direction:column;gap:18px">${CORNERS}
        <div style="font-size:10px;letter-spacing:.12em;color:var(--color-neutral-600)">原文 · ${esc(FILE_NAME)}</div>
        ${docHtml(state.selReq, "selReq")}
      </div>
      <div style="display:flex;flex-direction:column;border-top:1px solid var(--color-divider)">
        ${REQS.map((r) => `<div ${act("selReq", r.id)} style="display:grid;grid-template-columns:52px 1fr 48px;gap:10px;align-items:center;padding:10px 12px;border-bottom:1px solid var(--color-divider);cursor:pointer;background:${state.selReq === r.id ? "var(--color-accent-100)" : "transparent"}"><span style="font:600 14px var(--font-heading);color:var(--color-accent-700)">${r.id}</span><div><div style="font-weight:500;font-size:14px">${esc(r.title)}</div><div style="font-size:12px;color:var(--color-neutral-700)">${r.cat} · ${r.sec} · ${esc(r.detail)}</div></div><span style="font:600 15px var(--font-heading);text-align:right;color:${confFg(r)}">${r.conf}%</span></div>`).join("")}
      </div>
    </div>`;
  } else {
    const cats: [Requirement["cat"], string][] = [["機能", "ユーザー・管理者の操作"], ["非機能", "品質・性能・セキュリティ"], ["制約", "期限・条件"]];
    body = `
    <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:24px;align-items:start">
      ${cats.map(([c, note]) => {
        const items = REQS.filter((r) => r.cat === c);
        return `
        <div style="display:flex;flex-direction:column;gap:14px">
          <div style="display:flex;align-items:baseline;gap:10px;border-bottom:2px solid var(--color-text);padding-bottom:6px"><h3 style="margin:0;font-size:24px">${c}</h3><span style="font:600 24px var(--font-heading);color:var(--color-accent)">${items.length}</span><span style="font-size:12px;color:var(--color-neutral-700)">${note}</span></div>
          ${items.map((r) => `
          <div class="card blueprint">${CORNERS}
            <div style="display:flex;justify-content:space-between;align-items:center"><span class="card-kicker">${r.id} · 優先度 ${r.pri}</span><span style="font:600 15px var(--font-heading);color:${confFg(r)}">${r.conf}%</span></div>
            <div class="card-title">${esc(r.title)}</div>
            <p class="card-body">${esc(r.detail)}</p>
            <div class="card-meta"><span>${r.sec} p.${r.page}</span><span style="flex:1"></span>${r.conf < 80 ? `<span style="color:oklch(0.5 0.168 25)">要確認</span>` : ""}</div>
          </div>`).join("")}
        </div>`;
      }).join("")}
    </div>`;
  }
  return head + body;
}

function step5(): string {
  const a = state.assign;
  const total = TASKS.reduce((s, t) => s + t.h, 0);
  const groups = REQS.map((r) => ({ r, tasks: TASKS.filter((t) => t.req === r.id) })).filter((g) => g.tasks.length);
  return `
  <div style="display:flex;gap:10px;flex-wrap:wrap"><span class="tag tag-accent">タスク ${TASKS.length}件</span><span class="tag tag-neutral">見積り合計 ${total}h</span></div>
  <div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(min(420px,100%),1fr));gap:24px 28px;align-items:start">
    ${groups.map(({ r, tasks }) => `
    <div style="display:flex;flex-direction:column">
      <div style="display:flex;align-items:baseline;gap:10px;padding-bottom:6px;border-bottom:2px solid var(--color-text)"><span style="font:600 15px var(--font-heading);color:var(--color-accent-700)">${r.id}</span><span style="flex:1;font-weight:500">${esc(r.title)}</span><span style="font-size:12px;color:var(--color-neutral-700)">${tasks.length}タスク · ${tasks.reduce((s, t) => s + t.h, 0)}h</span></div>
      ${tasks.map((t) => {
        const row = taskRow(t, a);
        return `<div style="display:grid;grid-template-columns:48px 1fr auto 44px;gap:10px;align-items:center;padding:9px 0;border-bottom:1px solid var(--color-divider);font-size:13.5px"><span style="font:600 13px var(--font-heading);color:var(--color-neutral-600)">${t.id}</span><div><div>${esc(t.title)}</div><div style="font-size:11.5px;color:var(--color-neutral-600)">依存: ${row.deps}</div></div><span class="tag tag-outline">${SK[t.sk]} Lv${t.lv}</span><span style="font:600 15px var(--font-heading);text-align:right">${t.h}h</span></div>`;
      }).join("")}
    </div>`).join("")}
  </div>`;
}

function step6(): string {
  const { depth, chain, total } = dependencyInfo();
  const crit = new Set(chain);
  const cols = [0, 1, 2, 3]
    .map((d) => ({ d, items: TASKS.filter((t) => depth[t.id] === d) }))
    .filter((c) => c.items.length);
  return `
  <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap"><span style="font-size:12px;color:var(--color-neutral-700)">クリティカルパス</span>
    ${chain.map((id, i) => `<span style="display:flex;align-items:center;gap:8px"><span class="tag" style="background:var(--color-accent-800);color:#fff">${id} ${esc(TK[id].title)}</span><span style="color:var(--color-neutral-500)">${i < chain.length - 1 ? "→" : "="}</span></span>`).join("")}
    <span style="font:600 18px var(--font-heading)">${total}h</span></div>
  <div style="display:grid;grid-template-columns:repeat(4,minmax(220px,1fr));gap:0;overflow-x:auto;border-top:1px solid var(--color-divider)">
    ${cols.map(({ d, items }) => `
    <div style="display:flex;flex-direction:column;gap:12px;padding:16px;border-right:1px solid var(--color-divider)">
      <div style="display:flex;flex-direction:column"><span style="font:600 20px var(--font-heading)">レベル ${d + 1}</span><span style="font-size:11.5px;color:var(--color-neutral-700)">${d === 0 ? "すぐ着手可能" : `レベル${d}の完了後`}</span></div>
      ${items.map((t) => `
      <div class="blueprint" style="padding:10px 12px;display:flex;flex-direction:column;gap:4px;border:${crit.has(t.id) ? "2px solid var(--color-accent)" : "1px solid var(--color-divider)"}">${CORNERS}
        <div style="display:flex;justify-content:space-between"><span style="font:600 13px var(--font-heading);color:var(--color-accent-700)">${t.id}</span><span style="font:600 13px var(--font-heading)">${t.h}h</span></div>
        <div style="font-size:13.5px;font-weight:500">${esc(t.title)}</div>
        <div style="font-size:11.5px;color:var(--color-neutral-700)">← ${t.deps.length ? t.deps.join(", ") : "依存なし"}</div>
      </div>`).join("")}
    </div>`).join("")}
  </div>`;
}

function step7(): string {
  const a = state.assign;
  const mv = memberViews(a);
  const v = state.variant[7];
  const capLine = (top: number) => `<div style="position:absolute;top:-${top}px;bottom:-${top}px;left:80%;width:1px;background:var(--color-text)"></div>`;
  const sortedSkills = (mid: string) => SKK.filter((k) => MEM[mid].sk[k]).sort((x, y) => MEM[mid].sk[y]! - MEM[mid].sk[x]!);

  if (v === 0) {
    const cols = "170px repeat(7,minmax(56px,1fr)) minmax(240px,1.6fr)";
    return `
    <div style="display:flex;flex-direction:column;border-top:1px solid var(--color-divider);overflow-x:auto">
      <div style="display:grid;grid-template-columns:${cols};min-width:900px">
        <div style="padding:10px 8px;font-size:11px;letter-spacing:.08em;color:var(--color-neutral-700)">メンバー</div>
        ${SKK.map((k) => `<div style="padding:10px 4px;font-size:11px;text-align:center;color:var(--color-neutral-700)">${SK[k]}</div>`).join("")}
        <div style="padding:10px 8px;font-size:11px;color:var(--color-neutral-700)">負荷（既存 + 今回割当）</div>
      </div>
      ${mv.map((m) => `
      <div style="display:grid;grid-template-columns:${cols};min-width:900px;border-top:1px solid var(--color-divider);align-items:stretch">
        <div style="padding:10px 8px;display:flex;flex-direction:column;justify-content:center"><span style="font-weight:500">${esc(m.name)}</span><span style="font-size:11.5px;color:var(--color-neutral-700)">${esc(m.role)}</span></div>
        ${SKK.map((k) => {
          const lv = MEM[m.id].sk[k] || 0;
          return `<div style="margin:3px;display:grid;place-items:center;font:600 18px var(--font-heading);background:${RAMP[lv]};color:${lv >= 4 ? "#fff" : lv ? "var(--color-accent-900)" : "var(--color-neutral-400)"}">${lv || "·"}</div>`;
        }).join("")}
        <div style="padding:10px 8px;display:flex;align-items:center;gap:10px"><div style="flex:1;height:14px;position:relative;border:1px solid var(--color-divider)"><div style="position:absolute;top:0;bottom:0;left:0;width:${m.baseW};background:var(--color-neutral-300)"></div><div style="position:absolute;top:0;bottom:0;left:${m.baseW};width:${m.newW};background:${m.barBg}"></div>${capLine(4)}</div><span style="font:600 17px var(--font-heading);width:46px;text-align:right;color:${m.pctFg}">${m.pct}%</span></div>
      </div>`).join("")}
      <div style="display:flex;gap:18px;padding:12px 8px;border-top:1px solid var(--color-divider);font-size:11.5px;color:var(--color-neutral-700);flex-wrap:wrap"><span>数字 = スキルレベル（1〜5）</span><span style="display:flex;align-items:center;gap:6px"><i style="width:12px;height:8px;background:var(--color-neutral-300)"></i>既存業務</span><span style="display:flex;align-items:center;gap:6px"><i style="width:12px;height:8px;background:var(--color-accent)"></i>今回の割当</span><span>縦線 = 上限 ${CAP}h</span></div>
    </div>`;
  }

  if (v === 1) {
    return `
    <div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:24px">
      ${mv.map((m) => `
      <div class="card blueprint" style="gap:12px;padding:16px">${CORNERS}
        <div style="display:flex;align-items:center;gap:10px"><span style="width:36px;height:36px;display:grid;place-items:center;border:1px solid var(--color-divider);font-size:15px">${esc(m.ini)}</span><div style="flex:1"><div class="card-title">${esc(m.name)}</div><div style="font-size:12px;color:var(--color-neutral-700)">${esc(m.role)}</div></div><span class="tag" style="background:${m.stBg};color:${m.stFg}">${m.status}</span></div>
        <div style="display:flex;align-items:flex-end;gap:6px"><span style="font:600 52px/0.9 var(--font-heading);color:${m.pctFg}">${m.pct}</span><span style="font:600 20px var(--font-heading);color:var(--color-neutral-600)">%</span><span style="flex:1"></span><span style="font-size:12px;color:var(--color-neutral-700)">${m.hTxt}</span></div>
        <div style="height:6px;position:relative;background:var(--color-neutral-200)"><div style="position:absolute;top:0;bottom:0;left:0;width:${m.baseW};background:var(--color-neutral-400)"></div><div style="position:absolute;top:0;bottom:0;left:${m.baseW};width:${m.newW};background:${m.barBg}"></div>${capLine(3)}</div>
        <div style="display:flex;flex-direction:column;gap:4px">
          ${sortedSkills(m.id).map((k) => { const lv = MEM[m.id].sk[k]!; return `<div style="display:flex;justify-content:space-between;font-size:12.5px"><span>${SK[k]}</span><span style="letter-spacing:2px;color:var(--color-accent)">${"●".repeat(lv)}${"○".repeat(5 - lv)}</span></div>`; }).join("")}
        </div>
        <div class="card-meta" style="flex-wrap:wrap">今回: ${m.mine.map((t) => `<span class="tag tag-neutral">${t.id}</span>`).join("")}${m.mine.length ? "" : "<span>なし</span>"}</div>
      </div>`).join("")}
    </div>`;
  }

  return `
  <div style="display:flex;flex-direction:column;gap:6px">
    <div style="display:grid;grid-template-columns:160px 1fr 60px;gap:14px;font-size:11px;color:var(--color-neutral-700)"><span></span><div style="position:relative;height:16px"><span style="position:absolute;left:0">0h</span><span style="position:absolute;left:40%;transform:translateX(-50%)">40h</span><span style="position:absolute;left:80%;transform:translateX(-50%);color:var(--color-text);font-weight:500">上限 ${CAP}h</span></div><span></span></div>
    ${mv.map((m) => {
      const base = MEM[m.id].base;
      const segs = [{ w: W(m.bp), bg: "var(--color-neutral-300)", fg: "var(--color-neutral-800)", label: "既存", tip: `既存業務 ${base}h` }].concat(
        m.mine.map((t, i) => ({
          w: W((t.h / CAP) * 100),
          bg: m.over ? (i % 2 ? WARN : "oklch(0.62 0.156 25)") : i % 2 ? "var(--color-accent-700)" : ACC,
          fg: "#fff", label: t.id, tip: `${t.id} ${t.title} ${t.h}h`,
        })),
      );
      const top = sortedSkills(m.id).slice(0, 2).map((k) => `${SK[k]} ${MEM[m.id].sk[k]}`).join(" · ");
      return `
      <div style="display:grid;grid-template-columns:160px 1fr 60px;gap:14px;align-items:center;padding:8px 0;border-top:1px solid var(--color-divider)">
        <div style="display:flex;flex-direction:column"><span style="font-weight:500">${esc(m.name)}</span><span style="font-size:11.5px;color:var(--color-neutral-700)">${top}</span></div>
        <div style="position:relative;height:34px;display:flex">${segs.map((sg) => `<div title="${esc(sg.tip)}" style="width:${sg.w};height:100%;background:${sg.bg};color:${sg.fg};border-right:1px solid var(--color-bg);display:flex;align-items:center;padding:0 6px;font:600 12px var(--font-heading);overflow:hidden;white-space:nowrap">${sg.label}</div>`).join("")}${capLine(4)}</div>
        <span style="font:600 20px var(--font-heading);text-align:right;color:${m.pctFg}">${m.pct}%</span>
      </div>`;
    }).join("")}
  </div>`;
}

function step8(): string {
  const a = state.assign;
  const v = state.variant[8];
  const rows = TASKS.map((t) => taskRow(t, a));
  const un = rows.filter((r) => !r.assigned);
  const head = `<div style="display:flex;gap:10px;flex-wrap:wrap;align-items:center"><span class="tag tag-accent">割当済 ${TASKS.length - un.length} / ${TASKS.length}</span><span class="tag" style="background:${WARN_BG};color:${WARN_FG}">未割当 ${un.length}</span><span style="font-size:12.5px;color:var(--color-neutral-700)">適合度 = スキル一致（最大66） + 負荷の余裕（最大44）</span></div>`;

  if (v === 0) {
    return head + `
    <table class="table">
      <thead><tr><th style="width:56px">ID</th><th>タスク</th><th style="width:130px">必要スキル</th><th style="width:130px">担当</th><th style="width:150px">適合度</th><th>根拠</th></tr></thead>
      <tbody>
        ${rows.map((r) => `<tr style="background:${r.assigned ? "transparent" : WARN_BG}"><td style="font:600 13px var(--font-heading);color:var(--color-accent-700)">${r.t.id}</td><td><div style="font-weight:500">${esc(r.t.title)}</div><div style="font-size:11.5px;color:var(--color-neutral-600)">${r.t.req} · ${r.t.h}h</div></td><td><span class="tag tag-outline">${SK[r.t.sk]} Lv${r.t.lv}</span></td><td style="font-weight:500;color:${r.whoFg}">${esc(r.who)}</td><td><div style="display:flex;align-items:center;gap:8px"><div style="flex:1;height:4px;background:var(--color-neutral-200)"><div style="height:100%;width:${r.assigned ? r.score : 0}%;background:var(--color-accent)"></div></div><span style="font:600 15px var(--font-heading);width:24px">${r.score}</span></div></td><td style="font-size:12.5px;color:var(--color-neutral-800)">${esc(r.reason)}</td></tr>`).join("")}
      </tbody>
    </table>`;
  }

  if (v === 1) {
    const mv = memberViews(a);
    const card = (r: TaskRow) => `<div style="padding:8px 10px;border:1px solid var(--color-divider);background:var(--color-bg);display:flex;flex-direction:column;gap:3px"><div style="display:flex;justify-content:space-between"><span style="font:600 12px var(--font-heading);color:var(--color-accent-700)">${r.t.id}</span><span style="font:600 12px var(--font-heading)">${r.t.h}h</span></div><div style="font-size:12.5px;font-weight:500">${esc(r.t.title)}</div><div style="font-size:11px;color:var(--color-neutral-600)">${SK[r.t.sk]} Lv${r.t.lv} · 適合 ${r.score}</div></div>`;
    const lane = (ini: string, name: string, pctTxt: string, pctFg: string, barW: string, barBg: string, bg: string, tasks: TaskRow[]) => `
      <div style="display:flex;flex-direction:column;gap:8px;padding:10px;border:1px solid var(--color-divider);background:${bg};min-height:420px">
        <div style="display:flex;align-items:center;gap:8px"><span style="width:26px;height:26px;display:grid;place-items:center;border:1px solid var(--color-divider);font-size:12px">${esc(ini)}</span><span style="flex:1;font-weight:500;font-size:13.5px">${esc(name)}</span><span style="font:600 16px var(--font-heading);color:${pctFg}">${pctTxt}</span></div>
        <div style="height:4px;background:var(--color-neutral-200);position:relative"><div style="position:absolute;inset:0 auto 0 0;width:${barW};background:${barBg}"></div></div>
        ${tasks.map(card).join("")}
      </div>`;
    return head + `
    <div style="display:grid;grid-template-columns:repeat(7,minmax(190px,1fr));gap:12px;overflow-x:auto;padding-bottom:8px">
      ${mv.map((m) => lane(m.ini, m.name, m.pct + "%", m.pctFg, Math.min(100, m.pct) + "%", m.barBg, "transparent", rows.filter((r) => a[r.t.id] === m.id))).join("")}
      ${lane("?", "未割当", un.length + "件", WARN, "0%", WARN, WARN_BG, un)}
    </div>`;
  }

  const tSel = TK[state.selTask] || TASKS[0];
  const sel = taskRow(tSel, a);
  const cands = MEMBERS.map((m) => ({ m, s: scoreOf(m, tSel, a), chosen: a[tSel.id] === m.id })).sort((x, y) => y.s.total - x.s.total);
  const cols = "130px 1fr 1fr 70px 60px 110px";
  return head + `
  <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:28px;align-items:start">
    <div data-scroll="list8" style="display:flex;flex-direction:column;border-top:1px solid var(--color-divider);max-height:640px;overflow:auto">
      ${rows.map((r) => `<div ${act("selTask", r.t.id)} style="display:grid;grid-template-columns:44px 1fr auto;gap:8px;align-items:center;padding:8px 10px;border-bottom:1px solid var(--color-divider);cursor:pointer;background:${state.selTask === r.t.id ? "var(--color-accent-100)" : "transparent"}"><span style="font:600 12.5px var(--font-heading);color:var(--color-accent-700)">${r.t.id}</span><span style="font-size:13px">${esc(r.t.title)}</span><span style="font-size:12px;color:${r.whoFg}">${esc(r.whoShort)}</span></div>`).join("")}
    </div>
    <div class="blueprint" style="padding:20px 22px;display:flex;flex-direction:column;gap:16px">${CORNERS}
      <div style="display:flex;flex-direction:column;gap:4px"><span style="font-size:11px;letter-spacing:.1em;color:var(--color-accent-700)">${tSel.id} · ${tSel.req} · ${tSel.h}h</span><h2 style="margin:0;font-size:28px">${esc(tSel.title)}</h2><span style="font-size:13px;color:var(--color-neutral-700)">必要スキル: ${SK[tSel.sk]} Lv${tSel.lv} · 依存: ${sel.deps}</span></div>
      <div style="display:grid;grid-template-columns:${cols};gap:10px;font-size:11px;color:var(--color-neutral-700);border-bottom:1px solid var(--color-divider);padding-bottom:6px"><span>候補</span><span>スキル一致</span><span>負荷の余裕</span><span>割当後</span><span>適合</span><span></span></div>
      ${cands.map(({ m, s, chosen }) => `
      <div style="display:grid;grid-template-columns:${cols};gap:10px;align-items:center;padding:4px 0;background:${chosen ? "var(--color-accent-100)" : "transparent"}">
        <div style="display:flex;flex-direction:column;padding-left:6px"><span style="font-weight:500;font-size:13.5px">${esc(m.name)}</span><span style="font-size:11px;color:var(--color-neutral-600)">${SK[tSel.sk]} Lv${s.lv}</span></div>
        <div style="height:8px;background:var(--color-neutral-200)"><div style="height:100%;width:${(s.skill / 66) * 100}%;background:var(--color-accent-700)"></div></div>
        <div style="height:8px;background:var(--color-neutral-200)"><div style="height:100%;width:${(s.load / 44) * 100}%;background:var(--color-accent-400)"></div></div>
        <span style="font:600 15px var(--font-heading);color:${s.after > 100 ? WARN : "var(--color-text)"}">${s.after}%</span>
        <span style="font:600 20px var(--font-heading)">${s.total}</span>
        ${chosen
          ? `<span class="tag tag-accent" style="justify-self:start">現在の担当</span>`
          : `<button class="btn btn-secondary" ${act("assign", tSel.id, m.id)} style="font-size:12.5px;padding:4px 10px;justify-self:start">この人にする</button>`}
      </div>`).join("")}
      <div style="font-size:12.5px;color:var(--color-neutral-700);border-top:1px solid var(--color-divider);padding-top:10px">${esc(sel.reason)}</div>
    </div>
  </div>`;
}

function step9(): string {
  const warns = buildWarnings(state.assign);
  if (!warns.length) {
    return `<div class="blueprint" style="padding:28px;display:flex;align-items:center;gap:16px">${CORNERS}<span style="font:600 40px var(--font-heading);color:var(--color-accent)">✓</span><div><h3 style="margin:0;font-size:24px">要対応の項目はありません</h3><div style="font-size:13px;color:var(--color-neutral-700)">すべてのタスクが割り当てられ、負荷・スキルの条件を満たしています。</div></div></div>`;
  }
  const subFont = "font:400 11px 'Barlow','Noto Sans JP',sans-serif;color:var(--color-neutral-600)";

  if (state.variant[9] === 0) {
    return `
    <div style="display:flex;flex-direction:column;border-top:1px solid var(--color-divider)">
      ${warns.map((w) => `
      <div style="display:grid;grid-template-columns:110px minmax(0,1fr) auto;gap:18px;align-items:center;padding:14px 4px;border-bottom:1px solid var(--color-divider)">
        <span class="tag" style="justify-self:start;background:${w.bg};color:${w.fg}">${w.kind}</span>
        <div><div style="font-weight:500">${esc(w.title)}</div><div style="font-size:12.5px;color:var(--color-neutral-700)">${esc(w.detail)}</div></div>
        <div style="display:flex;gap:8px;flex-wrap:wrap;justify-content:flex-end">
          ${w.actions.map((x) => `<button class="btn btn-secondary" ${x.attrs} style="flex-direction:column;align-items:flex-start;gap:0;padding:6px 12px"><span style="font-size:13px">${esc(x.label)}</span><span style="${subFont}">${esc(x.sub)}</span></button>`).join("")}
        </div>
      </div>`).join("")}
    </div>`;
  }

  const tiles: [string, string][] = [["未割当", WARN], ["過負荷", WARN], ["スキル不足", "var(--color-accent-700)"], ["要件が曖昧", "var(--color-neutral-700)"]];
  return `
  <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:18px">
    ${tiles.map(([k, fg]) => `<div class="blueprint" style="padding:16px 18px;display:flex;flex-direction:column;gap:2px">${CORNERS}<span style="font-size:12px;color:var(--color-neutral-700)">${k}</span><span style="font:600 56px/1 var(--font-heading);color:${fg}">${warns.filter((w) => w.kind === k).length}</span></div>`).join("")}
  </div>
  <div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(320px,1fr));gap:22px">
    ${warns.map((w) => `
    <div class="card blueprint" style="gap:10px;padding:16px">${CORNERS}
      <div style="height:3px;margin:-16px -16px 6px;background:${w.fg}"></div>
      <span class="card-kicker" style="color:${w.fg}">${w.kind}</span>
      <div class="card-title">${esc(w.title)}</div>
      <p class="card-body">${esc(w.detail)}</p>
      <div style="display:flex;flex-direction:column;gap:6px">
        ${w.actions.map((x) => `<button class="btn btn-secondary" ${x.attrs} style="justify-content:space-between;width:100%"><span>${esc(x.label)}</span><span style="${subFont}">${esc(x.sub)}</span></button>`).join("")}
      </div>
    </div>`).join("")}
  </div>`;
}

function step10(): string {
  const a = state.assign;
  const tSel = TK[state.selTask] || TASKS[0];
  const r = REQ[tSel.req];
  const para = PARA[r.p];
  const mid = a[tSel.id];
  const low = r.conf < 80;
  const note = r.id === "R-07"
    ? "数値目標（例：LCP 2.5秒以内）がないため、工数見積りの精度が低くなっています。顧客への確認を推奨します。"
    : "記述が抽象的なため、実装範囲の確認を推奨します。";
  return `
  <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:24px;align-items:start">
    <div data-scroll="list10" style="display:flex;flex-direction:column;border-top:1px solid var(--color-divider);max-height:680px;overflow:auto">
      ${TASKS.map((t) => `<div ${act("selTask", t.id)} style="display:grid;grid-template-columns:42px 1fr;gap:6px;padding:8px 10px;border-bottom:1px solid var(--color-divider);cursor:pointer;background:${state.selTask === t.id ? "var(--color-accent-100)" : "transparent"}"><span style="font:600 12.5px var(--font-heading);color:var(--color-accent-700)">${t.id}</span><span style="font-size:12.5px">${esc(t.title)}</span></div>`).join("")}
    </div>
    <div class="blueprint" data-scroll="doc10" style="padding:28px 32px;display:flex;flex-direction:column;gap:18px;max-height:680px;overflow:auto">${CORNERS}
      <div style="font-size:10px;letter-spacing:.12em;color:var(--color-neutral-600)">原文 · ${esc(FILE_NAME)}</div>
      ${docHtml(tSel.req, "selTaskByReq")}
    </div>
    <div style="display:flex;flex-direction:column;gap:14px">
      <div style="font-size:10px;letter-spacing:.12em;color:var(--color-neutral-600)">抽出の根拠</div>
      <div style="display:flex;flex-direction:column;gap:2px"><span style="font:600 14px var(--font-heading);color:var(--color-accent-700)">${tSel.id}</span><h3 style="margin:0;font-size:22px">${esc(tSel.title)}</h3></div>
      <div style="padding:12px 14px;background:var(--color-accent-100);font-size:13.5px;line-height:1.7">「${esc(para.t)}」</div>
      <div style="display:grid;grid-template-columns:80px 1fr;gap:6px 10px;font-size:13px">
        <span style="color:var(--color-neutral-700)">出典</span><span>${r.sec} · p.${r.page}</span>
        <span style="color:var(--color-neutral-700)">要件</span><span>${r.id} ${esc(r.title)}</span>
        <span style="color:var(--color-neutral-700)">信頼度</span><span style="color:${confFg(r)};font-weight:500">${r.conf}%</span>
        <span style="color:var(--color-neutral-700)">同要件</span><span>${TASKS.filter((x) => x.req === r.id).map((x) => x.id).join(" · ")}</span>
        <span style="color:var(--color-neutral-700)">担当</span><span>${mid ? esc(MEM[mid].name) : "未割当"}</span>
      </div>
      ${low ? `<div style="padding:10px 12px;border:1px solid oklch(0.75 0.120 25);font-size:12.5px;color:oklch(0.42 0.156 25)">${note}</div>` : ""}
    </div>
  </div>`;
}

function step11(): string {
  const a = state.assign;
  return `
  <div style="display:grid;grid-template-columns:repeat(4,minmax(220px,1fr));gap:14px;overflow-x:auto">
    ${KANBAN_COLS.map((c, ci) => {
      const cards = TASKS.filter((t) => state.kb[t.id] === c);
      return `
      <div class="s2t-kb-col" data-col="${c}" style="display:flex;flex-direction:column;gap:8px;padding:10px;min-height:520px;border:1px solid var(--color-divider);background:transparent">
        <div style="display:flex;align-items:baseline;gap:8px;padding:2px 2px 6px;border-bottom:2px solid var(--color-text)"><span style="font:600 20px var(--font-heading)">${c}</span><span style="font:600 16px var(--font-heading);color:var(--color-accent)">${cards.length}</span></div>
        ${cards.map((t) => {
          const mid = a[t.id];
          const m = mid ? MEM[mid] : undefined;
          const whoFg = m ? "var(--color-text)" : WARN;
          return `
          <div draggable="true" data-task="${t.id}" class="blueprint s2t-kb-card" style="padding:10px 12px;display:flex;flex-direction:column;gap:6px;background:var(--color-bg);cursor:grab">${CORNERS}
            <div style="display:flex;justify-content:space-between;align-items:center"><span style="font:600 12.5px var(--font-heading);color:var(--color-accent-700)">${t.id} · ${t.req}</span><span style="font:600 12.5px var(--font-heading)">${t.h}h</span></div>
            <div style="font-size:13.5px;font-weight:500">${esc(t.title)}</div>
            <div style="display:flex;align-items:center;gap:6px"><span style="width:22px;height:22px;display:grid;place-items:center;border:1px solid var(--color-divider);font-size:11px;color:${whoFg}">${m ? esc(m.ini) : "?"}</span><span style="font-size:12px;color:${whoFg}">${m ? esc(m.name) : "未割当"}</span><span style="flex:1"></span><button class="btn btn-ghost" ${act("openSource", t.id)} style="font-size:11.5px;padding:2px 4px">出典</button>${ci < 3 ? `<button class="btn btn-ghost" ${act("kbMove", t.id, KANBAN_COLS[ci + 1])} style="font-size:12px;padding:2px 6px">→</button>` : ""}</div>
          </div>`;
        }).join("")}
      </div>`;
    }).join("")}
  </div>`;
}

const STEP_RENDERERS = [step1, step2, step3, step4, step5, step6, step7, step8, step9, step10, step11];

// ─── 描画 ────────────────────────────────────────────────────────────────

const root = document.getElementById("s2t-root") as HTMLElement;

function render(): void {
  // 再描画で内部スクロール位置が失われないよう退避・復元する
  const scrolls: Record<string, number> = {};
  root.querySelectorAll<HTMLElement>("[data-scroll]").forEach((el) => (scrolls[el.dataset.scroll!] = el.scrollTop));

  root.innerHTML = `
  <div style="display:flex;min-height:100vh;color:var(--color-text)">
    <aside style="width:232px;flex:none;border-right:1px solid var(--color-divider);padding:18px 12px;display:flex;flex-direction:column;gap:20px;position:sticky;top:0;height:100vh;overflow:auto">
      <div style="display:flex;align-items:center;gap:10px;padding:0 8px">
        <div class="blueprint" style="width:28px;height:28px;display:grid;place-items:center;font:600 13px var(--font-heading);background:var(--color-accent-800);color:#fff;border-color:var(--color-accent)">S2</div>
        <div style="display:flex;flex-direction:column;line-height:1.1"><span style="font:600 18px var(--font-heading)">Spec2Task</span><span style="font-size:10.5px;color:var(--color-neutral-600)">仕様書 → タスク自動割当</span></div>
      </div>
      ${railHtml()}
      <div style="margin-top:auto;padding:12px 10px;border-top:1px solid var(--color-divider);display:flex;flex-direction:column;gap:8px">
        <div style="font-size:10px;letter-spacing:.12em;color:var(--color-neutral-600)">プロジェクト</div>
        <div style="font:600 16px var(--font-heading)">ECサイト リニューアル</div>
        <div style="display:flex;gap:4px">${MEMBERS.map((m) => `<span title="${esc(m.name)}" style="width:22px;height:22px;display:grid;place-items:center;font-size:11px;border:1px solid var(--color-divider)">${esc(m.ini)}</span>`).join("")}</div>
      </div>
    </aside>
    <main style="flex:1;min-width:0;display:flex;flex-direction:column">
      ${headerHtml()}
      <div style="padding:28px;display:flex;flex-direction:column;gap:24px">
        ${STEP_RENDERERS[state.step - 1]()}
      </div>
    </main>
  </div>`;

  root.querySelectorAll<HTMLElement>("[data-scroll]").forEach((el) => {
    const top = scrolls[el.dataset.scroll!];
    if (top != null) el.scrollTop = top;
  });
}

// ─── イベント（委譲） ─────────────────────────────────────────────────────

root.addEventListener("click", (e) => {
  const el = (e.target as HTMLElement).closest<HTMLElement>("[data-act]");
  if (!el || (el as HTMLButtonElement).disabled) return;
  const a = el.dataset.a ?? "";
  const b = el.dataset.b ?? "";
  switch (el.dataset.act) {
    case "go":
      if (Number(a) <= state.maxStep || Number(a) === state.step + 1) go(Number(a));
      break;
    case "variant":
      setState({ variant: { ...state.variant, [state.step]: Number(a) } });
      break;
    case "pickFile":
      setState({ file: true });
      break;
    case "selReq":
      setState({ selReq: a });
      break;
    case "selTask":
      setState({ selTask: a });
      break;
    case "selTaskByReq": {
      const t = TASKS.find((x) => x.req === a);
      if (t) setState({ selTask: t.id });
      break;
    }
    case "openSource":
      openSource(a);
      break;
    case "openSourceReq": {
      const t = TASKS.find((x) => x.req === a);
      if (t) openSource(t.id);
      break;
    }
    case "assign":
      setAssign(a, b);
      break;
    case "ack":
      ack(a);
      break;
    case "kbMove":
      setState({ kb: { ...state.kb, [a]: b as KanbanCol } });
      break;
  }
});

root.addEventListener("change", (e) => {
  const input = e.target as HTMLInputElement;
  if (input.name === "pol") state.policy = input.value;
});

// Kanban のドラッグ＆ドロップ。ドラッグ中に innerHTML を差し替えると
// ドラッグ元要素が消えて操作が中断されるため、ハイライトはクラス切替のみで行う。
let dragging: string | null = null;
const colOf = (e: Event) => (e.target as HTMLElement).closest<HTMLElement>(".s2t-kb-col");

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
  const col = colOf(e);
  if (!col) return;
  e.preventDefault();
  if (!col.classList.contains("is-hover")) {
    root.querySelectorAll(".s2t-kb-col.is-hover").forEach((el) => el.classList.remove("is-hover"));
    col.classList.add("is-hover");
  }
});
root.addEventListener("drop", (e) => {
  const col = colOf(e);
  if (!col) return;
  e.preventDefault();
  const id = e.dataTransfer?.getData("text/plain") || dragging;
  dragging = null;
  if (id && TK[id]) setState({ kb: { ...state.kb, [id]: col.dataset.col as KanbanCol } });
});

render();
if (state.step === 3 && state.prog < 100) runAnalysis();
