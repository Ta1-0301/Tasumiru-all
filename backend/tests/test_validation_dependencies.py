# backend/tests/test_validation_dependencies.py
"""backend/pipeline/validation/dependencies.py の単体テスト（CHECK 3）。"""

from backend.pipeline.dependencies.schema import Dependency
from backend.pipeline.validation.dependencies import (
    check_assigned_before_dependencies,
    check_circular_dependencies,
    check_dependencies,
    check_impossible_ordering,
    check_missing_dependency_references,
)

TASK_IDS = ["TASK-001", "TASK-002", "TASK-003"]


def _dep(from_id, to_id, type="required", confidence=0.9) -> Dependency:
    return Dependency(from_task_id=from_id, to_task_id=to_id, type=type, confidence=confidence)


# --- missing dependency references ---

def test_missing_dependency_reference_is_flagged():
    deps = [_dep("TASK-001", "TASK-999")]
    errors = check_missing_dependency_references(deps, TASK_IDS)
    assert any(e.code == "MISSING_DEPENDENCY_REFERENCE" for e in errors)


def test_valid_dependency_references_produce_no_error():
    deps = [_dep("TASK-001", "TASK-002")]
    assert check_missing_dependency_references(deps, TASK_IDS) == []


# --- circular dependencies ---

def test_circular_dependency_is_flagged():
    deps = [_dep("TASK-001", "TASK-002"), _dep("TASK-002", "TASK-001")]
    errors = check_circular_dependencies(deps, TASK_IDS)
    assert any(e.code == "CIRCULAR_DEPENDENCY" for e in errors)


def test_linear_chain_has_no_circular_dependency():
    deps = [_dep("TASK-001", "TASK-002"), _dep("TASK-002", "TASK-003")]
    assert check_circular_dependencies(deps, TASK_IDS) == []


# --- impossible ordering ---

def test_required_only_cycle_is_impossible_ordering():
    deps = [_dep("TASK-001", "TASK-002", type="required"), _dep("TASK-002", "TASK-001", type="required")]
    errors = check_impossible_ordering(deps, ["TASK-001", "TASK-002"])
    assert any(e.code == "IMPOSSIBLE_ORDERING" for e in errors)


def test_optional_only_cycle_is_not_impossible_ordering():
    deps = [_dep("TASK-001", "TASK-002", type="optional"), _dep("TASK-002", "TASK-001", type="optional")]
    assert check_impossible_ordering(deps, ["TASK-001", "TASK-002"]) == []


# --- tasks assigned before required dependencies ---

def test_dependent_assigned_before_prerequisite_is_flagged():
    deps = [_dep("TASK-001", "TASK-002", type="required")]
    assignments = {"TASK-002": "M-001"}  # TASK-001(前提)は未割り当て
    errors = check_assigned_before_dependencies(deps, assignments)
    assert any(e.code == "ASSIGNED_BEFORE_DEPENDENCY" for e in errors)


def test_prerequisite_assigned_first_produces_no_error():
    deps = [_dep("TASK-001", "TASK-002", type="required")]
    assignments = {"TASK-001": "M-001", "TASK-002": "M-002"}
    assert check_assigned_before_dependencies(deps, assignments) == []


def test_neither_task_assigned_produces_no_error():
    deps = [_dep("TASK-001", "TASK-002", type="required")]
    assert check_assigned_before_dependencies(deps, {}) == []


def test_optional_dependency_is_not_checked_for_assignment_order():
    deps = [_dep("TASK-001", "TASK-002", type="optional")]
    assignments = {"TASK-002": "M-001"}
    assert check_assigned_before_dependencies(deps, assignments) == []


# --- aggregation ---

def test_check_dependencies_aggregates_all_four_checks():
    deps = [
        _dep("TASK-001", "TASK-002", type="required"),
        _dep("TASK-002", "TASK-001", type="required"),  # circular + impossible
        _dep("TASK-001", "TASK-999"),                    # missing reference
    ]
    errors = check_dependencies(deps, TASK_IDS, {"TASK-002": "M-001"})
    codes = {e.code for e in errors}
    assert "MISSING_DEPENDENCY_REFERENCE" in codes
    assert "CIRCULAR_DEPENDENCY" in codes
    assert "IMPOSSIBLE_ORDERING" in codes


def test_check_dependencies_clean_plan_has_no_errors():
    deps = [_dep("TASK-001", "TASK-002", type="required")]
    assignments = {"TASK-001": "M-001", "TASK-002": "M-002"}
    assert check_dependencies(deps, TASK_IDS, assignments) == []
