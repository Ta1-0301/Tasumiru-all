# backend/pipeline/tasks/__init__.py
"""
Phase 4: Phase 3で生成された構造化要求(Requirement)を、実行可能な開発タスクに
分解するパイプライン。

Requirements → LLM Task Decomposition → Task Validation → tasks.json

入力は`backend.pipeline.requirements.schema.RequirementDocument`
（Phase 3の出力）。元の仕様書本文は直接パースし直さない
（出典の再検証が必要な場合のみ、呼び出し側から任意で渡せる）。

`backend/services/pipeline/`（既存のタスク分解パイプライン。Specification→Task）
とは別の、独立したパッケージ。メンバーへの割り当て・タスク間の依存関係の構築は
このフェーズの範囲外であり、一切行わない。
"""
