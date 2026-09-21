# backend/pipeline/dependencies/graph.py
"""
依存関係グラフの表現。完全に決定的（LLM不使用）。

辺 (from_task_id -> to_task_id) は「from_task_idが完了しないとto_task_idに
着手できない」という意味（from が先行、to が後続）。`backend.pipeline.dependencies
.validator`のサイクル検出・実行順序決定はすべてこのモジュールを使う。

自己依存(from==to)は`find_cycle`/`topological_order`/`levels`では常に無視する
（自己依存は`validator.check_self_dependencies`という専用のチェックで扱うため、
ここで「長さ1のサイクル」として二重に報告しない）。
"""

from __future__ import annotations

from collections import defaultdict, deque
from typing import Dict, List, Optional, Sequence

from backend.pipeline.dependencies.schema import Dependency


class GraphCycleError(Exception):
    """指定した種別の辺だけでサイクルがあり、実行順序を決定できない場合"""


class DependencyGraph:
    def __init__(self, task_ids: Sequence[str], dependencies: Sequence[Dependency]):
        self.task_ids: List[str] = list(dict.fromkeys(task_ids))
        self.dependencies: List[Dependency] = list(dependencies)

    def _edges(self, types: Optional[Sequence[str]] = None):
        for d in self.dependencies:
            if types is not None and d.type not in types:
                continue
            if d.from_task_id == d.to_task_id:
                continue  # 自己依存は別チェック(check_self_dependencies)の対象
            yield d

    def _adjacency(self, types: Optional[Sequence[str]] = None) -> Dict[str, List[str]]:
        adjacency: Dict[str, List[str]] = defaultdict(list)
        for d in self._edges(types=types):
            adjacency[d.from_task_id].append(d.to_task_id)
        return adjacency

    def successors(self, task_id: str, types: Optional[Sequence[str]] = None) -> List[str]:
        return list(self._adjacency(types=types).get(task_id, []))

    def find_cycle(self, types: Optional[Sequence[str]] = None) -> Optional[List[str]]:
        """指定した種別（Noneなら全種別）の辺だけでサイクルを探す。

        見つかった場合、サイクルを構成するタスクIDのリスト
        （[A, B, C, A] のように開始点で閉じた形）を返す。無ければNone。
        """
        adjacency = self._adjacency(types=types)
        nodes = set(adjacency.keys()) | {n for succs in adjacency.values() for n in succs}

        WHITE, GRAY, BLACK = 0, 1, 2
        color: Dict[str, int] = defaultdict(int)
        path: List[str] = []

        def dfs(node: str) -> Optional[List[str]]:
            color[node] = GRAY
            path.append(node)
            for neighbor in sorted(adjacency.get(node, [])):
                if color[neighbor] == GRAY:
                    cycle_start = path.index(neighbor)
                    return path[cycle_start:] + [neighbor]
                if color[neighbor] == WHITE:
                    found = dfs(neighbor)
                    if found:
                        return found
            path.pop()
            color[node] = BLACK
            return None

        for node in sorted(nodes):
            if color[node] == WHITE:
                cycle = dfs(node)
                if cycle:
                    return cycle
        return None

    def topological_order(self, types: Optional[Sequence[str]] = None) -> List[str]:
        """Kahnのアルゴリズムによる位相ソート。指定種別の辺でサイクルがあれば
        `GraphCycleError`を投げる。辺に現れない孤立タスクも結果に含める。
        """
        adjacency = self._adjacency(types=types)
        indegree: Dict[str, int] = {tid: 0 for tid in self.task_ids}
        for succs in adjacency.values():
            for to_id in succs:
                indegree[to_id] = indegree.get(to_id, 0) + 1
        for from_id in adjacency:
            indegree.setdefault(from_id, indegree.get(from_id, 0))

        queue = deque(sorted(tid for tid, deg in indegree.items() if deg == 0))
        order: List[str] = []
        remaining = dict(indegree)

        while queue:
            node = queue.popleft()
            order.append(node)
            for neighbor in sorted(adjacency.get(node, [])):
                remaining[neighbor] -= 1
                if remaining[neighbor] == 0:
                    queue.append(neighbor)

        if len(order) != len(remaining):
            raise GraphCycleError("指定種別の依存関係にサイクルがあり、実行順序を決定できません")
        return order

    def levels(self, types: Optional[Sequence[str]] = None) -> Dict[str, int]:
        """最長経路レイヤリング。同じレベルのタスクは並行して着手できる
        （＝ parallel tasks）。指定種別の辺にサイクルがあれば`GraphCycleError`。
        """
        order = self.topological_order(types=types)
        adjacency = self._adjacency(types=types)

        level: Dict[str, int] = {tid: 0 for tid in self.task_ids}
        for node in order:
            for neighbor in adjacency.get(node, []):
                level[neighbor] = max(level.get(neighbor, 0), level.get(node, 0) + 1)
        return level

    def to_dict(self) -> dict:
        """JSON化可能なグラフ表現。levelsはrequired種別の辺だけを使って計算する
        （recommended/optionalは実行順序を強制しないため）。
        """
        try:
            levels = self.levels(types=("required",))
            required_cycle = None
        except GraphCycleError:
            levels = {}
            required_cycle = self.find_cycle(types=("required",))

        return {
            "nodes": list(self.task_ids),
            "edges": [
                {
                    "from_task_id": d.from_task_id,
                    "to_task_id": d.to_task_id,
                    "type": d.type,
                    "reason": d.reason,
                    "confidence": d.confidence,
                }
                for d in self.dependencies
            ],
            "levels": levels,
            "required_cycle": required_cycle,
        }
