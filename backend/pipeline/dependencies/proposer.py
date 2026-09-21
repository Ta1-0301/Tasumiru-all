# backend/pipeline/dependencies/proposer.py
"""
Stage: LLM Dependency Proposal。

Phase 4の検証済みタスク一覧を入力として受け取り、タスク間の依存関係を
「提案」する。グラフとしての正しさ（循環依存等）はこの層の責務ではない
——`backend.pipeline.dependencies.validator`が決定的に検証する。

`backend.services.llm.BaseLLMClient`だけに依存する（`complete()`しか呼ばない）。
プロバイダー固有の処理・モデル名は一切ハードコードしない。
"""

from __future__ import annotations

from typing import List, Optional, Tuple

from backend.pipeline.dependencies.schema import Dependency
from backend.pipeline.tasks.schema import Task
from backend.services.llm import BaseLLMClient
from backend.services.pipeline.llm_json import call_llm_json

_VALID_TYPES = {"required", "recommended", "optional"}
_DEFAULT_TYPE = "optional"
_DEFAULT_CONFIDENCE = 0.3  # 型が不明/不正な提案は確信度を低めに倒す（高い確信度を捏造しない）

_DEPENDENCY_PROMPT = """\
あなたはソフトウェア開発のプロジェクト管理者です。以下は検証済みの開発タスク
一覧です。タスク間の依存関係を提案してください。

## 依存関係の方向
from_task_id は「先に完了すべきタスク」、to_task_id は「それに続くタスク」です。
例:「データベース設計(TASK-001)」が終わらないと「バックエンドAPI実装(TASK-002)」
に着手できない場合、from_task_id="TASK-001", to_task_id="TASK-002" とします。

## 依存の種別(type)
- required   : 前提タスクが完了しないと後続タスクに着手できない
- recommended: 前提タスクを先に終える方が望ましいが、必須ではない
- optional   : 関連はあるが、順序を強制する必要は無い

## ルール
- 意味のある理由がある場合のみ依存関係を作成すること
- 同じカテゴリ・同じ要求から来ているという理由だけで依存関係があると
  仮定しないこと（本当に順序上の制約がある場合のみ作成すること）
- from_task_id/to_task_idには、以下のタスク一覧のIDのみを使うこと
  （一覧に無いIDを作り出さないこと）
- reasonには、なぜその依存関係が必要かを簡潔に書くこと
- 確信が持てない場合はconfidenceを低くすること
- 依存関係が無ければ空配列を返すこと

## タスク一覧
{task_list}

出力は必ず以下のJSON形式のみ。説明文やMarkdownは不要です。

{{"dependencies": [
  {{"from_task_id": "TASK-001", "to_task_id": "TASK-002", "type": "required",
    "reason": "短い理由", "confidence": 0.9}}
]}}
"""


def _format_task_list(tasks: List[Task]) -> str:
    return "\n".join(f"- {t.id}: {t.title} — {t.description}" for t in tasks)


async def propose_dependencies(
    tasks: List[Task], client: BaseLLMClient
) -> Tuple[List[Dependency], Optional[str]]:
    """タスク一覧から依存関係候補を提案する。戻り値は (依存関係一覧, エラーメッセージ)。

    LLM呼び出し自体が失敗した場合のみエラーを返す。個々の項目が不正な形式
    （from_task_id/to_task_id欠損等）の場合はその項目だけを黙って捨てる。
    """
    if len(tasks) < 2:
        return [], None  # 依存関係を定義するには2件以上のタスクが必要

    prompt = _DEPENDENCY_PROMPT.format(task_list=_format_task_list(tasks))
    result, error = await call_llm_json(client, prompt)

    if result is None:
        return [], error

    raw_list = result.get("dependencies")
    if not isinstance(raw_list, list):
        return [], f"'dependencies'が配列ではない: {result!r}"

    dependencies: List[Dependency] = []
    for item in raw_list:
        if not isinstance(item, dict):
            continue

        from_task_id = str(item.get("from_task_id") or "").strip()
        to_task_id = str(item.get("to_task_id") or "").strip()
        if not from_task_id or not to_task_id:
            continue  # 辺を定義するのに必須の情報が無い

        dep_type = item.get("type") if item.get("type") in _VALID_TYPES else _DEFAULT_TYPE
        reason = str(item.get("reason") or "").strip()

        confidence = item.get("confidence")
        if (
            not isinstance(confidence, (int, float))
            or isinstance(confidence, bool)
            or not (0.0 <= confidence <= 1.0)
        ):
            confidence = _DEFAULT_CONFIDENCE

        dependencies.append(Dependency(
            from_task_id=from_task_id,
            to_task_id=to_task_id,
            type=dep_type,
            reason=reason,
            confidence=float(confidence),
        ))

    return dependencies, None
