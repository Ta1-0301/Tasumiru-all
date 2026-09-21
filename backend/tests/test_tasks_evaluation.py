# backend/tests/test_tasks_evaluation.py
"""backend/pipeline/tasks/evaluation.py の単体テスト。"""

from backend.pipeline.requirements.schema import SourceReference
from backend.pipeline.tasks.evaluation import (
    evaluate_task,
    evaluate_task_document,
    score_actionability,
    score_clear_objective,
    score_clear_outcome,
    score_granularity,
    score_traceability,
)
from backend.pipeline.tasks.schema import Task, TaskDocument


def _good_task(**overrides) -> Task:
    defaults = dict(
        id="TASK-001",
        requirement_ids=["REQ-001"],
        title="ファイルアップロードAPIを実装する",
        description="仕様書ファイルを受け取り保存するAPIエンドポイントを実装する",
        priority="high",
        estimated_hours=8,
        required_skills=["FastAPI"],
        acceptance_criteria=["アップロードでき、保存されることを確認できる"],
        source_reference=SourceReference(
            document_id="doc_1", section="第1条", source_text="仕様書ドキュメントをアップロードできる",
        ),
        confidence=0.9,
    )
    defaults.update(overrides)
    return Task(**defaults)


def test_score_clear_objective_high_for_focused_task():
    score, issues = score_clear_objective(_good_task())
    assert score == 5


def test_score_clear_objective_low_for_system_wide_task():
    score, issues = score_clear_objective(_good_task(title="システム全体を実装する"))
    assert score == 0
    assert issues


def test_score_actionability_low_without_verb():
    score, issues = score_actionability(_good_task(title="アップロードAPI"))
    assert score == 1
    assert issues


def test_score_actionability_high_with_clear_verb():
    score, issues = score_actionability(_good_task())
    assert score == 5


def test_score_clear_outcome_low_without_acceptance_criteria():
    score, issues = score_clear_outcome(_good_task(acceptance_criteria=[]))
    assert score == 1
    assert issues


def test_score_clear_outcome_high_with_multiple_criteria():
    score, issues = score_clear_outcome(
        _good_task(acceptance_criteria=["条件A", "条件B"])
    )
    assert score == 5


def test_score_granularity_low_for_broad_task():
    score, issues = score_granularity(_good_task(title="システム全体を実装する"))
    assert score == 0


def test_score_granularity_high_for_focused_task():
    score, issues = score_granularity(_good_task())
    assert score == 5


def test_score_traceability_zero_without_source_reference():
    score, issues = score_traceability(_good_task(source_reference=None))
    assert score == 0
    assert issues


def test_score_traceability_high_with_section():
    score, issues = score_traceability(_good_task())
    assert score == 5


def test_score_traceability_partial_without_section():
    task = _good_task(source_reference=SourceReference(document_id="doc_1", source_text="出典テキスト"))
    score, issues = score_traceability(task)
    assert score == 4


def test_evaluate_task_returns_all_five_dimensions():
    result = evaluate_task(_good_task())
    assert set(result["scores"]) == {
        "clear_objective", "actionability", "clear_outcome", "granularity", "traceability",
    }
    assert result["overall_score"] > 4.0


def test_evaluate_task_document_aggregates_across_tasks():
    doc = TaskDocument(
        document_id="doc_1",
        tasks=[_good_task(id="TASK-001"), _good_task(id="TASK-002", title="システム全体を実装する")],
    )
    result = evaluate_task_document(doc)
    assert result["task_count"] == 2
    assert len(result["per_task"]) == 2
    assert result["document_overall_score"] is not None


def test_evaluate_task_document_handles_empty_task_list():
    doc = TaskDocument(document_id="doc_1", tasks=[])
    result = evaluate_task_document(doc)
    assert result["task_count"] == 0
    assert result["document_overall_score"] is None
