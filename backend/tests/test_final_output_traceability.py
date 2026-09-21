# backend/tests/test_final_output_traceability.py
"""backend/pipeline/final_output/traceability.py の単体テスト。"""

from backend.pipeline.final_output.traceability import find_untraceable_tasks
from backend.pipeline.tasks.schema import Task


def _task(id, requirement_ids) -> Task:
    return Task(id=id, requirement_ids=requirement_ids, title="タスク", description="説明", confidence=0.9)


def test_task_with_requirement_id_is_traceable():
    tasks = [_task("TASK-001", ["REQ-001"])]
    assert find_untraceable_tasks(tasks) == []


def test_task_without_any_requirement_id_is_flagged():
    tasks = [_task("TASK-001", [])]
    issues = find_untraceable_tasks(tasks)
    assert len(issues) == 1
    assert issues[0].task_id == "TASK-001"
    assert issues[0].code == "TASK_WITHOUT_REQUIREMENT"


def test_mixed_tasks_only_flag_the_untraceable_one():
    tasks = [_task("TASK-001", ["REQ-001"]), _task("TASK-002", [])]
    issues = find_untraceable_tasks(tasks)
    assert [i.task_id for i in issues] == ["TASK-002"]
