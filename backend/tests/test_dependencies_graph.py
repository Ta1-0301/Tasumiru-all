# backend/tests/test_dependencies_graph.py
"""backend/pipeline/dependencies/graph.py の単体テスト。完全に決定的。"""

import pytest

from backend.pipeline.dependencies.graph import DependencyGraph, GraphCycleError
from backend.pipeline.dependencies.schema import Dependency


def _dep(from_task_id, to_task_id, type="required", confidence=0.9):
    return Dependency(from_task_id=from_task_id, to_task_id=to_task_id, type=type, confidence=confidence)


# --- linear dependency ---

def test_linear_dependency_topological_order_and_levels():
    deps = [_dep("TASK-001", "TASK-002"), _dep("TASK-002", "TASK-003")]
    graph = DependencyGraph(["TASK-001", "TASK-002", "TASK-003"], deps)

    order = graph.topological_order()
    assert order.index("TASK-001") < order.index("TASK-002") < order.index("TASK-003")

    levels = graph.levels()
    assert levels == {"TASK-001": 0, "TASK-002": 1, "TASK-003": 2}
    assert graph.find_cycle() is None


def test_linear_dependency_successors_and_predecessors():
    deps = [_dep("TASK-001", "TASK-002"), _dep("TASK-002", "TASK-003")]
    graph = DependencyGraph(["TASK-001", "TASK-002", "TASK-003"], deps)
    assert graph.successors("TASK-001") == ["TASK-002"]


# --- parallel tasks ---

def test_parallel_tasks_share_the_same_level():
    # TASK-002とTASK-003はどちらもTASK-001に依存するが、互いには依存しない（並行可能）
    deps = [_dep("TASK-001", "TASK-002"), _dep("TASK-001", "TASK-003")]
    graph = DependencyGraph(["TASK-001", "TASK-002", "TASK-003"], deps)

    levels = graph.levels()
    assert levels["TASK-001"] == 0
    assert levels["TASK-002"] == levels["TASK-003"] == 1
    assert graph.find_cycle() is None


def test_isolated_task_with_no_dependencies_is_level_zero():
    deps = [_dep("TASK-001", "TASK-002")]
    graph = DependencyGraph(["TASK-001", "TASK-002", "TASK-003"], deps)
    levels = graph.levels()
    assert levels["TASK-003"] == 0  # 誰にも依存しない孤立タスク


# --- circular dependency ---

def test_circular_dependency_is_detected():
    deps = [_dep("TASK-001", "TASK-002"), _dep("TASK-002", "TASK-003"), _dep("TASK-003", "TASK-001")]
    graph = DependencyGraph(["TASK-001", "TASK-002", "TASK-003"], deps)

    cycle = graph.find_cycle()
    assert cycle is not None
    assert cycle[0] == cycle[-1]
    assert set(cycle) == {"TASK-001", "TASK-002", "TASK-003"}


def test_circular_dependency_makes_topological_order_raise():
    deps = [_dep("TASK-001", "TASK-002"), _dep("TASK-002", "TASK-001")]
    graph = DependencyGraph(["TASK-001", "TASK-002"], deps)
    with pytest.raises(GraphCycleError):
        graph.topological_order()


def test_cycle_detection_can_be_scoped_to_a_single_type():
    # requiredのサイクルだけを見た場合は検出されるが、optionalだけ見た場合は無い
    deps = [
        _dep("TASK-001", "TASK-002", type="required"),
        _dep("TASK-002", "TASK-001", type="required"),
        _dep("TASK-002", "TASK-003", type="optional"),
    ]
    graph = DependencyGraph(["TASK-001", "TASK-002", "TASK-003"], deps)
    assert graph.find_cycle(types=("required",)) is not None
    assert graph.find_cycle(types=("optional",)) is None


# --- self dependency ---

def test_self_dependency_is_ignored_by_cycle_detection():
    """自己依存は専用のチェック(validator.check_self_dependencies)の対象であり、
    グラフのサイクル検出では「長さ1のサイクル」として二重に報告しない"""
    deps = [_dep("TASK-001", "TASK-001"), _dep("TASK-001", "TASK-002")]
    graph = DependencyGraph(["TASK-001", "TASK-002"], deps)
    assert graph.find_cycle() is None
    assert graph.topological_order() == ["TASK-001", "TASK-002"]


# --- nonexistent task reference ---

def test_nonexistent_task_reference_does_not_crash_graph_construction():
    """存在しないタスクIDへの参照があってもグラフ構築・走査は例外を出さない
    （存在確認自体はvalidator.check_nonexistent_task_referencesの責務）"""
    deps = [_dep("TASK-001", "TASK-999")]
    graph = DependencyGraph(["TASK-001", "TASK-002"], deps)
    order = graph.topological_order()
    assert "TASK-999" in order  # 幽霊ノードとしてでも扱われ、クラッシュしない
    assert graph.find_cycle() is None


def test_to_dict_contains_nodes_edges_and_levels():
    deps = [_dep("TASK-001", "TASK-002")]
    graph = DependencyGraph(["TASK-001", "TASK-002"], deps)
    result = graph.to_dict()
    assert result["nodes"] == ["TASK-001", "TASK-002"]
    assert len(result["edges"]) == 1
    assert result["levels"] == {"TASK-001": 0, "TASK-002": 1}
    assert result["required_cycle"] is None


def test_to_dict_reports_required_cycle_when_levels_cannot_be_computed():
    deps = [_dep("TASK-001", "TASK-002", type="required"), _dep("TASK-002", "TASK-001", type="required")]
    graph = DependencyGraph(["TASK-001", "TASK-002"], deps)
    result = graph.to_dict()
    assert result["levels"] == {}
    assert result["required_cycle"] is not None
