// src/specToTasks/data.ts
//
// Spec to Tasks デモ用のサンプルデータとスコア計算。
// claude.ai/design「Spec to Tasks.dc.html」のスクリプト部をそのまま型付けしたもの。

export type SkillKey = "fe" | "be" | "db" | "infra" | "ux" | "sec" | "qa";

export interface Member {
  id: string;
  name: string;
  ini: string;
  role: string;
  /** 既存業務の工数（h） */
  base: number;
  sk: Partial<Record<SkillKey, number>>;
}

export interface Requirement {
  id: string;
  title: string;
  detail: string;
  cat: "機能" | "非機能" | "制約";
  pri: string;
  conf: number;
  sec: string;
  page: number;
  /** 原文段落ID */
  p: string;
}

export interface Task {
  id: string;
  title: string;
  req: string;
  sk: SkillKey;
  lv: number;
  h: number;
  deps: string[];
}

export interface DocPara {
  id: string;
  s?: string;
  t: string;
  r?: string;
}

export interface DocSection {
  h: string;
  paras: DocPara[];
}

export interface Step {
  n: number;
  t: string;
  g: number;
  d: string;
}

/** taskId -> memberId */
export type Assignment = Record<string, string | undefined>;

export const SK: Record<SkillKey, string> = {
  fe: "フロント",
  be: "バックエンド",
  db: "DB",
  infra: "インフラ",
  ux: "UI/UX",
  sec: "セキュリティ",
  qa: "QA",
};
export const SKK = Object.keys(SK) as SkillKey[];
export const CAP = 80;
export const WARN = "oklch(0.55 0.180 25)";
export const WARN_BG = "oklch(0.95 0.042 25)";
export const WARN_FG = "oklch(0.45 0.156 25)";

export const FILE_NAME = "EC_リニューアル_要件定義書_v1.2.pdf";

export const MEMBERS: Member[] = [
  { id: "m1", name: "佐藤 健", ini: "佐", role: "フロントエンド", base: 30, sk: { fe: 5, ux: 3, be: 1 } },
  { id: "m2", name: "鈴木 彩", ini: "鈴", role: "バックエンド", base: 50, sk: { be: 5, db: 4, infra: 2 } },
  { id: "m3", name: "高橋 翔", ini: "高", role: "フロントエンド", base: 20, sk: { fe: 4, qa: 3, be: 1 } },
  { id: "m4", name: "田中 由衣", ini: "田", role: "デザイナー", base: 40, sk: { ux: 5, fe: 2 } },
  { id: "m5", name: "伊藤 大輔", ini: "伊", role: "インフラ / セキュリティ", base: 46, sk: { infra: 5, sec: 4, be: 3 } },
  { id: "m6", name: "渡辺 陽菜", ini: "渡", role: "QA", base: 20, sk: { qa: 5, be: 2, db: 1 } },
];
export const MEM: Record<string, Member> = Object.fromEntries(MEMBERS.map((m) => [m.id, m]));

export const REQS: Requirement[] = [
  { id: "R-01", title: "会員登録・ログイン", detail: "メール / SNS（Google・LINE）", cat: "機能", pri: "高", conf: 96, sec: "§3.1", page: 4, p: "p31" },
  { id: "R-02", title: "商品検索・絞り込み", detail: "キーワード・カテゴリ・価格帯・在庫", cat: "機能", pri: "高", conf: 94, sec: "§3.2", page: 5, p: "p32" },
  { id: "R-03", title: "カート・購入フロー", detail: "3ステップ以内で購入完了", cat: "機能", pri: "高", conf: 97, sec: "§3.3", page: 6, p: "p33" },
  { id: "R-04", title: "決済", detail: "クレジットカード・コンビニ決済", cat: "機能", pri: "高", conf: 91, sec: "§3.4", page: 7, p: "p34" },
  { id: "R-05", title: "注文履歴・配送状況", detail: "マイページで確認", cat: "機能", pri: "中", conf: 86, sec: "§3.5", page: 8, p: "p35" },
  { id: "R-06", title: "商品管理", detail: "登録・編集・公開設定", cat: "機能", pri: "中", conf: 90, sec: "§4.1", page: 10, p: "p41" },
  { id: "R-07", title: "ページ表示の高速化", detail: "数値目標の記載なし — 要確認", cat: "非機能", pri: "高", conf: 62, sec: "§5.1", page: 12, p: "p51" },
  { id: "R-08", title: "PCI DSS 準拠", detail: "決済処理の構成", cat: "非機能", pri: "高", conf: 78, sec: "§5.3", page: 13, p: "p53" },
  { id: "R-09", title: "マルチデバイス対応", detail: "PC・スマートフォン・タブレット", cat: "非機能", pri: "中", conf: 93, sec: "§5.2", page: 12, p: "p52" },
  { id: "R-10", title: "2027年3月末リリース", detail: "段階リリースなし", cat: "制約", pri: "高", conf: 99, sec: "§1.3", page: 2, p: "p13" },
];
export const REQ: Record<string, Requirement> = Object.fromEntries(REQS.map((r) => [r.id, r]));

