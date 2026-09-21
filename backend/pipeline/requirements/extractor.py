# backend/pipeline/requirements/extractor.py
"""
Stage: LLM Requirement Extraction。

`backend.services.llm.BaseLLMClient`だけに依存する（`complete()`しか呼ばない）。
どのプロバイダー（Ollama/Anthropic/将来追加されるもの）を使うかはこの層の
関心事ではない。**Ollama固有の挙動やモデル名は一切ハードコードしない**
（依頼の「Do not hard-code Ollama-specific logic into business logic」に対応）。
呼び出し側（`backend.services.llm.get_llm_client()`）が使うモデルは
環境変数(`LLM_PROVIDER`等)で設定可能。

出典(`source_reference`)はLLMの出力からは一切採用しない。常に呼び出し元から
渡された`DocumentChunk`（`backend.services.pipeline.structure.decompose_document()`
が仕様書本文から機械的に切り出した実在のチャンク）から機械的に組み立てる。
これにより「出典を捏造しない」という要件を構造的に保証する。
"""

from __future__ import annotations

from typing import List, Optional, Tuple, get_args

from backend.pipeline.requirements.schema import RequirementCandidate, RequirementType, SourceReference
from backend.services.llm import BaseLLMClient
from backend.services.pipeline.llm_json import call_llm_json
from backend.services.pipeline.schema import DocumentChunk

_VALID_TYPES = set(get_args(RequirementType))
_VALID_PRIORITIES = {"high", "medium", "low", "unknown"}
_VALID_ORIGINS = {"explicit", "inferred"}

_INFERRED_DEFAULT_CONFIDENCE = 0.3
_EXPLICIT_DEFAULT_CONFIDENCE = 0.5

_EXTRACTION_PROMPT = """\
あなたはソフトウェア要求分析の専門家です。以下は仕様書本文の一区画です。
この区画の内容から、次の9種類のいずれかに当たる要求・情報を過不足なく抽出してください。

- system_purpose : システムの目的・存在理由
- target_user    : 想定利用者・対象ユーザー
- functional     : 機能要件（システムが実行すべき機能）
- non_functional : 非機能要件（性能・可用性・セキュリティ等）
- constraint     : 制約（技術的・予算的・スケジュール的な制限）
- assumption     : 前提条件
- deliverable    : 成果物・提出物
- technical      : 技術要件（使用言語・フレームワーク等の指定）
- business_rule  : 重要な業務ルール

ルール:
- この区画に書かれていないことを新しく作り出さないこと（捏造禁止）
- 区画に明記されている内容は origin="explicit" とすること
- 区画に明記されていないが、文脈から合理的に推測できる内容は
  origin="inferred" とし、confidenceを低めに設定すること（0.4以下を推奨）
- 確信が持てない場合はconfidenceを低くすること（高い確信度を安易に付けないこと）
- 該当する情報が無ければ空配列を返すこと
- priorityは high/medium/low/unknown のいずれか（判断できなければunknown）

出力は必ず以下のJSON形式のみ。説明文やMarkdownは不要です。

{{"requirements": [
  {{"type": "functional", "title": "短い見出し", "description": "詳細説明",
    "priority": "high", "origin": "explicit", "confidence": 0.9}}
]}}

## 区画の見出し
{heading}

## 区画の内容
{chunk_text}
"""


async def extract_requirements_from_chunk(
    chunk: DocumentChunk,
    client: BaseLLMClient,
    document_id: str,
) -> Tuple[List[RequirementCandidate], Optional[str]]:
    """1チャンクから要求候補を抽出する。戻り値は (候補一覧, エラーメッセージ)。

    LLM呼び出し自体が失敗した場合のみエラーを返す。個々の項目が不正な形式
    （title/description欠損、typeが未知の値等）の場合はその項目だけを
    黙って捨てる（無い情報を捏造して埋めることはしない）。
    """
    prompt = _EXTRACTION_PROMPT.format(
        heading=chunk.heading or "(見出し無し)",
        chunk_text=chunk.text,
    )
    result, error = await call_llm_json(client, prompt)

    if result is None:
        return [], f"chunk={chunk.chunk_id}: {error}"

    raw_list = result.get("requirements")
    if not isinstance(raw_list, list):
        return [], f"chunk={chunk.chunk_id}: 'requirements'が配列ではない: {result!r}"

    candidates: List[RequirementCandidate] = []
    for item in raw_list:
        if not isinstance(item, dict):
            continue

        req_type = item.get("type")
        if req_type not in _VALID_TYPES:
            continue  # 未知の種別は丸めずに捨てる（存在しない種別を捏造しない）

        title = str(item.get("title") or "").strip()
        description = str(item.get("description") or "").strip()
        if not title or not description:
            continue  # 情報が無いのに埋め合わせで作り出すことはしない

        priority = item.get("priority") if item.get("priority") in _VALID_PRIORITIES else "unknown"
        origin = item.get("origin") if item.get("origin") in _VALID_ORIGINS else "explicit"

        confidence = item.get("confidence")
        if not isinstance(confidence, (int, float)) or not (0.0 <= confidence <= 1.0):
            # 妥当な確信度が示されなかった場合は、由来に応じた控えめな既定値にする
            # （高い確信度を安易に捏造しない）
            confidence = _INFERRED_DEFAULT_CONFIDENCE if origin == "inferred" else _EXPLICIT_DEFAULT_CONFIDENCE

        source_reference = SourceReference(
            document_id=document_id,
            page=None,
            section=chunk.heading,
            paragraph=chunk.chunk_id,
            source_text=chunk.text,
        )

        candidates.append(RequirementCandidate(
            type=req_type,
            title=title,
            description=description,
            priority=priority,
            origin=origin,
            source_reference=source_reference,
            confidence=float(confidence),
        ))

    return candidates, None
