# backend/pipeline/dependencies/validator.py
"""
Stage: Dependency Validation。

決定的（ルールベース、LLM不使用）に完結する。「LLMは依存関係を提案するだけで、
グラフとしての正しさはPythonが検証する」という依頼の方針をそのまま実装した
モジュール。同じ入力に対して常に同じ結果になる。

検出対象:
  - circular dependencies         -> check_circular_dependencies
  - self dependencies             -> check_self_dependencies
  - references to nonexistent tasks -> check_nonexistent_task_references
  - duplicate dependencies        -> check_duplicate_dependencies
  - impossible dependency graphs  -> check_impossible_graph
  - (追加) 理由(reason)が空の依存関係    -> check_missing_reason
"""

from __future__ import annotations

from collections import defaultdict
from typing import Dict, List, Sequence, Tuple

from backend.pipeline.dependencies.graph import DependencyGraph
from backend.pipeline.dependencies.schema import Dependency, EdgeRef, ValidationIssue


def check_self_dependencies(dependencies: List[Dependency]) -> List[ValidationIssue]:
    """タスクが自分自身に依存している辺を検出する"""
    issues: List[ValidationIssue] = []
    for d in dependencies:
        if d.from_task_id == d.to_task_id:
            issues.append(ValidationIssue(
                code="SELF_DEPENDENCY",
                message=f"タスクが自分自身に依存しています: {d.from_task_id}",
                edges=[EdgeRef(from_task_id=d.from_task_id, to_task_id=d.to_task_id)],
            ))
    return issues


def check_nonexistent_task_references(
    dependencies: List[Dependency], valid_task_ids: Sequence[str]
) -> List[ValidationIssue]:
    """存在しないタスクIDを参照している辺を検出する"""
    valid = set(valid_task_ids)
    issues: List[ValidationIssue] = []
    for d in dependencies:
        missing = [tid for tid in (d.from_task_id, d.to_task_id) if tid not in valid]
        if missing:
            issues.append(ValidationIssue(
                code="NONEXISTENT_TASK_REFERENCE",
                message=f"存在しないタスクIDを参照しています: {missing}",
                edges=[EdgeRef(from_task_id=d.from_task_id, to_task_id=d.to_task_id)],
            ))
    return issues


def check_duplicate_dependencies(dependencies: List[Dependency]) -> List[ValidationIssue]:
    """同じ(from_task_id, to_task_id)ペアが複数回定義されている辺を検出する"""
    counts: Dict[Tuple[str, str], int] = defaultdict(int)
    for d in dependencies:
        counts[(d.from_task_id, d.to_task_id)] += 1

    issues: List[ValidationIssue] = []
    for (from_id, to_id), count in counts.items():
        if count > 1:
            issues.append(ValidationIssue(
                code="DUPLICATE_DEPENDENCY",
                message=f"同じ依存関係が{count}件重複しています: {from_id} -> {to_id}",
                edges=[EdgeRef(from_task_id=from_id, to_task_id=to_id)],
            ))
    return issues


def check_circular_dependencies(
    dependencies: List[Dependency], valid_task_ids: Sequence[str]
) -> List[ValidationIssue]:
    """種別を問わず、依存関係のグラフにサイクルがあるかを検出する"""
    graph = DependencyGraph(valid_task_ids, dependencies)
    cycle = graph.find_cycle()
    if cycle is None:
        return []
    edges = [EdgeRef(from_task_id=a, to_task_id=b) for a, b in zip(cycle, cycle[1:])]
    return [ValidationIssue(
        code="CIRCULAR_DEPENDENCY",
        message=f"循環依存が検出されました: {' -> '.join(cycle)}",
        edges=edges,
    )]


def check_impossible_graph(
    dependencies: List[Dependency], valid_task_ids: Sequence[str]
) -> List[ValidationIssue]:
    """required種別の依存関係だけでサイクルがある場合を検出する。

    recommended/optionalのサイクルは無視すれば実行できる（circular dependencies
    として警告するだけで済む）が、requiredのサイクルは実行順序を一切決定できない
    ため、より深刻な「実行不可能なグラフ」として区別して報告する。
    """
    graph = DependencyGraph(valid_task_ids, dependencies)
    cycle = graph.find_cycle(types=("required",))
    if cycle is None:
        return []
    edges = [EdgeRef(from_task_id=a, to_task_id=b) for a, b in zip(cycle, cycle[1:])]
    return [ValidationIssue(
        code="IMPOSSIBLE_DEPENDENCY_GRAPH",
        message=f"required種別の依存関係だけでサイクルがあり、実行順序を決定できません: {' -> '.join(cycle)}",
        edges=edges,
    )]


def check_missing_reason(dependencies: List[Dependency]) -> List[ValidationIssue]:
    """理由(reason)が空の依存関係を検出する（依頼の"meaningful reason"の要件に対応）"""
    issues: List[ValidationIssue] = []
    for d in dependencies:
        if not d.reason or not d.reason.strip():
            issues.append(ValidationIssue(
                code="MISSING_REASON",
                message=f"依存関係の理由(reason)が空です: {d.from_task_id} -> {d.to_task_id}",
                edges=[EdgeRef(from_task_id=d.from_task_id, to_task_id=d.to_task_id)],
            ))
    return issues


def validate_dependencies(
    dependencies: List[Dependency], valid_task_ids: Sequence[str]
) -> List[ValidationIssue]:
    """依頼された5種類 + 追加1種類の検証すべてを実行し、1つのリストにまとめる"""
    issues: List[ValidationIssue] = []
    issues += check_self_dependencies(dependencies)
    issues += check_nonexistent_task_references(dependencies, valid_task_ids)
    issues += check_duplicate_dependencies(dependencies)
    issues += check_circular_dependencies(dependencies, valid_task_ids)
    issues += check_impossible_graph(dependencies, valid_task_ids)
    issues += check_missing_reason(dependencies)
    return issues
