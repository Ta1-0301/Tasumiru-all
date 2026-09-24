// src/views/assignmentsView.ts
//
// 画面: アサイン推奨（Assignment recommendation, Phase 7の結果を可視化）。
// 表示: タスク / 推奨メンバー / スコア / スキル一致度 / 稼働状況 / 経験 /
//       空き状況 / 理由。[承認] [担当者を変更] を許可する。
// AIの推奨理由は常に表示し、隠さない。
//
// 【重要】[承認]/[担当者を変更] は、この確定結果を書き込むHTTPエンドポイント
// がバックエンドに存在しないため、この画面内だけのローカル状態としてのみ
// 反映する（Kanbanのステータス変更と同じ制約）。バックエンドへの永続化は行わない。
import { getAssignments } from "../services/assignmentService";
import { getPipelineTasks } from "../services/taskService";
import { getPipelineMembers } from "../services/memberService";
import { escapeHtml } from "../auth/util";
import { IS_SAMPLE_DATA } from "../services/projectService";
import {
  sampleDataBannerHtml,
  pipelineErrorBannerHtml,
  extractErrorMessage,
  assignmentStatusBadgeHtml,
  scoreBarHtml,
  UNAVAILABLE_TEXT,
} from "../pipeline/format";
import type { CandidateScore, FinalAssignment, PipelineMember, PipelineTask } from "../types/pipeline";

interface LocalDecision {
  assigned_member_id: string | null;
  decided_by: "ai" | "human";
  overridden: boolean;
  override_reason: string | null;
  accepted: boolean;
}

function memberName(memberId: string | null, members: PipelineMember[]): string {
  if (!memberId) return "未定";
  return members.find((m) => m.id === memberId)?.name ?? memberId;
}

function candidateScoreRowHtml(candidate: CandidateScore, members: PipelineMember[]): string {
  return `
    <div class="candidate-score-card">
      <div class="candidate-score-name">${escapeHtml(memberName(candidate.member_id, members))} <span class="auth-hint">総合 ${Math.round(candidate.score)}</span></div>
      ${scoreBarHtml(candidate.skill_match, "スキル一致")}
      ${scoreBarHtml(candidate.workload_score, "稼働状況")}
      ${scoreBarHtml(candidate.experience_score, "経験")}
      ${scoreBarHtml(candidate.availability_score, "空き状況")}
    </div>
  `;
}

function assignmentCardHtml(
  assignment: FinalAssignment,
  task: PipelineTask | undefined,
  members: PipelineMember[],
  decision: LocalDecision,
): string {
  const rec = assignment.ai_recommendation;
  const primaryCandidate = rec.candidate_scores.find((c) => c.member_id === rec.recommended_member_id);

  return `
    <div class="assignment-card" data-task-id="${escapeHtml(assignment.task_id)}">
      <div class="assignment-card-top">
        <div>
          <span class="req-card-id">${escapeHtml(assignment.task_id)}</span>
          <span style="margin-left:8px;font-weight:600">${task ? escapeHtml(task.title) : "（タスク情報不明）"}</span>
        </div>
        ${assignmentStatusBadgeHtml(rec.status)}
      </div>

      <div class="assignment-card-body">
        <div class="assignment-recommend-col">
          <div class="req-card-tasks-label">推奨メンバー</div>
          <div class="assignment-recommend-name">
            ${rec.recommended_member_id ? escapeHtml(memberName(rec.recommended_member_id, members)) : `<span class="auth-hint">${UNAVAILABLE_TEXT}（適任者なし）</span>`}
            ${rec.score !== null ? `<span class="auth-hint" style="margin-left:6px">スコア ${Math.round(rec.score)}</span>` : ""}
          </div>

          ${primaryCandidate ? candidateScoreRowHtml(primaryCandidate, members) : ""}

          <div class="req-card-tasks-label" style="margin-top:10px">推奨理由（AI）</div>
          ${
            rec.reasons.length > 0
              ? `<ul class="assignment-reason-list">${rec.reasons.map((r) => `<li>${escapeHtml(r)}</li>`).join("")}</ul>`
              : `<span class="auth-hint">理由の記載なし</span>`
          }

          ${
            rec.warnings.length > 0
              ? `<div class="assignment-warning-box"><i data-lucide="triangle-alert"></i> ${rec.warnings.map(escapeHtml).join(" / ")}</div>`
              : ""
          }

          ${
            rec.candidate_scores.length > 1
              ? `<details class="management-key-reveal" style="margin-top:8px">
                  <summary>他の候補者スコアを見る (${rec.candidate_scores.length}名)</summary>
                  <div class="candidate-score-grid">${rec.candidate_scores.map((c) => candidateScoreRowHtml(c, members)).join("")}</div>
                </details>`
              : ""
          }

          ${
            rec.rejected_candidates.length > 0
              ? `<details class="management-key-reveal" style="margin-top:8px">
                  <summary>除外された候補者を見る (${rec.rejected_candidates.length}名)</summary>
                  <ul class="assignment-reason-list">
                    ${rec.rejected_candidates
                      .map((rc) => `<li>${escapeHtml(memberName(rc.member_id, members))}: ${rc.reasons.map(escapeHtml).join(" / ")}</li>`)
                      .join("")}
                  </ul>
                </details>`
              : ""
          }
        </div>

        <div class="assignment-decision-col">
          <div class="req-card-tasks-label">確定状況</div>
          <div class="assignment-decision-current">
            現在の担当: <b>${decision.assigned_member_id ? escapeHtml(memberName(decision.assigned_member_id, members)) : "未定"}</b>
            <div class="auth-hint">決定者: ${decision.decided_by === "human" ? "人手" : "AI"}${decision.overridden ? "（AI推奨から変更あり）" : ""}${decision.accepted ? "・承認済み" : ""}</div>
            ${decision.override_reason ? `<div class="auth-hint">理由: ${escapeHtml(decision.override_reason)}</div>` : ""}
          </div>

          <div class="assignment-actions">
            <button class="btn-preview-secondary btn-assignment-accept" ${decision.accepted ? "disabled" : ""}>
              <i data-lucide="check"></i> ${decision.accepted ? "承認済み" : "承認"}
            </button>
            <button class="btn-preview-secondary btn-assignment-change">
              <i data-lucide="user-pen"></i> 担当者を変更
            </button>
          </div>

          <div class="assignment-change-form" style="display:none">
            <select class="project-select assignment-change-select">
              ${members.map((m) => `<option value="${escapeHtml(m.id)}" ${m.id === decision.assigned_member_id ? "selected" : ""}>${escapeHtml(m.name)}</option>`).join("")}
            </select>
            <input class="input-member assignment-change-reason" placeholder="変更理由（任意）" style="width:100%;margin-top:6px" />
            <button class="btn-add-member assignment-change-submit" style="margin-top:6px;width:100%">この担当者に変更</button>
          </div>
          <div class="auth-hint" style="margin-top:8px">※この画面内のみの変更です。バックエンドへの保存は未実装です。</div>
        </div>
      </div>
    </div>
  `;
}

