# backend/pipeline/members/__init__.py
"""
Phase 6: タスクアサインのための、構造化されたメンバー情報。

**このパッケージにLLMは一切使われていない。** メンバーのスキルレベルを
LLMが自動で作り出すことは禁止されている（依頼の"Member skill levels must NOT
be automatically invented by the LLM"に対応）。スキルレベルは以下のいずれか
から人間が入力した値のみを起点とする:

  - user input（本人の入力）
  - team manager input（チームマネージャーの入力）
  - imported data（外部データの取り込み）
  - confirmed historical data（過去の確定済みデータ）

このフェーズではタスクアサイン（割り当てロジック）はまだ実装しない。
構造化されたデータモデルと、その検証だけを提供する。
"""
