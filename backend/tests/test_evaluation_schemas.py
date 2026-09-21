# backend/tests/test_evaluation_schemas.py
"""
backend/evaluation/schemas/models.py の単体テスト。

- ScoreDetail.effective_score が「人手 > LLM-judge > ルールベース」の
  優先順位で決まること（LLM-as-judgeだけに依存しないことの土台）
- DocumentEvaluation/TaskEvaluationのoverall_scoreが未評価(None)を無視して
  計算されること
- 人手評価ファイルの読み込み・マージ（evaluators/human.py）
"""

import json

import pytest

from backend.evaluation.evaluators.human import apply_human_scores, load_human_scores
from backend.evaluation.schemas.models import (
    DocumentEvaluation,
    HumanScoreEntry,
    ScoreDetail,
    SourceTraceability,
    TaskEvaluation,
)


def _sample_document() -> DocumentEvaluation:
    task = TaskEvaluation(
        task_id="T-001",
        title="認証APIを実装する",
        source=SourceTraceability(document_id="doc_1", source_text="認証APIを実装すること"),
        scores={
            "traceability": ScoreDetail(rule_score=4),
            "specificity": ScoreDetail(llm_score=3),
            "completeness": ScoreDetail(llm_score=None),  # judge失敗などで未評価
        },
    )
    return DocumentEvaluation(
        document_id="doc_1",
        generated_task_count=1,
        ground_truth_task_count=1,
        scores={"coverage": ScoreDetail(llm_score=4), "non_duplication": ScoreDetail(rule_score=5)},
        task_evaluations=[task],
    )


def test_score_detail_prefers_rule_when_only_rule_present():
    detail = ScoreDetail(rule_score=3)
    assert detail.effective_score == 3
    assert detail.source == "rule"


def test_score_detail_prefers_llm_over_rule():
    detail = ScoreDetail(rule_score=2, llm_score=4)
    assert detail.effective_score == 4
    assert detail.source == "llm"


def test_score_detail_prefers_human_over_llm_and_rule():
    detail = ScoreDetail(rule_score=2, llm_score=4, human_score=5)
    assert detail.effective_score == 5
    assert detail.source == "human"


def test_score_detail_with_no_scores_is_none():
    detail = ScoreDetail()
    assert detail.effective_score is None
    assert detail.source is None


def test_task_overall_score_ignores_unset_criteria():
    task = TaskEvaluation(
        task_id="T-001",
        title="t",
        source=SourceTraceability(document_id="doc_1"),
        scores={"a": ScoreDetail(rule_score=4), "b": ScoreDetail(llm_score=None)},
    )
    assert task.overall_score == 4.0


def test_document_overall_score_combines_doc_and_task_levels():
    doc = _sample_document()
    # coverage=4, non_duplication=5, task overall = mean(4,3)=3.5 -> mean(4,5,3.5)=4.17
    assert doc.overall_score == pytest.approx(4.17, abs=0.01)


def test_apply_human_scores_overrides_task_level_criterion():
    doc = _sample_document()
    entries = [
        HumanScoreEntry(document_id="doc_1", task_id="T-001", criterion="specificity", score=1, rater="yamada"),
    ]
    merged = apply_human_scores(doc, entries)

    assert merged.task_evaluations[0].scores["specificity"].effective_score == 1
    assert merged.task_evaluations[0].scores["specificity"].source == "human"
    # 元のオブジェクトは変更されない
    assert doc.task_evaluations[0].scores["specificity"].human_score is None


def test_apply_human_scores_overrides_document_level_criterion():
    doc = _sample_document()
    entries = [
        HumanScoreEntry(document_id="doc_1", task_id=None, criterion="coverage", score=2, rater="yamada"),
    ]
    merged = apply_human_scores(doc, entries)
    assert merged.scores["coverage"].effective_score == 2


def test_apply_human_scores_rejects_unknown_task():
    doc = _sample_document()
    entries = [
        HumanScoreEntry(document_id="doc_1", task_id="T-999", criterion="specificity", score=1, rater="x"),
    ]
    with pytest.raises(ValueError):
        apply_human_scores(doc, entries)


def test_load_human_scores_reads_json_array(tmp_path):
    path = tmp_path / "human_scores.json"
    path.write_text(
        json.dumps([
            {"document_id": "doc_1", "task_id": "T-001", "criterion": "specificity", "score": 5, "rater": "y"},
        ]),
        encoding="utf-8",
    )
    entries = load_human_scores(path)
    assert len(entries) == 1
    assert entries[0].score == 5


def test_load_human_scores_rejects_non_array(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text(json.dumps({"not": "a list"}), encoding="utf-8")
    with pytest.raises(ValueError):
        load_human_scores(path)
