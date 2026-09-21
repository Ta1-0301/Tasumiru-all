# backend/tests/test_validation_task_quality.py
"""backend/pipeline/validation/task_quality.py の単体テスト（CHECK 7、決定的）。"""

from backend.pipeline.requirements.schema import SourceReference
from backend.pipeline.tasks.schema import Task
from backend.pipeline.validation.task_quality import check_task_quality


def _task(**overrides) -> Task:
    defaults = dict(
        id="TASK-001", requirement_ids=["REQ-001"], title="t", description="d",
        confidence=0.8, source_reference=SourceReference(document_id="doc-1", source_text="x"),
    )
    defaults.update(overrides)
    return Task(**defaults)


def test_needs_review_task_is_reported_with_its_reasons():
    task = _task(needs_review=True, review_reasons=["INVALID_ESTIMATED_HOURS: 非現実的です"])
    issues = check_task_quality([task])
    assert any(i.code == "NEEDS_REVIEW" and i.task_id == "TASK-001" for i in issues)


def test_clean_task_produces_no_needs_review_issue():
    task = _task(needs_review=False)
    issues = check_task_quality([task])
    assert not any(i.code == "NEEDS_REVIEW" for i in issues)


def test_unknown_required_skills_is_flagged():
    task = _task(required_skills=["unknown"])
    issues = check_task_quality([task])
    assert any(i.code == "MISSING_REQUIRED_SKILLS" for i in issues)


def test_empty_required_skills_is_flagged():
    task = _task(required_skills=[])
    issues = check_task_quality([task])
    assert any(i.code == "MISSING_REQUIRED_SKILLS" for i in issues)


def test_specified_required_skills_is_not_flagged():
    task = _task(required_skills=["Python"])
    issues = check_task_quality([task])
    assert not any(i.code == "MISSING_REQUIRED_SKILLS" for i in issues)
