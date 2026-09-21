# backend/pipeline/tasks/decomposer.py
"""
Stage: LLM Task Decomposition。

Phase 3で生成された1件の`Requirement`を入力として受け取り、実行可能な
開発タスクに変換する。元の仕様書は直接パースし直さない —
各タスクの`source_reference`は、入力として渡された`Requirement`の
`source_reference`を機械的に引き継ぐだけで、LLMに出典を書かせることはない。

`backend.services.llm.BaseLLMClient`だけに依存する（`complete()`しか呼ばない）。
プロバイダー固有の処理・モデル名は一切ハードコードしない。モデルは呼び出し側
(`backend.services.llm.get_llm_client()`)が環境変数で設定する。

メンバーへの割り当て・タスク間の依存関係の構築はここでは一切行わない。
"""

from __future__ import annotations

from typing import List, Optional, Tuple

from backend.pipeline.requirements.schema import Requirement
from backend.pipeline.tasks.schema import TaskCandidate
from backend.services.llm import BaseLLMClient
from backend.services.pipeline.llm_json import call_llm_json
from backend.services.rag.embeddings import BaseEmbeddingClient
from backend.services.rag.schema import RagSource, SpecIndex
from backend.services.rag.search import retrieve_related_sources

_VALID_PRIORITIES = {"high", "medium", "low", "unknown"}

_DECOMPOSITION_PROMPT = """\
あなたはソフトウェア開発のプロジェクト管理者です。以下の「要求」を、
実行可能な開発タスクに分解してください。

## 良いタスクの条件
- 1つの明確な目的を持つ
- 着手可能である（何をすべきかが明確）
- 完了したかどうかを明確に判断できる
- 広すぎない（例:「システム全体を実装する」のような分解はNG）
- 不必要に細かすぎない（例: 要求に明記されていない限り「ボタンの色を変える」
  のような粒度のタスクは作らない）
- 1人以上の担当者にアサインできる粒度である

## 良い例
要求: 「利用者は仕様書ドキュメントをアップロードできる」
タスク: 「ファイルアップロードAPIを実装する」/「ファイル選択UIを実装する」/
       「ドラッグ&ドロップアップロードを実装する」

## 避けるべき例
- 広すぎる: 「システム全体を実装する」
- 細かすぎる（要求に明記が無い限り）: 「アップロードボタンの色を変更する」

## ルール
- 要求に書かれていないことを新しく作り出さないこと（捏造禁止）
- 確信が持てない項目は null または "unknown" にすること
- 確信が持てない場合はconfidenceを低くすること
- 分解すべきタスクが無ければ空配列を返すこと

## 要求
種別: {requirement_type}
タイトル: {requirement_title}
内容: {requirement_description}
{extra_context}
出力は必ず以下のJSON形式のみ。説明文やMarkdownは不要です。

{{"tasks": [
  {{"title": "動詞で終わる具体的なタスク名", "description": "何をどう完了させるかの説明",
    "priority": "high/medium/low/unknownのいずれか", "estimated_hours": 数値またはnull,
    "required_skills": ["スキル名"] または ["unknown"],
    "acceptance_criteria": ["完了と判断できる条件"],
    "confidence": 0.0から1.0の数値}}
]}}
"""


async def decompose_requirement(
    requirement: Requirement,
    client: BaseLLMClient,
    *,
    spec_index: Optional[SpecIndex] = None,
    embedding_client: Optional[BaseEmbeddingClient] = None,
    top_k: int = 3,
) -> Tuple[List[TaskCandidate], Optional[str]]:
    """1件のRequirementを実行可能な開発タスクに分解する。

    戻り値は (タスク候補一覧, エラーメッセージ)。LLM呼び出し自体が失敗した
    場合のみエラーを返す。個々の項目が不正な形式（title/description欠損等）
    の場合はその項目だけを黙って捨てる（無い情報を捏造して埋めない）。

    `spec_index`/`embedding_client`は実験的RAG機能用の任意引数（既定はNone）。
    どちらもNoneのとき（＝ENABLE_RAG=falseの既定動作時）は従来と完全に同一の
    挙動になる：追加のHTTP呼び出しは発生せず、related_sourcesは空配列のまま。
    渡された場合のみ、Requirementの説明文をqueryとして仕様書chunkを類似度検索し、
    (1) 追加の参考コンテキストとしてプロンプトに注入し、(2) 各TaskCandidateの
    related_sourcesに類似度付きで記録する。注入する参考コンテキストは常に実在の
    chunkテキストの抜粋であり、LLMにページ番号・節番号を生成させることはない。
    """
    related_sources: List[RagSource] = []
    extra_context = ""
    if spec_index is not None and embedding_client is not None:
        related_sources = await retrieve_related_sources(
            requirement.description, spec_index, embedding_client, k=top_k
        )
        if related_sources:
            chunk_text_by_id = {c.chunk_id: c.text for c in spec_index.chunks}
            excerpts = "\n".join(
                f"- [{s.section or '見出し無し'}] {chunk_text_by_id.get(s.chunk_id, '')}"
                for s in related_sources
            )
            extra_context = (
                "\n## 仕様書の関連箇所（参考。ここに書かれていないことは推測しないこと）\n"
                f"{excerpts}\n"
            )

    prompt = _DECOMPOSITION_PROMPT.format(
        requirement_type=requirement.type,
        requirement_title=requirement.title,
        requirement_description=requirement.description,
        extra_context=extra_context,
    )
    result, error = await call_llm_json(client, prompt)

    if result is None:
        return [], f"requirement={requirement.id}: {error}"

    raw_list = result.get("tasks")
    if not isinstance(raw_list, list):
        return [], f"requirement={requirement.id}: 'tasks'が配列ではない: {result!r}"

    candidates: List[TaskCandidate] = []
    for item in raw_list:
        if not isinstance(item, dict):
            continue

        title = str(item.get("title") or "").strip()
        description = str(item.get("description") or "").strip()
        if not title or not description:
            continue  # 情報が無いのに埋め合わせで作り出すことはしない

        priority = item.get("priority") if item.get("priority") in _VALID_PRIORITIES else "unknown"

        estimated_hours = item.get("estimated_hours")
        if not isinstance(estimated_hours, (int, float)) or isinstance(estimated_hours, bool):
            estimated_hours = None

        required_skills = item.get("required_skills")
        if not isinstance(required_skills, list) or not required_skills:
            required_skills = ["unknown"]
        else:
            required_skills = [str(s) for s in required_skills]

        acceptance_criteria = item.get("acceptance_criteria")
        if not isinstance(acceptance_criteria, list):
            acceptance_criteria = []
        else:
            acceptance_criteria = [str(c) for c in acceptance_criteria]

        confidence = item.get("confidence")
        if not isinstance(confidence, (int, float)) or isinstance(confidence, bool) or not (0.0 <= confidence <= 1.0):
            confidence = 0.5  # 妥当な確信度が示されなければ中立値にする（高い確信度を捏造しない）

        candidates.append(TaskCandidate(
            requirement_ids=[requirement.id],
            title=title,
            description=description,
            priority=priority,
            estimated_hours=float(estimated_hours) if estimated_hours is not None else None,
            required_skills=required_skills,
            acceptance_criteria=acceptance_criteria,
            # 出典はRequirementから機械的に引き継ぐだけ。元の仕様書は再パースしない
            source_reference=requirement.source_reference,
            confidence=float(confidence),
            related_sources=related_sources,
        ))

    return candidates, None
