# backend/pipeline/tasks/runner.py
"""
Phase 4のオーケストレーター。

Requirements（Phase 3の出力、`RequirementDocument`）
  → LLM Task Decomposition（本モジュール、Requirementごとに逐次実行）
  → Task Validation（本モジュール、決定的。無効な結果を修復せず
     needs_review/review_reasonsとして印を付けるだけ）
  → TaskDocument（tasks.json として保存）

**メンバーへの割り当て（既存の`backend.services.matcher`）や、タスク間の
依存関係の構築はここでは一切行わない。** それらは本モジュールの範囲外。

元の仕様書本文は直接パースし直さない。渡された場合のみ、出典の再検証
（`check_source_text_matches_document`）にのみ使う。

使い方（CLIから直接実行する場合）:
    source .venv/bin/activate
    export LLM_PROVIDER=ollama OLLAMA_BASE_URL=http://localhost:11434
    python -m backend.pipeline.tasks.runner <requirements.jsonのパス> [元の仕様書テキストファイル]
"""

from __future__ import annotations

import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

from backend.pipeline.requirements.schema import RequirementDocument
from backend.pipeline.tasks.decomposer import decompose_requirement
from backend.pipeline.tasks.schema import Task, TaskCandidate, TaskDocument, ValidationIssue
from backend.pipeline.tasks.validator import apply_review_flags, validate_tasks
from backend.services.concurrency import gather_with_concurrency, get_max_concurrency
from backend.services.llm import BaseLLMClient
from backend.services.rag.embeddings import BaseEmbeddingClient
from backend.services.rag.schema import SpecIndex

OUTPUT_DIR = Path(__file__).resolve().parent / "output"


def _assign_ids(candidates: List[TaskCandidate]) -> List[Task]:
    """候補にTASK-XXX形式の一意なIDを機械的に割り当てる（IDをLLMに書かせない）"""
    return [
        Task(
            id=f"TASK-{i + 1:03d}",
            requirement_ids=c.requirement_ids,
            title=c.title,
            description=c.description,
            priority=c.priority,
            estimated_hours=c.estimated_hours,
            required_skills=c.required_skills,
            acceptance_criteria=c.acceptance_criteria,
            source_reference=c.source_reference,
            confidence=c.confidence,
            related_sources=c.related_sources,
        )
        for i, c in enumerate(candidates)
    ]


async def run_task_decomposition_pipeline(
    requirement_document: RequirementDocument,
    client: BaseLLMClient,
    original_document_text: Optional[str] = None,
    *,
    spec_index: Optional[SpecIndex] = None,
    embedding_client: Optional[BaseEmbeddingClient] = None,
) -> TaskDocument:
    """Phase 3のRequirementDocumentから実行可能な開発タスクを分解・検証する。

    `client`は`backend.services.llm.BaseLLMClient`の実装であればよく、
    どのプロバイダー/モデルかはこの関数の関心事ではない。
    `original_document_text`は任意。渡された場合のみ出典の再検証に使われる
    （「元の仕様書を直接パースし直さない」方針の唯一の例外）。

    `spec_index`/`embedding_client`は実験的RAG機能用の任意引数（既定はNone、
    ENABLE_RAG=false時の既定動作と完全に同一）。渡された場合のみ、各Requirementの
    分解時に仕様書chunkの類似度検索を行い、related_sourcesを追加で付与する。
    """
    candidates: List[TaskCandidate] = []
    decomposition_errors: List[str] = []

    # Part 3: 各requirementの分解は互いに独立している（前のrequirementの
    # 結果を参照しない）ため、安全に並列化できる。requirements/runner.pyと
    # 同じ既定値1（＝逐次実行のまま）・同じ環境変数(OLLAMA_MAX_CONCURRENCY)を使う。
    # spec_indexが無い（＝ENABLE_RAG=false）場合は、decompose_requirement()を
    # 従来と全く同じ2引数の形で呼ぶ（既存コード/既存テストがdecompose_requirementを
    # 独自のフェイク実装に差し替えているケースとの後方互換性のため、
    # spec_index/embedding_clientキーワード引数自体を渡さない）。
    if spec_index is not None:
        factories = [
            (lambda r=requirement: decompose_requirement(
                r, client, spec_index=spec_index, embedding_client=embedding_client,
            ))
            for requirement in requirement_document.requirements
        ]
    else:
        factories = [
            (lambda r=requirement: decompose_requirement(r, client))
            for requirement in requirement_document.requirements
        ]

    max_concurrency = get_max_concurrency()
    results = await gather_with_concurrency(factories, max_concurrency)
    for task_candidates, error in results:
        candidates.extend(task_candidates)
        if error:
            decomposition_errors.append(error)

    tasks = _assign_ids(candidates)

    requirements_by_id = {r.id: r for r in requirement_document.requirements}
    issues = validate_tasks(
        tasks,
        requirements_by_id=requirements_by_id,
        source_document_text=original_document_text,
    )
    issues += [ValidationIssue(code="DECOMPOSITION_ERROR", message=e) for e in decomposition_errors]

    # 無効な結果を修復するのではなく、印を付けるだけ
    tasks = apply_review_flags(tasks, issues)

    model = getattr(client, "model", None)

    return TaskDocument(
        document_id=requirement_document.document_id,
        tasks=tasks,
        issues=issues,
        model=model,
        generated_at=datetime.now(timezone.utc).isoformat(),
    )


def save_tasks_document(doc: TaskDocument, output_dir: Path = OUTPUT_DIR) -> Path:
    """tasks.json を保存する（中間結果の永続化）"""
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_path = output_dir / f"{doc.document_id}_{timestamp}.tasks.json"
    out_path.write_text(
        json.dumps(doc.model_dump(mode="json"), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return out_path


async def _main() -> None:
    if len(sys.argv) < 2:
        print(
            "使い方: python -m backend.pipeline.tasks.runner "
            "<requirements.jsonのパス> [元の仕様書テキストファイル]"
        )
        raise SystemExit(1)

    from backend.services.llm import get_llm_client  # 既存のプロバイダー抽象化をそのまま使う

    req_path = Path(sys.argv[1])
    requirement_document = RequirementDocument.model_validate(
        json.loads(req_path.read_text(encoding="utf-8"))
    )

    original_text: Optional[str] = None
    if len(sys.argv) >= 3:
        original_text = Path(sys.argv[2]).read_text(encoding="utf-8")

    client = get_llm_client()
    doc = await run_task_decomposition_pipeline(requirement_document, client, original_text)
    out_path = save_tasks_document(doc)

    review_count = sum(1 for t in doc.tasks if t.needs_review)
    print(f"生成されたタスク: {len(doc.tasks)}件 / 要確認: {review_count}件 / 検証で検出された問題: {len(doc.issues)}件")
    print(f"保存先: {out_path}")


if __name__ == "__main__":
    asyncio.run(_main())
