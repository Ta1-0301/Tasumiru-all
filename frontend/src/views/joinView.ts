// src/views/joinView.ts
//
// 画面2: チーム参加ページ（招待URL `?token=...` を開いた際に表示）。
// 表示名だけを入力して参加する。メールアドレスやパスワードは要求しない。
// 参加に成功すると、セッションはバックエンドが HttpOnly Cookie で発行する
// ため、ここではレスポンスのメンバー/チーム情報を保持するだけで、
// トークン文字列を自分で読み書きすることはしない。
//
// 招待の事前プレビュー（参加前にチーム名を表示するAPI）はバックエンドに
// 存在しないため（統合テストで確認）、参加前はチーム名を出さず、
// 参加成功後に判明したチーム名をダッシュボード側で表示する。
import { joinTeam } from "../api/auth";
import { mapAuthError } from "../auth/util";
import type { ApiError, Team, TeamMemberInfo } from "../types/auth";

export function renderJoinView(
  container: HTMLElement,
  invitationToken: string,
  onJoined: (auth: { team: Team; member: TeamMemberInfo }) => void,
): void {
  container.innerHTML = `
    <div class="auth-screen-wrap">
      <div class="generate-card auth-card">
        <div class="generate-card-heading">
          <h1>チームに参加</h1>
          <p>表示名を入力して参加してください（メールアドレスやパスワードは不要です）</p>
        </div>

        <div class="step-block">
          <div class="step-block-header">
            <div class="step-block-num">1</div>
            <div>
              <div class="step-block-title">表示名を入力</div>
              <div class="step-block-sub">チーム内で表示される名前です</div>
            </div>
          </div>
          <input
            class="input-member"
            id="join-display-name-input"
            style="width: 100%; padding: 9px 12px; font-size: 13px;"
            placeholder="例: 田中 一郎"
          />
        </div>

        <div class="step-block step-block-generate">
          <button class="btn-generate btn-generate-full" id="btn-join-team">
            <i data-lucide="log-in"></i> 参加する
          </button>
          <div id="join-error" class="auth-error" style="display: none"></div>
        </div>
      </div>
    </div>
  `;

  const nameInput = container.querySelector(
    "#join-display-name-input",
  ) as HTMLInputElement;
  const joinBtn = container.querySelector("#btn-join-team") as HTMLButtonElement;
  const errorBox = container.querySelector("#join-error") as HTMLElement;

  const showError = (message: string) => {
    errorBox.textContent = message;
    errorBox.style.display = "block";
  };

  const submit = async () => {
    const displayName = nameInput.value.trim();
    if (!displayName) {
      showError("表示名を入力してください。");
      return;
    }

    errorBox.style.display = "none";
    joinBtn.disabled = true;
    joinBtn.innerHTML = `<i data-lucide="loader-circle" class="icon-spin"></i> 参加中...`;

    try {
      const { team, member } = await joinTeam(invitationToken, {
        display_name: displayName,
      });
      onJoined({ team, member });
    } catch (err) {
      const apiErr = err as ApiError;
      showError(mapAuthError(apiErr, "参加に失敗しました。"));
      joinBtn.disabled = false;
      joinBtn.innerHTML = `<i data-lucide="log-in"></i> 参加する`;
    }
  };

  joinBtn.addEventListener("click", submit);
  nameInput.addEventListener("keydown", (e) => {
    if (e.key === "Enter") submit();
  });
}
