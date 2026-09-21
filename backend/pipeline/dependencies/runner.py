# backend/pipeline/dependencies/runner.py
"""
Phase 5のオーケストレーター。

Tasks（Phase 4の出力、`TaskDocument`）
  → LLM Dependency Proposal（本モジュール、タスク一覧を1回で提案）
  → Dependency Validation（本モジュール、決定的）
  → DependencyGraph表現
  → DependencyDocument（dependencies.json として保存）

**メンバーへの割り当てはこのフェーズでも行わない。**

使い方（CLIから直接実行する場合）:
    source .venv/bin/activate
    export LLM_PROVIDER=ollama OLLAMA_BASE_URL=http://localhost:11434
    python -m backend.pipeline.dependencies.runner <tasks.jsonのパス>
"""

from __future__ import annotations

import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import List

from backend.pipeline.dependencies.graph import DependencyGraph
from backend.pipeline.dependencies.proposer import propose_dependencies
from backend.pipeline.dependencies.schema import Dependency, DependencyDocument, ValidationIssue
from backend.pipeline.dependencies.validator import validate_dependencies
from backend.pipeline.tasks.schema import TaskDocument
from backend.services.llm import BaseLLMClient

OUTPUT_DIR = Path(__file__).resolve().parent / "output"


async def run_dependency_pipeline(
    task_document: TaskDocument,
    client: BaseLLMClient,
) -> DependencyDocument:
    """Phase 4のTaskDocumentからタスク間の依存関係を提案・検証する。

    `client`は`backend.services.llm.BaseLLMClient`の実装であればよく、
    どのプロバイダー/モデルかはこの関数の関心事ではない。
    """
    valid_task_ids = [t.id for t in task_document.tasks]

    dependencies, proposal_error = await propose_dependencies(task_document.tasks, client)

    issues: List[ValidationIssue] = validate_dependencies(dependencies, valid_task_ids)
    if proposal_error:
        issues.append(ValidationIssue(code="PROPOSAL_ERROR", message=proposal_error))

    graph = DependencyGraph(valid_task_ids, dependencies)

    model = getattr(client, "model", None)

    return DependencyDocument(
        document_id=task_document.document_id,
        dependencies=dependencies,
        issues=issues,
        graph=graph.to_dict(),
        model=model,
        generated_at=datetime.now(timezone.utc).isoformat(),
    )


def save_dependencies_document(doc: DependencyDocument, output_dir: Path = OUTPUT_DIR) -> Path:
    """dependencies.json を保存する（中間結果の永続化）"""
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_path = output_dir / f"{doc.document_id}_{timestamp}.dependencies.json"
    out_path.write_text(
        json.dumps(doc.model_dump(mode="json"), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return out_path


async def _main() -> None:
    if len(sys.argv) < 2:
        print("使い方: python -m backend.pipeline.dependencies.runner <tasks.jsonのパス>")
        raise SystemExit(1)

    from backend.services.llm import get_llm_client  # 既存のプロバイダー抽象化をそのまま使う

    tasks_path = Path(sys.argv[1])
    task_document = TaskDocument.model_validate(json.loads(tasks_path.read_text(encoding="utf-8")))

    client = get_llm_client()
    doc = await run_dependency_pipeline(task_document, client)
    out_path = save_dependencies_document(doc)

    print(f"提案された依存関係: {len(doc.dependencies)}件 / 検証で検出された問題: {len(doc.issues)}件")
    print(f"保存先: {out_path}")


if __name__ == "__main__":
    asyncio.run(_main())
