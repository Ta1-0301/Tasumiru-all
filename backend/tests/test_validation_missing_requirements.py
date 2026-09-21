# backend/tests/test_validation_missing_requirements.py
"""backend/pipeline/validation/missing_requirements.py の単体テスト（CHECK 1）。"""

from backend.pipeline.requirements.schema import Requirement
from backend.pipeline.tasks.schema import Task
from backend.pipeline.validation.missing_requirements import find_missing_requirements


def _req(id) -> Requirement:
    return Requirement(id=id, type="functional", title=f"要求{id}", description="説明", confidence=0.9)


def _task(id, requirement_ids) -> Task:
    return Task(id=id, requirement_ids=requirement_ids, title="タスク", description="説明", confidence=0.9)


def test_requirement_with_covering_task_is_not_flagged():
    reqs = [_req("REQ-001")]
    tasks = [_task("TASK-001", ["REQ-001"])]
    assert find_missing_requirements(reqs, tasks) == []


def test_requirement_without_any_task_is_flagged():
    reqs = [_req("REQ-001"), _req("REQ-002")]
    tasks = [_task("TASK-001", ["REQ-001"])]
    missing = find_missing_requirements(reqs, tasks)
    assert len(missing) == 1
    assert missing[0].requirement_id == "REQ-002"


def test_task_covering_multiple_requirements_satisfies_all_of_them():
    reqs = [_req("REQ-001"), _req("REQ-002")]
    tasks = [_task("TASK-001", ["REQ-001", "REQ-002"])]
    assert find_missing_requirements(reqs, tasks) == []


def test_no_tasks_flags_all_requirements():
    reqs = [_req("REQ-001"), _req("REQ-002")]
    missing = find_missing_requirements(reqs, [])
    assert {m.requirement_id for m in missing} == {"REQ-001", "REQ-002"}
