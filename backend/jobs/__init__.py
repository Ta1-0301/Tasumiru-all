# backend/jobs/__init__.py
"""
Phase 10: 既存のPhase 3-9パイプラインをHTTP APIとして公開するための、
ジョブオーケストレーション層。

**このパッケージはPhase 3-9のビジネスロジックを一切変更・複製しない。**
既存の`backend.pipeline.*.runner`の関数をそのまま呼び出すだけで、
プロンプト・LLM呼び出し方法・スコアリング・検証ルールはすべて既存の
実装が唯一の情報源(source of truth)であり続ける。

ここで新規に追加するのは:
  - ジョブの状態管理(manager.py, backend.models.job.JobModel)
  - 各ステージ/各LLM呼び出しのタイミング計測(timing.py) —
    既存のBaseLLMClientをラップするだけで、services/llm.pyやPhase 3-9の
    どのファイルも変更しない
  - Phase 4のTask -> Phase 7のAssignmentTaskへの形式変換(adapters.py) —
    新しいビジネスルールではなく、既存の2つのフェーズの型を橋渡しするだけ
  - 例外をフロントエンド向けの構造化エラーに変換する処理(errors.py)

CLIエントリポイント(各`python -m backend.pipeline.*.runner`)は、
このパッケージとは無関係に、これまで通り単独で動作し続ける
（同じPhase 3-9の関数を呼ぶ「もう一つの入口」であり、別のパイプライン
実装ではない）。
"""
