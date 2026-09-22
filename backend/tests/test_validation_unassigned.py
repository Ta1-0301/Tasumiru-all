# backend/tests/test_validation_unassigned.py
"""backend/pipeline/validation/unassigned.py の単体テスト（CHECK 9、決定的）。"""

from backend.pipeline.assignment.schema import AssignmentResult, FinalAssignment
from backend.pipeline.validation.unassigned import check_unassigned_tasks


def _final_assignment(task_id, assigned_member_id, unassigned_reason=None) -> FinalAssignment:
    status = "recommended" if assigned_member_id else "no_suitable_member"
    return FinalAssignment(
        task_id=task_id,
        assigned_member_id=assigned_member_id,
        decided_by="ai",
        ai_recommendation=AssignmentResult(
            task_id=task_id,
            recommended_member_id=assigned_member_id,
            status=status,
            unassigned_reason=unassigned_reason,
        ),
    )


def test_assigned_task_produces_no_issue():
    fa = _final_assignment("TASK-001", "M-001")
    assert check_unassigned_tasks([fa]) == []


def test_unassigned_task_is_flagged_with_its_reason():
    fa = _final_assignment("TASK-001", None, unassigned_reason="NO_REQUIRED_SKILL")
    issues = check_unassigned_tasks([fa])
    assert len(issues) == 1
    assert issues[0].task_id == "TASK-001"
    assert issues[0].reason == "NO_REQUIRED_SKILL"
    assert issues[0].message


def test_missing_reason_falls_back_to_unknown_not_fabricated():
    fa = _final_assignment("TASK-001", None, unassigned_reason=None)
    issues = check_unassigned_tasks([fa])
    assert issues[0].reason == "UNKNOWN"


def test_empty_list_returns_empty():
    assert check_unassigned_tasks([]) == []


def test_multiple_tasks_mixed_assigned_and_unassigned():
    assignments = [
        _final_assignment("TASK-001", "M-001"),
        _final_assignment("TASK-002", None, unassigned_reason="NO_AVAILABILITY"),
        _final_assignment("TASK-003", None, unassigned_reason="WORKLOAD_TOO_HIGH"),
    ]
    issues = check_unassigned_tasks(assignments)
    assert {i.task_id for i in issues} == {"TASK-002", "TASK-003"}
