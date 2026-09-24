// src/views/pipelineMembersView.ts
//
// 画面: メンバー管理（Phase 6の構造化メンバーモデルを可視化）。
// 表示: 氏名 / スキル / スキルレベル / 稼働可能時間 / 現在の稼働 / 制約。
// §3の認証チームメンバー画面（チームメンバー）や、legacyの簡易メンバー管理
// （タスク生成用のスキル入力）とは別物 — こちらはPhase6パイプラインの
// 構造化データをそのまま表示する。存在しない値は捏造せず「不明」と表示する。
//
// 【プロジェクトによる絞り込み】バックエンドには「チームの全プロジェクト
// 一覧」を返すエンドポイントが存在しない（POST /api/projects と
// GET /api/projects/{id} のみ）。そのため、選択候補はこのブラウザが
// これまでに作成/参照したプロジェクトのローカルな記録
// （projectService.listKnownProjects()）に限られる。他デバイスで作成した
// プロジェクトは選択肢に出せない — これはフロント実装の制約ではなく、
// バックエンドAPIの制約であるため、隠さずそのまま画面に注記する。
import { getPipelineMembers, getMembersForProject, remainingCapacity } from "../services/memberService";
import { escapeHtml } from "../auth/util";
import {
  IS_SAMPLE_DATA,
  getActiveProjectId,
  listKnownProjects,
  type KnownProject,
} from "../services/projectService";
import {
  sampleDataBannerHtml,
  pipelineErrorBannerHtml,
  extractErrorMessage,
  formatPercent,
  UNAVAILABLE_TEXT,
} from "../pipeline/format";
import type { MemberConstraint, PipelineMember } from "../types/pipeline";

function projectLabel(project: KnownProject, activeProjectId: string | null): string {
  const base = project.name ? project.name : `（無題のプロジェクト・ID: ${project.id.slice(0, 8)}…）`;
  return project.id === activeProjectId ? `${base}（現在の生成対象）` : base;
}

// 選択候補一覧を組み立てる。アクティブなプロジェクトが既知一覧に
// まだ無い場合（レジストリが後から追加された等）でも必ず選べるようにする。
function buildSelectableProjects(activeProjectId: string | null): KnownProject[] {
  const known = listKnownProjects();
  if (activeProjectId && !known.some((p) => p.id === activeProjectId)) {
    return [{ id: activeProjectId, name: null }, ...known];
  }
  return known;
}

const CONSTRAINT_LABEL: Record<string, (c: MemberConstraint) => string> = {
  scope_restriction: (c) => `担当範囲の制約${c.value ? `: ${escapeHtml(c.value)}` : ""}`,
  day_unavailable: (c) => `稼働不可日: ${c.value ? escapeHtml(c.value) : UNAVAILABLE_TEXT}`,
  max_hours_per_week: (c) => `週の上限稼働時間: ${c.max_hours ?? UNAVAILABLE_TEXT}h`,
  requires_review: () => `人によるレビューが必要`,
};

function constraintHtml(constraint: MemberConstraint): string {
  const formatter = CONSTRAINT_LABEL[constraint.type];
  return `<span class="m-tag">${formatter ? formatter(constraint) : escapeHtml(constraint.type)}</span>`;
}

function memberCardHtml(member: PipelineMember): string {
  const workloadPct =
    member.availability.available_hours_per_week > 0
      ? (member.availability.current_assigned_hours / member.availability.available_hours_per_week) * 100
      : null;
  const remaining = remainingCapacity(member);

  return `
    <div class="member-directory-card">
      <div class="member-directory-header">
        <span class="req-card-id" style="font-size:13px">${escapeHtml(member.name)}</span>
        <span class="auth-hint">経験年数: ${member.experience_years !== null ? `${member.experience_years}年` : "不明"}</span>
      </div>

      <div class="member-directory-section">
        <div class="req-card-tasks-label">スキル</div>
        ${
          member.skills.length > 0
            ? `<div class="m-tags">${member.skills
                .map(
                  (s) =>
                    `<span class="m-tag">${escapeHtml(s.skill)} Lv.${s.level}${
                      s.experience_years !== null ? `（${s.experience_years}年）` : ""
                    }</span>`,
                )
                .join("")}</div>`
            : `<span class="auth-hint">スキル情報なし</span>`
        }
      </div>

      <div class="member-directory-section">
        <div class="req-card-tasks-label">稼働状況</div>
        <div class="score-bar-row">
          <span class="score-bar-label">稼働率</span>
          <div class="score-bar-track"><div class="score-bar-fill" style="width:${Math.min(100, workloadPct ?? 0)}%"></div></div>
          <span class="score-bar-value">${formatPercent(workloadPct)}</span>
        </div>
        <div class="auth-hint" style="margin-top:4px">
          稼働可能: ${member.availability.available_hours_per_week}h/週
          現在の割当: ${member.availability.current_assigned_hours}h
          残キャパシティ: ${remaining}h
        </div>
        <div class="auth-hint">
          稼働曜日: ${
            member.availability.working_days.length > 0
              ? member.availability.working_days.map(escapeHtml).join("・")
              : UNAVAILABLE_TEXT
          }
        </div>
      </div>

      <div class="member-directory-section">
        <div class="req-card-tasks-label">制約</div>
        ${
          member.constraints.length > 0
            ? `<div class="m-tags">${member.constraints.map(constraintHtml).join("")}</div>`
            : `<span class="auth-hint">制約なし</span>`
        }
      </div>
    </div>
  `;
}

