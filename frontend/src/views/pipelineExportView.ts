// src/views/pipelineExportView.ts
//
// 画面: JSONエクスポート（Phase 9のFinal JSON全体を可視化）。
// 整形済みJSONビューア、コピー、ダウンロードを提供する。
// ダウンロードされるJSONは、画面に表示しているものと同一のフィクスチャ
// データそのもの（実バックエンド接続後は実際の応答データになる）。
import { getProjectResult, IS_SAMPLE_DATA } from "../services/projectService";
import { sampleDataBannerHtml, pipelineErrorBannerHtml, extractErrorMessage } from "../pipeline/format";
import type { FinalProjectOutput } from "../types/pipeline";

export async function renderPipelineExportView(container: HTMLElement): Promise<void> {
  container.innerHTML = `
    <div class="sec-header sec-header-page">
      <div class="sec-header-icon"><i data-lucide="file-code"></i></div>
      <span class="sec-header-title">JSONエクスポート（Final JSON）</span>
    </div>
    <div class="sec-body" style="padding: 20px">
      ${IS_SAMPLE_DATA ? sampleDataBannerHtml() : ""}
      <div style="display:flex;gap:8px;margin-bottom:12px">
        <button class="btn-export" id="pex-copy" style="width:auto;padding:7px 16px;background:var(--brand-mid);color:#fff">
          <i data-lucide="copy"></i> コピー
        </button>
        <button class="btn-export" id="pex-download" style="width:auto;padding:7px 16px;background:#7a3d0e;color:#fff">
          <i data-lucide="download"></i> ダウンロード
        </button>
        <span class="auth-hint" id="pex-status" style="align-self:center"></span>
      </div>
      <div class="json-preview" id="pex-json-preview" style="height: 520px">読み込み中...</div>
    </div>
  `;

  const preview = container.querySelector("#pex-json-preview") as HTMLElement;
  const statusEl = container.querySelector("#pex-status") as HTMLElement;
  let project: FinalProjectOutput;
  try {
    project = await getProjectResult();
  } catch (err) {
    preview.innerHTML = pipelineErrorBannerHtml(
      extractErrorMessage(err, "エクスポートデータの取得に失敗しました。"),
    );
    return;
  }
  const formatted = JSON.stringify(project, null, 2);
  preview.textContent = formatted;

  container.querySelector("#pex-copy")?.addEventListener("click", async () => {
    try {
      await navigator.clipboard.writeText(formatted);
      statusEl.textContent = "コピーしました";
    } catch {
      statusEl.textContent = "コピーに失敗しました";
    }
  });

  container.querySelector("#pex-download")?.addEventListener("click", () => {
    const blob = new Blob([formatted], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${project.project.name || project.project.document_id}_final.json`;
    a.click();
    URL.revokeObjectURL(url);
  });
}
