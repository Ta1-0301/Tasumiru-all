# backend/evaluation/evaluators/human.py
"""
人手評価（マニュアルスコアリング）の入出力。

「LLM-as-judgeだけに依存しない」という要件を満たすため、人間の評価者が
付けたスコアを読み込み、自動評価結果（ルールベース/LLM-judge）に統合できる
ようにする。人手スコアは常に最優先で採用される
（`backend/evaluation/schemas/models.py`の`ScoreDetail.effective_score`を参照）。

入力ファイル形式（JSON配列。1件が`HumanScoreEntry`1件に対応）:

    [
      {"document_id": "spec_a_simple", "task_id": "T-001",
       "criterion": "specificity", "score": 4, "rater": "yamada", "comment": "..."},
      {"document_id": "spec_a_simple", "task_id": null,
       "criterion": "coverage", "score": 3, "rater": "yamada"}
    ]

`task_id` が null の場合は文書単位の基準（coverage/non_duplication）への
評価とみなす。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import List, Union

from backend.evaluation.schemas.models import DocumentEvaluation, HumanScoreEntry


def load_human_scores(path: Union[str, Path]) -> List[HumanScoreEntry]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError("人手評価ファイルはJSON配列である必要があります。")
    return [HumanScoreEntry.model_validate(item) for item in data]


def apply_human_scores(
    document_evaluation: DocumentEvaluation, entries: List[HumanScoreEntry]
) -> DocumentEvaluation:
    """人手評価を該当するScoreDetailにマージした新しいDocumentEvaluationを返す（引数は変更しない）"""
    doc = document_evaluation.model_copy(deep=True)

    for entry in entries:
        if entry.document_id != doc.document_id:
            continue

        if entry.task_id is None:
            if entry.criterion not in doc.scores:
                raise ValueError(f"未知の文書単位の評価基準です: {entry.criterion}")
            detail = doc.scores[entry.criterion]
        else:
            task = next((t for t in doc.task_evaluations if t.task_id == entry.task_id), None)
            if task is None:
                raise ValueError(f"人手評価対象のタスクが見つかりません: {entry.task_id}")
            if entry.criterion not in task.scores:
                raise ValueError(f"未知のタスク単位の評価基準です: {entry.criterion}")
            detail = task.scores[entry.criterion]

        detail.human_score = entry.score
        detail.human_rater = entry.rater
        detail.human_comment = entry.comment

    return doc
