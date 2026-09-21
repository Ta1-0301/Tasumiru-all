# backend/pipeline/validation/__init__.py
"""
Phase 8: タスクアサイン後の、プロジェクト計画全体の検証。

入力（すべて前フェーズの出力）:
  - requirements  (Phase 3: backend.pipeline.requirements.schema.Requirement)
  - tasks         (Phase 4: backend.pipeline.tasks.schema.Task)
  - dependencies  (Phase 5: backend.pipeline.dependencies.schema.Dependency)
  - members       (Phase 6: backend.pipeline.members.schema.Member)
  - assignments   (Phase 7: task_id -> member_id のマッピング。
                    `backend.pipeline.assignment.schema.FinalAssignment`から
                    導出できる)

このパッケージ自身は何も「直す」ことをしない。検出した問題を
`ValidationReport`として報告するだけで、**検証エラーを黒黙に握り潰さない**
（依頼の"Validation errors must not be silently ignored"に対応）。
このレポートはフロントエンドが警告として表示する想定。
"""
