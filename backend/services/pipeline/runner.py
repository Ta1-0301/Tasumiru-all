# backend/services/pipeline/runner.py
"""
パイプライン全体のオーケストレーター。

Specification
  → Document structure extraction (structure.decompose_document, ルールベース)
  → Requirement identification (stages.identify_requirements, LLM・チャンク単位)
  → Candidate task extraction (stages.extract_candidate_task, LLM・要求事項単位)
  → Task normalization (stages.normalize_task, ルールベース)
  → Duplicate detection (stages.detect_duplicates, ルールベース)
  → Task validation (validate.validate_task, Pydantic + 修復)
  → Structured output (PipelineResult)
"""

from __future__ import annotations

from typing import Dict, List

from backend.services.llm import BaseLLMClient
from backend.services.pipeline.schema import (
    CandidateTask,
    DocumentChunk,
    FailedItem,
    PipelineResult,
    Requirement,
    Task,
)
from backend.services.pipeline.stages import (
    detect_duplicates,
    extract_candidate_task,
    identify_requirements,
    normalize_task,
)
from backend.services.pipeline.structure import decompose_document
from backend.services.pipeline.validate import validate_task


async def run_pipeline(document_text: str, client: BaseLLMClient) -> PipelineResult:
    # Stage 1: 文書構造抽出
    chunks: List[DocumentChunk] = decompose_document(document_text)
    chunk_by_id: Dict[str, DocumentChunk] = {c.chunk_id: c for c in chunks}

    if not chunks:
        return PipelineResult(tasks=[], chunk_count=0, requirement_count=0)

    # Stage 2: 要求事項識別（チャンクごとに逐次実行）
    #
    # NOTE: 当初 asyncio.gather で並列化していたが、実機のOllama(単一GPU/CPUで
    #       推論を直列処理する)に対して投げると、後発のリクエストがキューで
    #       待たされ続けて180秒のタイムアウトに引っかかることを実際の実行で確認した。
    #       これはOllama固有の問題ではなく「1推論ワーカーしか持たないローカルLLM」
    #       全般に言えることなので、ビジネスロジック側をOllama専用にするのではなく、
    #       どのプロバイダーに対しても安全な「逐次実行」をデフォルトにした。
    all_requirements: List[Requirement] = []
    failed_items: List[FailedItem] = []
    for chunk in chunks:
        reqs, error = await identify_requirements(chunk, client)
        all_requirements.extend(reqs)
        if error:
            failed_items.append(FailedItem(
                raw_data={"chunk_id": chunk.chunk_id}, error=error, stage="identify_requirements",
            ))

    # Stage 3: 候補タスク抽出（要求事項ごとに逐次実行、1要求→1タスク）
    candidates: List[CandidateTask] = []
    for req in all_requirements:
        candidate, error = await extract_candidate_task(req, chunk_by_id[req.chunk_id], client)
        if candidate is None:
            failed_items.append(FailedItem(
                raw_data={"requirement": req.model_dump()},
                error=error or "候補タスクの生成に失敗",
                stage="extract_candidate_task",
            ))
        else:
            candidates.append(candidate)

    # Stage 4: 正規化（決定的）
    normalized = [normalize_task(c) for c in candidates]

    # Stage 5: 重複検出（決定的）
    deduped, dropped_duplicates = detect_duplicates(normalized)

    # Stage 6-7: 検証（+ 必要なら修復） → 構造化出力
    tasks: List[Task] = []
    for i, candidate in enumerate(deduped):
        task_id = f"T-{i + 1:03d}"
        task, failed = await validate_task(candidate, task_id, client)
        if task is not None:
            tasks.append(task)
        if failed is not None:
            failed_items.append(failed)

    return PipelineResult(
        tasks=tasks,
        failed_items=failed_items,
        dropped_duplicates=dropped_duplicates,
        chunk_count=len(chunks),
        requirement_count=len(all_requirements),
    )
