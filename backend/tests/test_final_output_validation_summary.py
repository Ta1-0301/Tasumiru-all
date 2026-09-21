# backend/tests/test_final_output_validation_summary.py
"""backend/pipeline/final_output/validation_summary.py の単体テスト。

Phase 8のValidationReport(bool一本)からvalid/warning/errorの3段階分類を
組み立てるロジックを検証する。
"""

from backend.pipeline.tasks.schema import Task
from backend.pipeline.validation.schema import (
    ConstraintViolation,
    DependencyError,
    DuplicateTaskGroup,
    MissingRequirement,
    SkillMismatch,
    ValidationReport,
    WorkloadWarning,
)
from backend.pipeline.final_output.validation_summary import build_validation_summary


def _task(id, requirement_ids=None) -> Task:
    if requirement_ids is None:
        requirement_ids = ["REQ-001"]
    return Task(id=id, requirement_ids=requirement_ids, title="t", description="d", confidence=0.9)


def test_clean_report_and_traceable_tasks_yield_valid_status():
    report = ValidationReport(valid=True)
    summary = build_validation_summary(report, [_task("TASK-001")])
    assert summary.status == "valid"
    assert summary.critical_issue_count == 0
    assert summary.warning_issue_count == 0


def test_missing_requirement_is_critical():
    report = ValidationReport(valid=False, missing_requirements=[MissingRequirement(requirement_id="REQ-002", message="m")])
    summary = build_validation_summary(report, [_task("TASK-001")])
    assert summary.status == "error"
    assert summary.critical_issue_count == 1


def test_constraint_violation_is_critical():
    report = ValidationReport(
        valid=False,
        constraint_violations=[ConstraintViolation(task_id="TASK-001", member_id="M-001", code="X", message="m")],
    )
    summary = build_validation_summary(report, [_task("TASK-001")])
    assert summary.status == "error"


def test_circular_dependency_error_is_critical():
    report = ValidationReport(
        valid=False,
        dependency_errors=[DependencyError(code="CIRCULAR_DEPENDENCY", message="m")],
    )
    summary = build_validation_summary(report, [_task("TASK-001")])
    assert summary.status == "error"


def test_assigned_before_dependency_error_is_only_a_warning():
    report = ValidationReport(
        valid=False,
        dependency_errors=[DependencyError(code="ASSIGNED_BEFORE_DEPENDENCY", message="m")],
    )
    summary = build_validation_summary(report, [_task("TASK-001")])
    assert summary.status == "warning"
    assert summary.critical_issue_count == 0
    assert summary.warning_issue_count == 1


def test_duplicate_tasks_is_only_a_warning():
    report = ValidationReport(
        valid=False,
        duplicate_tasks=[DuplicateTaskGroup(task_ids=["TASK-001", "TASK-002"], similarity=0.9, method="rule", reason="m")],
    )
    summary = build_validation_summary(report, [_task("TASK-001")])
    assert summary.status == "warning"


def test_workload_warning_is_only_a_warning():
    report = ValidationReport(
        valid=False,
        workload_warnings=[WorkloadWarning(member_id="M-001", assigned_hours=50, available_hours=40, remaining_capacity=-10, workload_percentage=125, code="OVERLOAD", message="m")],
    )
    summary = build_validation_summary(report, [_task("TASK-001")])
    assert summary.status == "warning"


def test_skill_mismatch_is_only_a_warning():
    report = ValidationReport(
        valid=False,
        skill_mismatches=[SkillMismatch(task_id="TASK-001", member_id="M-001", skill="Python", required_level=3, member_level=1, message="m")],
    )
    summary = build_validation_summary(report, [_task("TASK-001")])
    assert summary.status == "warning"


def test_untraceable_task_is_critical_even_if_report_itself_is_clean():
    """Phase 8のCHECK 1は逆方向しか見ないため、report.valid=Trueでもこのフェーズ
    独自のトレーサビリティ検証が問題を検出する"""
    report = ValidationReport(valid=True)
    summary = build_validation_summary(report, [_task("TASK-001", requirement_ids=[])])
    assert summary.status == "error"
    assert len(summary.traceability_errors) == 1


def test_critical_and_warning_issues_together_still_report_error():
    report = ValidationReport(
        valid=False,
        missing_requirements=[MissingRequirement(requirement_id="REQ-002", message="m")],
        duplicate_tasks=[DuplicateTaskGroup(task_ids=["TASK-001", "TASK-002"], similarity=0.9, method="rule", reason="m")],
    )
    summary = build_validation_summary(report, [_task("TASK-001")])
    assert summary.status == "error"
    assert summary.critical_issue_count == 1
    assert summary.warning_issue_count == 1


def test_underlying_report_is_never_dropped_from_the_summary():
    """検証結果を黙って握り潰さない: 元のreportは常にsummary.reportにそのまま残る"""
    report = ValidationReport(valid=False, missing_requirements=[MissingRequirement(requirement_id="REQ-002", message="m")])
    summary = build_validation_summary(report, [_task("TASK-001")])
    assert summary.report is report
