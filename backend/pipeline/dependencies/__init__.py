# backend/pipeline/dependencies/__init__.py
"""
Phase 5: Phase 4で生成された検証済みタスク一覧（`backend.pipeline.tasks.schema.TaskDocument`）
からタスク間の依存関係を識別するパイプライン。

Tasks (Phase 4の出力) → LLM Dependency Proposal → Dependency Validation → dependencies.json

LLMは依存関係を「提案」するだけで、グラフとしての正しさ（循環依存・自己依存・
存在しないタスクへの参照・重複・実行不可能なグラフ）はPythonの決定的なコードが
検証する。メンバーへの割り当てはこのフェーズでも行わない。
"""
