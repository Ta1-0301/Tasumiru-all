# backend/pipeline/validation/dependencies.py
"""
CHECK 3: Dependencies。

完全に決定的（LLM不使用）。Phase 5(`backend.pipeline.dependencies.graph`)の
グラフ表現をそのまま再利用し、サイクル検出等を重複実装しない。

  - circular dependencies              -> check_circular_dependencies
  - missing dependency references      -> check_missing_dependency_references
  - tasks assigned before required dependencies -> check_assigned_before_dependencies
  - impossible ordering                -> check_impossible_ordering
    （required種別の辺だけでサイクルがある場合。Phase 5の
      "impossible dependency graph"と同じ考え方）
"""

from __future__ import annotations

from typing import Dict, List, Sequence

from backend.pipeline.dependencies.graph import DependencyGraph
from backend.pipeline.dependencies.schema import Dependency
from backend.pipeline.validation.schema import DependencyError


def check_missing_dependency_references(
    dependencies: List[Dependency], valid_task_ids: Sequence[str]
) -> List[DependencyError]:
    valid = set(valid_task_ids)
    errors: List[DependencyError] = []
    for d in dependencies:
        missing = [tid for tid in (d.from_task_id, d.to_task_id) if tid not in valid]
        if missing:
            errors.append(DependencyError(
                code="MISSING_DEPENDENCY_REFERENCE",
                message=f"存在しないタスクIDを参照しています: {missing}",
                task_ids=[d.from_task_id, d.to_task_id],
            ))
    return errors


def check_circular_dependencies(
    dependencies: List[Dependency], valid_task_ids: Sequence[str]
) -> List[DependencyError]:
    graph = DependencyGraph(valid_task_ids, dependencies)
    cycle = graph.find_cycle()
    if cycle is None:
        return []
    return [DependencyError(
        code="CIRCULAR_DEPENDENCY",
        message=f"循環依存が検出されました: {' -> '.join(cycle)}",
        task_ids=list(dict.fromkeys(cycle)),
    )]


def check_impossible_ordering(
    dependencies: List[Dependency], valid_task_ids: Sequence[str]
) -> List[DependencyError]:
    """required種別の依存関係だけでサイクルがあり、実行順序を一切決定できない場合を検出する"""
    graph = DependencyGraph(valid_task_ids, dependencies)
    cycle = graph.find_cycle(types=("required",))
    if cycle is None:
        return []
    return [DependencyError(
        code="IMPOSSIBLE_ORDERING",
        message=f"required種別の依存関係だけでサイクルがあり、実行順序を決定できません: {' -> '.join(cycle)}",
        task_ids=list(dict.fromkeys(cycle)),
    )]


def check_assigned_before_dependencies(
    dependencies: List[Dependency], assignments: Dict[str, str]
) -> List[DependencyError]:
    """前提タスク(required)が未割り当てなのに、後続タスクには既に担当者が
    割り当てられている場合を検出する（着手順序の矛盾）。
    """
    errors: List[DependencyError] = []
    for d in dependencies:
        if d.type != "required":
            continue
        prerequisite_assigned = d.from_task_id in assignments
        dependent_assigned = d.to_task_id in assignments
        if dependent_assigned and not prerequisite_assigned:
            errors.append(DependencyError(
                code="ASSIGNED_BEFORE_DEPENDENCY",
                message=(
                    f"'{d.to_task_id}'には担当者が割り当てられていますが、"
                    f"前提タスク'{d.from_task_id}'はまだ割り当てられていません"
                ),
                task_ids=[d.from_task_id, d.to_task_id],
            ))
    return errors


def check_dependencies(
    dependencies: List[Dependency],
    valid_task_ids: Sequence[str],
    assignments: Dict[str, str],
) -> List[DependencyError]:
    """依頼された4種類の依存関係チェックすべてを実行する"""
    errors: List[DependencyError] = []
    errors += check_missing_dependency_references(dependencies, valid_task_ids)
    errors += check_circular_dependencies(dependencies, valid_task_ids)
    errors += check_impossible_ordering(dependencies, valid_task_ids)
    errors += check_assigned_before_dependencies(dependencies, assignments)
    return errors
