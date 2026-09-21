# backend/tests/test_tasks_schema.py
"""backend/pipeline/tasks/schema.py の単体テスト。"""

import pytest
from pydantic import ValidationError

from backend.pipeline.requirements.schema import SourceReference
from backend.pipeline.tasks.schema import Task, TaskCandidate


def _make_task(**overrides):
    defaults = dict(
        id="TASK-001",
        requirement_ids=["REQ-001"],
        title="ファイルアップロードAPIを実装する",
        description="仕様書ファイルを受け取り保存するAPIエンドポイントを実装する",
        priority="high",
        estimated_hours=8,
        required_skills=["Python", "FastAPI"],
        acceptance_criteria=["ファイルをアップロードでき、保存されることを確認できる"],
        source_reference=SourceReference(document_id="doc_1", source_text="仕様書ドキュメントをアップロードできる"),
        confidence=0.9,
    )
    defaults.update(overrides)
    return Task(**defaults)


def test_task_accepts_valid_data():
    task = _make_task()
    assert task.id == "TASK-001"
    assert task.needs_review is False
    assert task.review_reasons == []


def test_task_rejects_invalid_id_format():
    with pytest.raises(ValidationError):
        _make_task(id="not-an-id")


def test_task_rejects_confidence_out_of_range():
    with pytest.raises(ValidationError):
        _make_task(confidence=1.5)
    with pytest.raises(ValidationError):
        _make_task(confidence=-0.1)


def test_task_defaults_priority_and_required_skills():
    task = Task(id="TASK-002", title="t", description="d", confidence=0.5)
    assert task.priority == "unknown"
    assert task.required_skills == ["unknown"]
    assert task.requirement_ids == []
    assert task.acceptance_criteria == []
    assert task.source_reference is None


def test_task_candidate_confidence_defaults_mid():
    candidate = TaskCandidate(title="t", description="d")
    assert candidate.confidence == 0.5


def test_task_can_be_marked_for_review_without_changing_other_fields():
    task = _make_task()
    reviewed = task.model_copy(update={"needs_review": True, "review_reasons": ["ISSUE: 何か問題"]})
    assert reviewed.needs_review is True
    assert reviewed.title == task.title  # 他フィールドは書き換えられない
    assert reviewed.estimated_hours == task.estimated_hours
