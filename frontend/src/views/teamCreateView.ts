// src/views/teamCreateView.ts
//
// 画面1: チーム作成ページ。
// チーム名と作成者自身の表示名を入力すると、その場でチームと管理者
// メンバーが作成され、セッション（HttpOnly Cookie）が発行される
// ＝作成者は追加の参加操作なしでそのままダッシュボードに入れる
// （統合テストで判明した実際の挙動。詳細は AUTH_INTEGRATION_TEST.md 参照）。
import { createTeam, createInvitation } from "../api/auth";
import { escapeHtml, mapAuthError } from "../auth/util";
import type { ApiError, Team, TeamMemberInfo } from "../types/auth";

export function renderTeamCreateView(
  container: HTMLElement,
  onCreated: (auth: { team: Team; member: TeamMemberInfo }) => void,
): void {
  container.innerHTML = `
    <div class="auth-screen-wrap">
      <div class="generate-card auth-card">
        <div class="generate-card-heading">
          <h1>タスみるへようこそ</h1>
          <p>チームを作成すると、招待URLでメンバーを追加できます（メールアドレスやパスワードは不要です）</p>
        </div>

        <div class="step-block">
          <div class="step-block-header">
            <div class="step-block-num">1</div>
            <div>
              <div class="step-block-title">チーム名を入力</div>
              <div class="step-block-sub">あとから変更できます</div>
            </div>
          </div>
          <input
            class="input-member"
            id="team-name-input"
            style="width: 100%; padding: 9px 12px; font-size: 13px;"
            placeholder="例: 開発チーム"
          />
        </div>

        <div class="step-block">
          <div class="step-block-header">
            <div class="step-block-num">2</div>
            <div>
              <div class="step-block-title">あなたの表示名を入力</div>
              <div class="step-block-sub">チーム内で表示される名前です</div>
            </div>
          </div>
          <input
            class="input-member"
            id="admin-name-input"
            style="width: 100%; padding: 9px 12px; font-size: 13px;"
            placeholder="例: 田中 一郎"
          />
        </div>

        <div class="step-block step-block-generate" id="team-create-action-row">
          <button class="btn-generate btn-generate-full" id="btn-create-team">
            <i data-lucide="plus"></i> チームを作成
          </button>
          <div id="team-create-error" class="auth-error" style="display: none"></div>
        </div>

        <div id="team-create-result" style="display: none"></div>
      </div>
    </div>
  `;

  const nameInput = container.querySelector("#team-name-input") as HTMLInputElement;
  const adminNameInput = container.querySelector("#admin-name-input") as HTMLInputElement;
  const createBtn = container.querySelector("#btn-create-team") as HTMLButtonElement;
  const errorBox = container.querySelector("#team-create-error") as HTMLElement;
  const resultBox = container.querySelector("#team-create-result") as HTMLElement;

  const showError = (message: string) => {
    errorBox.textContent = message;
    errorBox.style.display = "block";
  };

  createBtn.addEventListener("click", async () => {
    const name = nameInput.value.trim();
    const adminName = adminNameInput.value.trim();
    if (!name) {
      showError("チーム名を入力してください。");
      return;
    }
    if (!adminName) {
      showError("あなたの表示名を入力してください。");
      return;
    }

    errorBox.style.display = "none";
    createBtn.disabled = true;
    createBtn.innerHTML = `<i data-lucide="loader-circle" class="icon-spin"></i> 作成中...`;

    try {
      const { team, member } = await createTeam({
        name,
        admin_display_name: adminName,
      });

      // 作成直後に招待URLも1件発行してその場で共有できるようにする
      let inviteUrl: string | null = null;
      try {
        const invitation = await createInvitation(team.id);
        inviteUrl = `${window.location.origin}/?token=${invitation.token}`;
      } catch {
        /* 招待の即時発行に失敗しても、チーム作成自体は成功しているので続行する */
      }

      renderResult(resultBox, team.name, inviteUrl, () =>
        onCreated({ team, member }),
      );

      nameInput.disabled = true;
      adminNameInput.disabled = true;
      createBtn.style.display = "none";
    } catch (err) {
      const apiErr = err as ApiError;
      showError(mapAuthError(apiErr, "チームの作成に失敗しました。"));
    } finally {
      createBtn.disabled = false;
      createBtn.innerHTML = `<i data-lucide="plus"></i> チームを作成`;
    }
  });
}

function renderResult(
  resultBox: HTMLElement,
  teamName: string,
  inviteUrl: string | null,
  onProceed: () => void,
): void {
  resultBox.style.display = "block";
  resultBox.innerHTML = `
    <div class="step-block">
      <div class="step-block-header">
        <div class="step-block-num"><i data-lucide="check" style="font-size: 12px"></i></div>
        <div>
          <div class="step-block-title">「${escapeHtml(teamName)}」を作成しました</div>
          <div class="step-block-sub">招待URLをメンバーに共有してください</div>
        </div>
      </div>
      ${
        inviteUrl
          ? `<div class="invite-url-box">
               <span id="invite-url-text">${escapeHtml(inviteUrl)}</span>
               <button class="btn-modal-cancel" id="btn-copy-invite-url">
                 <i data-lucide="copy"></i> コピー
               </button>
             </div>`
          : `<div class="auth-hint">招待URLの発行に失敗しました。ダッシュボードの「チームメンバー」タブから再発行できます。</div>`
      }
    </div>

    <div class="step-block step-block-generate">
      <button class="btn-generate btn-generate-full" id="btn-proceed-to-dashboard">
        <i data-lucide="arrow-right"></i> ダッシュボードへ進む
      </button>
    </div>
  `;

  if (inviteUrl) {
    resultBox
      .querySelector("#btn-copy-invite-url")
      ?.addEventListener("click", () => copyToClipboard(inviteUrl));
  }
  resultBox
    .querySelector("#btn-proceed-to-dashboard")
    ?.addEventListener("click", onProceed);
}

async function copyToClipboard(text: string): Promise<void> {
  try {
    await navigator.clipboard.writeText(text);
  } catch {
    /* クリップボードAPIが使えない環境では黙って無視する */
  }
}
