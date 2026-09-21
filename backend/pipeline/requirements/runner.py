# backend/pipeline/requirements/runner.py
"""
Phase 3のオーケストレーター。

Specification Document
  → Document Parser（呼び出し側の責務。既存の`backend.services.parser.parse_document()`
     をそのまま使う想定。本モジュールはテキスト化済みの文書を受け取るだけで、
     既存の仕様書アップロード機能には一切触れない・変更しない）
  → LLM Requirement Extraction（本モジュール、チャンクごとに逐次実行）
  → Requirement Validation（本モジュール、決定的）
  → RequirementDocument（requirements.json として保存）

**タスクへの分解はここでは行わない。** `backend/services/pipeline/`
（CandidateTask/Taskの生成）は本モジュールの範囲外であり、呼び出さない。

使い方（CLIから直接実行する場合）:
    source .venv/bin/activate
    export LLM_PROVIDER=ollama OLLAMA_BASE_URL=http://localhost:11434
    python -m backend.pipeline.requirements.runner <仕様書テキストファイル> <document_id>
"""

from __future__ import annotations

import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import List

from backend.pipeline.requirements.extractor import extract_requirements_from_chunk
from backend.pipeline.requirements.schema import (
    Requirement,
    RequirementCandidate,
    RequirementDocument,
    ValidationIssue,
)
from backend.pipeline.requirements.validator import validate_requirements
from backend.services.concurrency import gather_with_concurrency, get_max_concurrency
from backend.services.llm import BaseLLMClient
from backend.services.pipeline.structure import decompose_document

OUTPUT_DIR = Path(__file__).resolve().parent / "output"


def _assign_ids(candidates: List[RequirementCandidate]) -> List[Requirement]:
    """候補にREQ-XXX形式の一意なIDを機械的に割り当てる（IDをLLMに書かせない）"""
    return [
        Requirement(
            id=f"REQ-{i + 1:03d}",
            type=c.type,
            title=c.title,
            description=c.description,
            priority=c.priority,
            origin=c.origin,
            source_reference=c.source_reference,
            confidence=c.confidence,
        )
        for i, c in enumerate(candidates)
    ]


async def run_requirements_pipeline(
    document_id: str,
    document_text: str,
    client: BaseLLMClient,
) -> RequirementDocument:
    """仕様書テキストから構造化要求(RequirementDocument)を抽出・検証する。

    `client`は`backend.services.llm.BaseLLMClient`の実装であればよく、
    どのプロバイダー/モデルかはこの関数の関心事ではない（モデルは呼び出し側で
    `backend.services.llm.get_llm_client()`等を通じて設定可能）。
    """
    # 文書構造抽出は既存のタスク分解パイプラインのものを読み取り専用で再利用する
    # （出典が実在のチャンクに機械的に紐づくことを保証するための既存の仕組み）
    chunks = decompose_document(document_text)

    candidates: List[RequirementCandidate] = []
    extraction_errors: List[str] = []

    # Part 3: 各チャンクの抽出は互いに独立している（前のチャンクの結果を
    # 参照しない）ため、安全に並列化できる。既定値は1（＝これまでと完全に
    # 同じ逐次実行）で、OLLAMA_MAX_CONCURRENCY環境変数で明示的に上げない限り
    # 挙動は変わらない。単一ワーカーのローカルOllamaに対して並列度を
    # むやみに上げると逆に遅くなる可能性があるため（依頼Part 3の警告）、
    # 積極的な並列度をデフォルトにはしない。
    max_concurrency = get_max_concurrency()
    results = await gather_with_concurrency(
        [
            (lambda c=chunk: extract_requirements_from_chunk(c, client, document_id))
            for chunk in chunks
        ],
        max_concurrency,
    )
    for chunk_candidates, error in results:
        candidates.extend(chunk_candidates)
        if error:
            extraction_errors.append(error)

    requirements = _assign_ids(candidates)
    issues = validate_requirements(requirements, document_text=document_text)
    issues += [ValidationIssue(code="EXTRACTION_ERROR", message=e) for e in extraction_errors]

    model = getattr(client, "model", None)

    return RequirementDocument(
        document_id=document_id,
        requirements=requirements,
        issues=issues,
        model=model,
        generated_at=datetime.now(timezone.utc).isoformat(),
    )


def save_requirements_document(doc: RequirementDocument, output_dir: Path = OUTPUT_DIR) -> Path:
    """requirements.json を保存する（中間結果の永続化）"""
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_path = output_dir / f"{doc.document_id}_{timestamp}.requirements.json"
    out_path.write_text(
        json.dumps(doc.model_dump(mode="json"), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return out_path


async def _main() -> None:
    if len(sys.argv) < 3:
        print("使い方: python -m backend.pipeline.requirements.runner <spec_text_file> <document_id>")
        raise SystemExit(1)

    from backend.services.llm import get_llm_client  # 既存のプロバイダー抽象化をそのまま使う

    spec_path = Path(sys.argv[1])
    document_id = sys.argv[2]
    document_text = spec_path.read_text(encoding="utf-8")

    client = get_llm_client()
    doc = await run_requirements_pipeline(document_id, document_text, client)
    out_path = save_requirements_document(doc)

    print(f"抽出された要求: {len(doc.requirements)}件 / 検証で検出された問題: {len(doc.issues)}件")
    print(f"保存先: {out_path}")


if __name__ == "__main__":
    asyncio.run(_main())