export async function renderAssignmentsView(container: HTMLElement): Promise<void> {
  container.innerHTML = `
    <div class="sec-header sec-header-page">
      <div class="sec-header-icon"><i data-lucide="user-check"></i></div>
      <span class="sec-header-title">アサイン推奨</span>
    </div>
    <div class="sec-body" style="padding: 20px">
      ${IS_SAMPLE_DATA ? sampleDataBannerHtml() : ""}
      <div id="assignment-list-container">読み込み中...</div>
    </div>
  `;

  const listContainer = container.querySelector("#assignment-list-container") as HTMLElement;
  let assignments: FinalAssignment[];
  let tasks: PipelineTask[];
  let members: PipelineMember[];
  try {
    [assignments, tasks, members] = await Promise.all([
      getAssignments(),
      getPipelineTasks(),
      getPipelineMembers(),
    ]);
  } catch (err) {
    listContainer.innerHTML = pipelineErrorBannerHtml(
      extractErrorMessage(err, "アサインメントデータの取得に失敗しました。"),
    );
    return;
  }

  if (assignments.length === 0) {
    listContainer.innerHTML = `<div class="auth-hint">アサインメントデータはまだ利用できません。</div>`;
    return;
  }

  const decisions = new Map<string, LocalDecision>(
    assignments.map((a) => [
      a.task_id,
      {
        assigned_member_id: a.assigned_member_id,
        decided_by: a.decided_by,
        overridden: a.overridden,
        override_reason: a.override_reason,
        accepted: a.decided_by === "human",
      },
    ]),
  );

  function renderList(): void {
    listContainer.innerHTML = `
      <div class="assignment-list">
        ${assignments
          .map((a) => assignmentCardHtml(a, tasks.find((t) => t.id === a.task_id), members, decisions.get(a.task_id)!))
          .join("")}
      </div>
    `;
    bindCardEvents();
  }

  function bindCardEvents(): void {
    listContainer.querySelectorAll<HTMLElement>(".assignment-card").forEach((card) => {
      const taskId = card.getAttribute("data-task-id")!;
      const decision = decisions.get(taskId)!;

      card.querySelector(".btn-assignment-accept")?.addEventListener("click", () => {
        decision.accepted = true;
        decision.decided_by = decision.overridden ? decision.decided_by : "ai";
        renderList();
      });

      card.querySelector(".btn-assignment-change")?.addEventListener("click", () => {
        const form = card.querySelector(".assignment-change-form") as HTMLElement;
        form.style.display = form.style.display === "none" ? "block" : "none";
      });

      card.querySelector(".assignment-change-submit")?.addEventListener("click", () => {
        const select = card.querySelector(".assignment-change-select") as HTMLSelectElement;
        const reasonInput = card.querySelector(".assignment-change-reason") as HTMLInputElement;
        decision.assigned_member_id = select.value || null;
        decision.decided_by = "human";
        decision.overridden = true;
        decision.override_reason = reasonInput.value.trim() || null;
        decision.accepted = true;
        renderList();
      });
    });
  }

  renderList();
}
