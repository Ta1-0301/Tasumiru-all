# backend/tests/test_dependencies_validator.py
"""backend/pipeline/dependencies/validator.py の単体テスト。LLMは使わない。

依頼された5つのテストケース（linear dependency / parallel tasks /
circular dependency / self dependency / nonexistent task）をすべてカバーする。
"""

from backend.pipeline.dependencies.schema import Dependency
from backend.pipeline.dependencies.validator import (
    check_circular_dependencies,
    check_duplicate_dependencies,
    check_impossible_graph,
    check_missing_reason,
    check_nonexistent_task_references,
    check_self_dependencies,
    validate_dependencies,
)

TASK_IDS = ["TASK-001", "TASK-002", "TASK-003"]


def _dep(from_task_id, to_task_id, type="required", reason="意味のある理由", confidence=0.9):
    return Dependency(from_task_id=from_task_id, to_task_id=to_task_id, type=type, reason=reason, confidence=confidence)


# --- linear dependency: クリーンなケースは何も検出されない ---

def test_linear_dependency_produces_no_issues():
    deps = [_dep("TASK-001", "TASK-002"), _dep("TASK-002", "TASK-003")]
    issues = validate_dependencies(deps, TASK_IDS)
    assert issues == []


# --- parallel tasks: 独立した2つの依存はどちらも問題なし ---

def test_parallel_tasks_produce_no_issues():
    deps = [_dep("TASK-001", "TASK-002"), _dep("TASK-001", "TASK-003")]
    issues = validate_dependencies(deps, TASK_IDS)
    assert issues == []


# --- circular dependency ---

def test_circular_dependency_is_flagged():
    deps = [_dep("TASK-001", "TASK-002"), _dep("TASK-002", "TASK-003"), _dep("TASK-003", "TASK-001")]
    issues = check_circular_dependencies(deps, TASK_IDS)
    assert any(i.code == "CIRCULAR_DEPENDENCY" for i in issues)


def test_required_only_cycle_is_also_flagged_as_impossible():
    deps = [
        _dep("TASK-001", "TASK-002", type="required"),
        _dep("TASK-002", "TASK-001", type="required"),
    ]
    issues = check_impossible_graph(deps, ["TASK-001", "TASK-002"])
    assert any(i.code == "IMPOSSIBLE_DEPENDENCY_GRAPH" for i in issues)


def test_optional_only_cycle_is_circular_but_not_impossible():
    """optional種別だけのサイクルは無視すれば実行できるため、circularではあるが
    impossibleとしては報告されない"""
    deps = [
        _dep("TASK-001", "TASK-002", type="optional"),
        _dep("TASK-002", "TASK-001", type="optional"),
    ]
    circular = check_circular_dependencies(deps, ["TASK-001", "TASK-002"])
    impossible = check_impossible_graph(deps, ["TASK-001", "TASK-002"])
    assert any(i.code == "CIRCULAR_DEPENDENCY" for i in circular)
    assert impossible == []


# --- self dependency ---

def test_self_dependency_is_flagged():
    deps = [_dep("TASK-001", "TASK-001")]
    issues = check_self_dependencies(deps)
    assert len(issues) == 1
    assert issues[0].code == "SELF_DEPENDENCY"
    assert issues[0].edges[0].from_task_id == "TASK-001"


def test_self_dependency_is_not_also_reported_as_circular():
    deps = [_dep("TASK-001", "TASK-001")]
    circular = check_circular_dependencies(deps, TASK_IDS)
    assert circular == []


# --- nonexistent task ---

def test_nonexistent_task_reference_is_flagged():
    deps = [_dep("TASK-001", "TASK-999")]
    issues = check_nonexistent_task_references(deps, TASK_IDS)
    assert len(issues) == 1
    assert issues[0].code == "NONEXISTENT_TASK_REFERENCE"


def test_nonexistent_task_reference_reports_both_missing_ids():
    deps = [_dep("TASK-888", "TASK-999")]
    issues = check_nonexistent_task_references(deps, TASK_IDS)
    assert "TASK-888" in issues[0].message
    assert "TASK-999" in issues[0].message


def test_existing_task_references_produce_no_issue():
    deps = [_dep("TASK-001", "TASK-002")]
    assert check_nonexistent_task_references(deps, TASK_IDS) == []


# --- duplicate dependencies ---

def test_duplicate_dependency_is_flagged():
    deps = [_dep("TASK-001", "TASK-002"), _dep("TASK-001", "TASK-002", type="optional")]
    issues = check_duplicate_dependencies(deps)
    assert any(i.code == "DUPLICATE_DEPENDENCY" for i in issues)


def test_distinct_dependencies_are_not_flagged_as_duplicate():
    deps = [_dep("TASK-001", "TASK-002"), _dep("TASK-002", "TASK-003")]
    assert check_duplicate_dependencies(deps) == []


# --- missing reason ---

def test_missing_reason_is_flagged():
    deps = [Dependency(from_task_id="TASK-001", to_task_id="TASK-002", confidence=0.5)]
    issues = check_missing_reason(deps)
    assert any(i.code == "MISSING_REASON" for i in issues)


# --- validate_dependencies aggregation ---

def test_validate_dependencies_aggregates_all_checks():
    deps = [
        _dep("TASK-001", "TASK-001"),          # self dependency
        _dep("TASK-001", "TASK-999"),          # nonexistent task
        _dep("TASK-001", "TASK-002"),
        _dep("TASK-001", "TASK-002"),           # duplicate
    ]
    issues = validate_dependencies(deps, TASK_IDS)
    codes = {i.code for i in issues}
    assert "SELF_DEPENDENCY" in codes
    assert "NONEXISTENT_TASK_REFERENCE" in codes
    assert "DUPLICATE_DEPENDENCY" in codes
