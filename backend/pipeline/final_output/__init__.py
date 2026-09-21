# backend/pipeline/final_output/__init__.py
"""
Phase 9: 最終的な構造化プロジェクト出力の組み立て。

**このフェーズは新しい情報を一切生成しない。** Phase 3-8で既に検証済みの
中間結果（requirements/tasks/dependencies/members/assignments/validation）
をそのまま転記し、再構成するだけ。新規に計算するのはタイムスタンプ・
プロンプトのフィンガープリント・valid/warning/errorの分類ラベルのみ
（いずれも既存データからの機械的な導出であり、内容の推測・創作ではない）。

トレーサビリティ:
  Requirement -> Task -> Dependency -> Assignment
の関係が保たれていることを検証する（特に「すべてのタスクが1つ以上の
要求に紐づいているか」は、Phase 8のCHECK 1では見ていない向きの検証
であるため、このフェーズで独自に追加している）。

検証結果に重大な問題(status=="error")がある場合でも、`assemble_final_output`
自体は組み立てを拒否しない（検証結果を隠さず常に完全な形で報告するのが
このフェーズの役目）。「問題無い完成品として扱ってよいか」の最終判断は
`ensure_safe_to_publish`を呼び出す側が行う。
"""
