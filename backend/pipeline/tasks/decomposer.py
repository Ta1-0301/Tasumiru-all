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

from typing import List, Optional, Sequence, Tuple

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

# チームスキル語彙（team_skill_vocabulary）を渡された場合だけプロンプトに追加する節。
# 語彙は「required_skillsの表記をそろえるための対応表」であり、スキルの候補一覧ではない。
# gemma3:4b等の小さなモデルは「一覧」や「例の答え」をそのまま出力に写しやすい
# （実測: v2でテスト報告書→Figma、v3で例に書いた「技術文書作成」「要件定義」がそのまま出力、
#   チーム全体の語彙から無関係なscikit-learnが混入）ため、
#   1. required_skillsの意味（Taskを実行するのに必要なもの。担当者の都合ではない）
#   2. 作業内容から先に判断する順序
#   3. スキル名がタスク文に書かれている例だけを示す（例の外にある「答え」を見せない）
#   4. 作業の目的がセキュリティの場合だけ、セキュリティの知識を落とさない
#   5. 表記対応表はチーム全体のもので、大半はこのタスクと無関係であること
# を示し、表記対応表は「同じスキルの表記」を確認するためだけに使わせる。
_TEAM_SKILL_VOCABULARY_CONTEXT = """
## required_skillsの決め方
required_skillsは「そのタスクを実行するために必要な技術・知識・能力」です。
担当者候補・チームが持っているスキル・担当者を見つけるためのスキルではありません。
仕様書に名前が出てくるだけの技術や、プロジェクト全体で使う技術も、そのタスクの作業に使わなければ含めません。

各タスクについて、次の順番で決めてください。
1. そのタスクで具体的に何をするかを確認する
2. その作業を行うために必要なスキルを、作業内容だけから判断する
3. 判断したスキルと同じスキルが、下の「表記対応表」にある場合だけ、その表記に書き換える
4. 表記対応表に同じスキルが無ければ、判断したスキル名をそのまま使う（別のスキルに置き換えない）
5. 作業に使わないスキルは追加しない（表記対応表に載っているという理由で追加しない）

判断のしかた:
- 作業内容に技術やツールが書かれている場合は、その技術・ツールと、それを使うのに直接必要な言語などを書く
  （例:「PostgreSQLのテーブルを設計する」→ ["PostgreSQL"]、「FastAPIで認証APIを実装する」→ ["FastAPI", "Python"]、
    「Reactでログイン画面を実装する」→ ["React", "TypeScript", "HTML/CSS"]、「管理画面のUIをFigmaで設計する」→ ["Figma"]）
- 文書作成・計画・報告・調整・レビュー・テストのように、技術やツールを使わない作業にも必要なスキルはある。
  作業内容に書かれている作業の種類や対象分野を、そのままスキル名として書く
  （作業に使わない技術・ツール名は付けない。必要な知識・能力が作業内容から分かる場合は "unknown" にしない）
- 作業の目的がセキュリティにある場合（暗号化・ハッシュ化・トークンやパスワードの保護・脆弱性対策・認証や認可の設計・
  セキュリティのレビューなど）は、実装に使う技術があればそれに加えて、セキュリティの知識を含める（省略しない）。
  目的がセキュリティでない作業には付けない

## 表記対応表（チーム全体のメンバーが登録しているスキル名）
チーム全体のスキルなので、ほとんどはこのタスクとは無関係です。
手順3で「同じスキルの表記」を確認するためだけに使うこと。スキルを選ぶための一覧ではない。
{vocabulary}
"""


def format_team_skill_vocabulary_context(team_skill_vocabulary: Optional[Sequence[str]]) -> str:
    """チームスキル語彙のプロンプト節を組み立てる。語彙が無ければ空文字列
    （＝プロンプトは従来と完全に同一）を返す。
    """
    names = [s.strip() for s in (team_skill_vocabulary or []) if s and s.strip()]
    if not names:
        return ""
    return _TEAM_SKILL_VOCABULARY_CONTEXT.format(vocabulary=", ".join(names))


async def decompose_requirement(
    requirement: Requirement,
    client: BaseLLMClient,
    *,
    spec_index: Optional[SpecIndex] = None,
    embedding_client: Optional[BaseEmbeddingClient] = None,
    top_k: int = 3,
    team_skill_vocabulary: Optional[Sequence[str]] = None,
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

    `team_skill_vocabulary`は任意引数（既定はNone）。チームメンバーが実際に
    登録しているスキル名の一覧で、required_skillsを書く際の「参考語彙」として
    プロンプトに追加するだけ（RAGとは独立）。None/空のときはプロンプト・挙動とも
    従来と完全に同一。LLMの呼び出し回数は変わらない（1 Requirement = 1回のまま）。
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
        extra_context=extra_context + format_team_skill_vocabulary_context(team_skill_vocabulary),
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