export const TASKS: Task[] = [
  { id: "T-01", title: "認証API設計・実装", req: "R-01", sk: "be", lv: 4, h: 16, deps: [] },
  { id: "T-02", title: "ログイン・会員登録画面", req: "R-01", sk: "fe", lv: 3, h: 12, deps: ["T-01"] },
  { id: "T-03", title: "SNSログイン連携（OAuth）", req: "R-01", sk: "be", lv: 4, h: 10, deps: ["T-01"] },
  { id: "T-04", title: "商品検索API・インデックス", req: "R-02", sk: "be", lv: 4, h: 20, deps: [] },
  { id: "T-05", title: "検索UI・絞り込み", req: "R-02", sk: "fe", lv: 3, h: 14, deps: ["T-04"] },
  { id: "T-06", title: "カート機能", req: "R-03", sk: "fe", lv: 3, h: 12, deps: [] },
  { id: "T-07", title: "購入フローUI設計", req: "R-03", sk: "ux", lv: 4, h: 8, deps: [] },
  { id: "T-08", title: "決済ゲートウェイ連携", req: "R-04", sk: "sec", lv: 4, h: 18, deps: ["T-06"] },
  { id: "T-09", title: "注文履歴画面", req: "R-05", sk: "fe", lv: 2, h: 8, deps: ["T-10"] },
  { id: "T-10", title: "配送ステータス連携API", req: "R-05", sk: "be", lv: 3, h: 10, deps: [] },
  { id: "T-11", title: "管理画面：商品登録", req: "R-06", sk: "fe", lv: 3, h: 16, deps: ["T-04"] },
  { id: "T-12", title: "性能目標の策定・計測", req: "R-07", sk: "infra", lv: 3, h: 12, deps: [] },
  { id: "T-13", title: "PCI DSS 準拠レビュー", req: "R-08", sk: "sec", lv: 4, h: 14, deps: ["T-08"] },
  { id: "T-14", title: "レスポンシブ対応", req: "R-09", sk: "ux", lv: 3, h: 10, deps: ["T-07"] },
  { id: "T-15", title: "E2Eテスト", req: "R-03", sk: "qa", lv: 4, h: 16, deps: ["T-06", "T-08"] },
  { id: "T-16", title: "インフラ・CI/CD構築", req: "R-10", sk: "infra", lv: 4, h: 12, deps: [] },
];
export const TK: Record<string, Task> = Object.fromEntries(TASKS.map((t) => [t.id, t]));

export const INIT_ASSIGN: Assignment = {
  "T-01": "m2", "T-02": "m3", "T-04": "m6", "T-05": "m1", "T-06": "m1", "T-07": "m4", "T-08": "m5",
  "T-09": "m3", "T-11": "m3", "T-13": "m5", "T-14": "m4", "T-15": "m6", "T-16": "m5",
};

export const UNASSIGNED_REASON: Record<string, string> = {
  "T-03": "バックエンドLv4の担当者（鈴木）は負荷83%。これ以上の割当で上限超過",
  "T-10": "§3.5に配送業者の指定がなく、連携方式が未確定",
  "T-12": "R-07に数値目標がなく、候補（伊藤）も過負荷",
};

export const DOC: DocSection[] = [
  { h: "1. 概要", paras: [
    { id: "p11", t: "本書は、株式会社ミナト商事が運営するECサイト「minato store」のリニューアルにおける要件を定義する。" },
    { id: "p13", s: "§1.3", t: "本システムは2027年3月末までに本番リリースすること。段階リリースは行わない。", r: "R-10" },
  ] },
  { h: "3. 機能要件", paras: [
    { id: "p31", s: "§3.1", t: "利用者はメールアドレスまたはSNSアカウント（Google / LINE）で会員登録・ログインできること。", r: "R-01" },
    { id: "p32", s: "§3.2", t: "キーワード検索に加え、カテゴリ・価格帯・在庫有無による絞り込みを提供する。", r: "R-02" },
    { id: "p33", s: "§3.3", t: "カートへの追加・数量変更・削除を行い、3ステップ以内で購入を完了できること。", r: "R-03" },
    { id: "p34", s: "§3.4", t: "クレジットカードおよびコンビニ決済に対応する。カード情報は自社サーバーに保持しない。", r: "R-04" },
    { id: "p35", s: "§3.5", t: "会員は過去の注文履歴と配送状況をマイページで確認できること。", r: "R-05" },
  ] },
  { h: "4. 管理機能", paras: [
    { id: "p41", s: "§4.1", t: "管理者は商品の登録・編集・公開設定を管理画面から行える。", r: "R-06" },
  ] },
  { h: "5. 非機能要件", paras: [
    { id: "p51", s: "§5.1", t: "ページは高速に表示されること。", r: "R-07" },
    { id: "p52", s: "§5.2", t: "PC・スマートフォン・タブレットで最適に表示されること。", r: "R-09" },
    { id: "p53", s: "§5.3", t: "決済に関わる処理はPCI DSSに準拠した構成とする。", r: "R-08" },
  ] },
];
export const PARA: Record<string, DocPara> = {};
DOC.forEach((d) => d.paras.forEach((p) => (PARA[p.id] = p)));

