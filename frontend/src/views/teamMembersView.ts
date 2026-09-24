// src/views/teamMembersView.ts
//
// 画面4: チームメンバーページ（ダッシュボード内の新規タブ）。
// 既存の「メンバー管理」画面（AIタスク割り当て用のスキルプロファイル）とは
// 別物で、こちらは「実際にこのチームへログイン可能なメンバー」の一覧・
// 招待発行・削除を扱う。
//
// 招待発行・メンバー削除はセッションCookieだけで認可される
// （バックエンドが member.is_admin を判定する。統合テストで確認済み）。
// フロント側はあくまで「管理者ならボタンを出す」というUI上の親切であり、
// 実際の可否は常にバックエンドが判定する（UIを隠すことを権限制御の
// 代わりにはしない）。
import {
  createInvitation,
  deleteMember,
  listTeamMembers,
  revokeSession,
} from "../api/auth";
import { getCurrentAuth } from "../auth/session";
import { escapeHtml, mapAuthError } from "../auth/util";
import type { ApiError, TeamMemberInfo } from "../types/auth";

export async function renderTeamMembersView(
  container: HTMLElement,
  onSignedOut: () => void,
): Promise<void> {
  const auth = getCurrentAuth();
  if (!auth) {
    container.innerHTML = `<div class="sec-body" style="padding: 20px">セッションが確認できませんでした。</div>`;
    return;
  }

  container.innerHTML = `
    <div class="sec-header sec-header-page">
      <div class="sec-header-icon"><i data-lucide="users-round"></i></div>
      <span class="sec-header-title">チームメンバー — ${escapeHtml(auth.team.name)}</span>
    </div>
    <div class="sec-body" style="padding: 20px; max-width: 640px">
      <div id="team-invite-section" style="margin-bottom: 16px"></div>
      <div class="member-list" id="team-member-list" style="max-height: none"></div>
      <div style="margin-top: 20px; border-top: 0.5px solid #f3ece0; padding-top: 16px">
        <button class="btn-modal-cancel" id="btn-sign-out">
          <i data-lucide="log-out"></i> このデバイスをサインアウト
        </button>
      </div>
    </div>
  `;

  if (auth.member.is_admin) {
    renderInviteSection(container, auth.team.id);
  }
  await loadMembers(container, auth.team.id, auth.member.id, auth.member.is_admin);

  container.querySelector("#btn-sign-out")?.addEventListener("click", async () => {
    const btn = container.querySelector("#btn-sign-out") as HTMLButtonElement;
    btn.disabled = true;
    try {
      await revokeSession();
    } catch {
      /* サインアウトはベストエフォート。失敗してもローカルの状態は破棄する */
    }
    onSignedOut();
  });
}

function renderInviteSection(container: HTMLElement, teamId: string): void {
  const section = container.querySelector("#team-invite-section") as HTMLElement;
  section.innerHTML = `
    <button class="btn-add-member" id="btn-create-invite">
      <i data-lucide="link"></i> 招待URLを発行
    </button>
    <div id="invite-result" style="margin-top: 8px; display: none"></div>
  `;
  section
    .querySelector("#btn-create-invite")
    ?.addEventListener("click", () => handleCreateInvite(section, teamId));
}

async function handleCreateInvite(
  section: HTMLElement,
  teamId: string,
): Promise<void> {
  const btn = section.querySelector("#btn-create-invite") as HTMLButtonElement;
  const resultBox = section.querySelector("#invite-result") as HTMLElement;

  btn.disabled = true;
  try {
    const invitation = await createInvitation(teamId);
    const inviteUrl = `${window.location.origin}/?token=${invitation.token}`;

    resultBox.style.display = "block";
    resultBox.innerHTML = `
      <div class="invite-url-box">
        <span>${escapeHtml(inviteUrl)}</span>
        <button class="btn-modal-cancel" id="btn-copy-new-invite">
          <i data-lucide="copy"></i> コピー
        </button>
      </div>
    `;
    resultBox.querySelector("#btn-copy-new-invite")?.addEventListener("click", () => {
      navigator.clipboard.writeText(inviteUrl).catch(() => {});
    });
  } catch (err) {
    const apiErr = err as ApiError;
    resultBox.style.display = "block";
    resultBox.textContent = mapAuthError(apiErr, "招待URLの発行に失敗しました。");
  } finally {
    btn.disabled = false;
  }
}

async function loadMembers(
  container: HTMLElement,
  teamId: string,
  selfMemberId: string,
  isAdmin: boolean,
): Promise<void> {
  const listEl = container.querySelector("#team-member-list") as HTMLElement;
  listEl.innerHTML = `<div class="auth-hint">読み込み中...</div>`;

  try {
    const members = await listTeamMembers(teamId);
    renderMemberList(container, listEl, members, teamId, selfMemberId, isAdmin);
  } catch (err) {
    const apiErr = err as ApiError;
    listEl.innerHTML = `<div class="auth-error">${escapeHtml(mapAuthError(apiErr, "メンバー一覧の取得に失敗しました。"))}</div>`;
  }
}

function renderMemberList(
  container: HTMLElement,
  listEl: HTMLElement,
  members: TeamMemberInfo[],
  teamId: string,
  selfMemberId: string,
  isAdmin: boolean,
): void {
  listEl.innerHTML = "";

  members.forEach((member) => {
    const card = document.createElement("div");
    card.className = "member-card";
    const isSelf = member.id === selfMemberId;

    card.innerHTML = `
      <div>
        <span class="m-info-name">${escapeHtml(member.display_name)}</span>
        ${isSelf ? '<span class="m-info-load">あなた</span>' : ""}
        ${member.is_admin ? '<span class="m-info-load">管理者</span>' : ""}
      </div>
      ${
        isAdmin && !isSelf
          ? '<button class="btn-del-member" data-id="' +
            member.id +
            '"><i data-lucide="trash"></i></button>'
          : ""
      }
    `;

    card.querySelector(".btn-del-member")?.addEventListener("click", async () => {
      if (!confirm(`${member.display_name} さんをチームから削除しますか？`)) return;
      try {
        await deleteMember(member.id);
        await loadMembers(container, teamId, selfMemberId, isAdmin);
      } catch (err) {
        const apiErr = err as ApiError;
        alert(mapAuthError(apiErr, "メンバーの削除に失敗しました。"));
      }
    });

    listEl.appendChild(card);
  });
}