// プロジェクト切り替え時、先に発行した（=まだ解決していない）古いリクエストが
// 後から解決して新しい選択結果を上書きしてしまう競合状態を防ぐための
// 単調増加トークン。「最後に発行したリクエストの結果だけを反映する」という
// 単純なルールで、初期表示のロードと切り替え操作が競合しても常に画面が
// 直近の選択と一致するようにする。
let latestMembersRequestId = 0;

async function loadAndRenderMembers(
  listContainer: HTMLElement,
  projectId: string | null,
): Promise<void> {
  const requestId = ++latestMembersRequestId;
  listContainer.innerHTML = `読み込み中...`;

  let members: PipelineMember[];
  try {
    members = projectId ? await getMembersForProject(projectId) : await getPipelineMembers();
  } catch (err) {
    if (requestId !== latestMembersRequestId) return; // 新しい選択に追い越された
    listContainer.innerHTML = pipelineErrorBannerHtml(
      extractErrorMessage(err, "メンバーデータの取得に失敗しました。"),
    );
    return;
  }
  if (requestId !== latestMembersRequestId) return; // 新しい選択に追い越された

  if (members.length === 0) {
    listContainer.innerHTML = `<div class="auth-hint">このプロジェクトにはメンバーデータがありません。</div>`;
    return;
  }

  listContainer.innerHTML = `
    <div class="member-directory-grid">
      ${members.map(memberCardHtml).join("")}
    </div>
  `;
}

export async function renderPipelineMembersView(container: HTMLElement): Promise<void> {
  const activeProjectId = getActiveProjectId();
  const selectableProjects = buildSelectableProjects(activeProjectId);
  const hasSelectableProjects = selectableProjects.length > 0;

  container.innerHTML = `
    <div class="sec-header sec-header-page">
      <div class="sec-header-icon"><i data-lucide="users"></i></div>
      <span class="sec-header-title">メンバー管理（スキル/稼働モデル）</span>
    </div>
    <div class="sec-body" style="padding: 20px">
      ${IS_SAMPLE_DATA ? sampleDataBannerHtml() : ""}
      ${
        hasSelectableProjects
          ? `
            <div style="display:flex;align-items:center;gap:8px;margin-bottom:8px;flex-wrap:wrap">
              <label for="pm-project-filter" style="font-size:12px;font-weight:600;color:var(--brand)">プロジェクトで絞り込み</label>
              <select class="project-select" id="pm-project-filter" style="width:auto;min-width:220px">
                ${selectableProjects
                  .map(
                    (p) =>
                      `<option value="${escapeHtml(p.id)}" ${p.id === activeProjectId ? "selected" : ""}>${escapeHtml(projectLabel(p, activeProjectId))}</option>`,
                  )
                  .join("")}
              </select>
              <span class="auth-hint">※このブラウザで作成/使用したプロジェクトのみ選択できます（バックエンドに一覧APIが無いため）</span>
            </div>
          `
          : ""
      }
      ${
        selectableProjects.length > 1
          ? `
            <div class="sample-data-banner" style="margin-bottom:14px">
              <i data-lucide="triangle-alert"></i>
              <span>
                既知の制限: 現在のバックエンドの GET /api/projects/{id}/members は project_id を無視し、
                チーム内で最後に保存されたメンバー一覧を返す（実機で確認済み: 直接 curl で project_id を
                変えて問い合わせても同一の結果が返る）。そのため、上のプロジェクトをどれに切り替えても
                同じメンバー一覧が表示される場合がある。フロントエンドは正しく各プロジェクトのIDを指定して
                問い合わせているため、この画面側の実装の問題ではない — バックエンド側でメンバー保存を
                プロジェクト単位にスコープしてもらう必要がある。
              </span>
            </div>
          `
          : ""
      }
      <div id="member-directory-container">読み込み中...</div>
    </div>
  `;

  const listContainer = container.querySelector("#member-directory-container") as HTMLElement;
  const filterSelect = container.querySelector("#pm-project-filter") as HTMLSelectElement | null;

  filterSelect?.addEventListener("change", () => {
    loadAndRenderMembers(listContainer, filterSelect.value || null);
  });

  const initialProjectId = hasSelectableProjects ? (filterSelect?.value ?? selectableProjects[0].id) : null;
  await loadAndRenderMembers(listContainer, initialProjectId);
}
