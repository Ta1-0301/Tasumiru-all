# backend/tests/test_validation_workload.py
"""backend/pipeline/validation/workload.py の単体テスト（CHECK 4）。"""

from backend.pipeline.members.schema import Availability, Member
from backend.pipeline.tasks.schema import Task
from backend.pipeline.validation.workload import check_workload, compute_workload_summary


def _member(id="M-001", available=40, current=0) -> Member:
    return Member(
        id=id, name=id,
        availability=Availability(available_hours_per_week=available, current_assigned_hours=current),
    )


def _task(id, hours) -> Task:
    return Task(id=id, title="タスク", description="説明", estimated_hours=hours, confidence=0.9)


def test_workload_summary_computed_fresh_from_assignments_not_from_member_snapshot():
    """CHECK 4はassignments+tasksから合計時間を再集計する
    （Memberのcurrent_assigned_hoursスナップショットには依存しない）"""
    member = _member(available=40, current=999)  # 古い/無関係なスナップショット
    tasks = [_task("TASK-001", 10), _task("TASK-002", 5)]
    assignments = {"TASK-001": "M-001", "TASK-002": "M-001"}

    summary = compute_workload_summary(member, tasks, assignments)

    assert summary.assigned_hours == 15
    assert summary.available_hours == 40
    assert summary.remaining_capacity == 25
    assert summary.workload_percentage == 37.5


def test_workload_summary_ignores_tasks_assigned_to_other_members():
    member = _member()
    tasks = [_task("TASK-001", 10)]
    assignments = {"TASK-001": "M-999"}
    summary = compute_workload_summary(member, tasks, assignments)
    assert summary.assigned_hours == 0


def test_workload_summary_handles_zero_available_hours_without_crashing():
    member = _member(available=0, current=0)
    tasks = [_task("TASK-001", 5)]
    summary = compute_workload_summary(member, tasks, {"TASK-001": "M-001"})
    assert summary.workload_percentage == 100.0

    idle_member = _member(id="M-002", available=0)
    idle_summary = compute_workload_summary(idle_member, [], {})
    assert idle_summary.workload_percentage == 0.0


def test_check_workload_flags_overloaded_member():
    member = _member(available=40)
    tasks = [_task("TASK-001", 50)]
    summaries, warnings = check_workload([member], tasks, {"TASK-001": "M-001"})

    assert len(summaries) == 1
    assert any(w.code == "OVERLOAD" for w in warnings)


def test_check_workload_does_not_flag_member_within_capacity():
    member = _member(available=40)
    tasks = [_task("TASK-001", 20)]
    summaries, warnings = check_workload([member], tasks, {"TASK-001": "M-001"})
    assert warnings == []


def test_check_workload_returns_summary_for_every_member_regardless_of_issues():
    members = [_member(id="M-001"), _member(id="M-002")]
    summaries, warnings = check_workload(members, [], {})
    assert len(summaries) == 2
    assert warnings == []
