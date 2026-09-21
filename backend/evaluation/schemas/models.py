# backend/evaluation/schemas/models.py
"""
評価結果のデータ構造。

設計方針:
1. 採点は0-5の6段階（`backend/evaluation/schemas/rubric.py`のRUBRICを参照）。
2. 1つの基準に対して、ルールベース(rule_score)・LLM-judge(llm_score)・
   人手評価(human_score)の3つのソースを同時に保持できる（`ScoreDetail`）。
   「LLM-as-judgeだけに依存しない」という要件を満たすため、人手評価が
   存在する場合は常に人手評価を最優先で採用する（`effective_score`）。
3. タスクの出典(`SourceTraceability`)は、パイプラインが機械的に転記した
   実データのみを保持する。取得できない項目（例: page。プレーンテキストの
   仕様書にはページの概念が無い）は誠実にNoneのままにし、捏造しない。
4. `ReproducibilityRecord`が再現性のために必要な情報
   （モデル・モデルバージョン・プロンプトバージョン・temperature・実行時刻・
   入力文書・生成結果・評価結果）を1件にまとめて保持する。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field, computed_field

Score = Literal[0, 1, 2, 3, 4, 5]


class SourceTraceability(BaseModel):
    """タスクが仕様書のどこから来たかを表す出典情報。

    値は必ずパイプラインの機械的な処理結果からの転記であり、評価コードが
    作り出した値は含まない。取得できない項目は素直にNoneとする。
    """

    document_id: str
    page: Optional[int] = Field(
        None, description="ページ番号。プレーンテキスト仕様書にはページの概念が無いため常にNone。"
    )
    section: Optional[str] = Field(None, description="条項見出し等（例: 第2条(納期)）。無ければNone。")
    paragraph: Optional[str] = Field(None, description="段落/チャンクの識別子（chunk_id）。")
    source_text: Optional[str] = Field(None, description="出典の原文抜粋。仕様書本文からの実在の部分文字列。")


class ScoreDetail(BaseModel):
    """1つの評価基準に対する、採点方法ごとのスコア。"""

    rule_score: Optional[Score] = None
    llm_score: Optional[Score] = None
    human_score: Optional[Score] = None
    human_rater: Optional[str] = None
    human_comment: Optional[str] = None

    @computed_field  # type: ignore[misc]
    @property
    def effective_score(self) -> Optional[Score]:
        """今採用すべき点数。人手 > LLM-judge > ルールベース の優先順。"""
        if self.human_score is not None:
            return self.human_score
        if self.llm_score is not None:
            return self.llm_score
        return self.rule_score

    @computed_field  # type: ignore[misc]
    @property
    def source(self) -> Optional[Literal["human", "llm", "rule"]]:
        if self.human_score is not None:
            return "human"
        if self.llm_score is not None:
            return "llm"
        if self.rule_score is not None:
            return "rule"
        return None


class TaskEvaluation(BaseModel):
    """1つの生成タスクに対する評価結果（7つのタスク単位基準）"""

    task_id: str
    title: str
    source: SourceTraceability
    scores: Dict[str, ScoreDetail]
    issues: List[str] = Field(default_factory=list)

    @computed_field  # type: ignore[misc]
    @property
    def overall_score(self) -> Optional[float]:
        values = [d.effective_score for d in self.scores.values() if d.effective_score is not None]
        if not values:
            return None
        return round(sum(values) / len(values), 2)


class DocumentEvaluation(BaseModel):
    """1つの仕様書（＝1回の生成結果）に対する評価結果"""

    document_id: str
    generated_task_count: int
    ground_truth_task_count: int
    scores: Dict[str, ScoreDetail]  # coverage / non_duplication
    task_evaluations: List[TaskEvaluation]
    issues: List[str] = Field(default_factory=list)

    @computed_field  # type: ignore[misc]
    @property
    def overall_score(self) -> Optional[float]:
        doc_level_values = [d.effective_score for d in self.scores.values() if d.effective_score is not None]
        task_scores = [t.overall_score for t in self.task_evaluations if t.overall_score is not None]
        task_mean = sum(task_scores) / len(task_scores) if task_scores else None

        components = list(doc_level_values)
        if task_mean is not None:
            components.append(task_mean)
        if not components:
            return None
        return round(sum(components) / len(components), 2)


class ModelConfig(BaseModel):
    """評価対象/判定者となるモデルの設定（再現性の記録対象そのもの）"""

    key: str
    provider: str
    model: str
    model_version: Optional[str] = None
    temperature: Optional[float] = None
    notes: Optional[str] = None


class ReproducibilityRecord(BaseModel):
    """1回の評価実行を再現するために必要な情報一式。"""

    model: str
    model_version: Optional[str]
    prompt_version: str
    temperature: Optional[float]
    timestamp: datetime
    input_document_id: str
    input_document_text: str
    generated_result: List[Dict[str, Any]]
    evaluation_result: DocumentEvaluation


class HumanScoreEntry(BaseModel):
    """人手評価者が付けた1件のスコア。

    task_id が None の場合は文書単位の基準（coverage/non_duplication）への
    評価とみなす。
    """

    document_id: str
    task_id: Optional[str] = None
    criterion: str
    score: Score
    rater: str
    comment: Optional[str] = None