export const STEPS: Step[] = [
  { n: 1, t: "仕様書をアップロード", g: 0, d: "要件定義書・仕様書を読み込みます" },
  { n: 2, t: "AI分析開始", g: 0, d: "分析条件を確認して開始します" },
  { n: 3, t: "進捗表示", g: 0, d: "AIが仕様書を読み進めています" },
  { n: 4, t: "要件抽出", g: 1, d: "仕様書から要件を抽出しました。信頼度の低い項目は要確認です" },
  { n: 5, t: "タスク分解", g: 1, d: "各要件を実装タスクに分解し、工数と必要スキルを見積もりました" },
  { n: 6, t: "依存関係", g: 1, d: "着手順序とクリティカルパス" },
  { n: 7, t: "スキル・負荷", g: 2, d: "メンバーごとのスキルレベルと、既存業務を含めた負荷" },
  { n: 8, t: "自動割り当て", g: 2, d: "スキル適合度と負荷のバランスで担当者を割り当てました" },
  { n: 9, t: "未割当・警告", g: 2, d: "人の判断が必要な項目です。提案をクリックするとすぐ反映されます" },
  { n: 10, t: "出典を確認", g: 3, d: "すべてのタスクは仕様書の該当箇所に紐づいています" },
  { n: 11, t: "Kanban", g: 3, d: "ドラッグ、または → でステータスを更新" },
];
export const GROUPS = ["取り込み", "分析", "割り当て", "管理"];
export const VARIANTS: Record<number, string[]> = {
  4: ["テーブル", "原文と並列", "カテゴリ別"],
  7: ["スキル表", "メンバーカード", "負荷バー"],
  8: ["割当テーブル", "メンバー別", "根拠つき"],
  9: ["警告リスト", "サマリー"],
};

/** [フェーズ名, 開始%, 終了%] */
export const PHASES: [string, number, number][] = [
  ["テキスト抽出", 0, 15],
  ["文書構造の解析", 15, 32],
  ["要件の抽出", 32, 52],
  ["タスクへの分解", 52, 68],
  ["依存関係の推定", 68, 82],
  ["割当の最適化", 82, 100],
];
/** [表示される進捗%, メッセージ] */
export const LOGS: [number, string][] = [
  [3, "PDFからテキストを抽出 — 24ページ / 18,420字"],
  [16, "章構成を検出 — 5章 32節"],
  [34, "§3.1 会員機能 → R-01 を抽出"],
  [40, "§3.4 決済 → R-04 を抽出"],
  [46, "§5.1「高速に表示」— 数値目標なし（要確認）"],
  [54, "R-01 を 3タスクに分解"],
  [63, "合計 16タスク / 208h と見積り"],
  [70, "依存関係 10件を推定"],
  [84, "スキル×負荷で最適化 — 96通りを評価"],
  [97, "13件を割当 / 3件は未割当"],
];

export const KANBAN_COLS = ["未着手", "進行中", "レビュー", "完了"] as const;
export type KanbanCol = (typeof KANBAN_COLS)[number];
export const KANBAN_INIT: Record<string, KanbanCol> = Object.fromEntries(
  TASKS.map((t) => [t.id, "未着手" as KanbanCol]),
);
Object.assign(KANBAN_INIT, { "T-01": "進行中", "T-16": "進行中", "T-07": "レビュー" });

/** スキルレベル 0〜5 のヒートマップ色 */
export const RAMP = [
  "transparent",
  "var(--color-accent-100)",
  "var(--color-accent-200)",
  "var(--color-accent-300)",
  "var(--color-accent-500)",
  "var(--color-accent-700)",
];

/** 既存業務 + 割当タスクの合計工数。ex を指定するとそのタスクを除いて計算する */
export function hoursOf(mid: string, a: Assignment, ex?: string): number {
  let h = MEM[mid].base;
  TASKS.forEach((t) => {
    if (a[t.id] === mid && t.id !== ex) h += t.h;
  });
  return h;
}

export function pctOf(mid: string, a: Assignment): number {
  return Math.round((hoursOf(mid, a) / CAP) * 100);
}

export interface Score {
  total: number;
  /** スキル一致（最大66） */
  skill: number;
  /** 負荷の余裕（最大44） */
  load: number;
  lv: number;
  /** 割当後の負荷% */
  after: number;
}

export function scoreOf(m: Member, t: Task, a: Assignment): Score {
  const lv = m.sk[t.sk] || 0;
  const skill = Math.min(lv / t.lv, 1.2) * 55;
  const after = Math.round(((hoursOf(m.id, a, t.id) + t.h) / CAP) * 100);
  const load = Math.max(0, 110 - after) * 0.4;
  return {
    total: Math.max(1, Math.min(99, Math.round(skill + load))),
    skill: Math.round(skill),
    load: Math.round(load),
    lv,
    after,
  };
}
