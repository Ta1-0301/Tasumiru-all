# backend/pipeline/validation/

Phase 8: タスクアサイン後の、プロジェクト計画全体の検証。

```
requirements (Phase 3) + tasks (Phase 4) + dependencies (Phase 5)
    + members (Phase 6) + assignments (Phase 7, task_id -> member_id)
    ↓
CHECK 1  Missing Requirements    (missing_requirements.py — 決定的)
CHECK 2  Duplicates              (duplicates.py — 決定的 + 任意のLLM検証)
CHECK 3  Dependencies            (dependencies.py — 決定的)
CHECK 4  Workload                (workload.py — 決定的)
CHECK 5  Skill Mismatch          (skill_mismatch.py — 決定的)
CHECK 6  Assignment Constraints  (constraints.py — 決定的、Phase 7の再利用)
    ↓
ValidationReport                  (runner.py が output/ に保存)
```

**このパッケージは何も修復しない。** 見つけた問題を`ValidationReport`に
含めて報告するだけ。フロントエンドがこれを警告として表示する想定。

## 各CHECKの実装方針

| CHECK | 内容 | LLM |
|---|---|---|
| 1. Missing Requirements | `Task.requirement_ids`から参照されていない要求を検出 | 不使用 |
| 2. Duplicates | タイトルの文字列類似度(difflib)で重複候補を検出。**削除は一切しない** | 任意（意味的な検証のみ、候補の増減はしない） |
| 3. Dependencies | 循環依存・存在しないタスク参照・required依存だけのサイクル（実行不可能）・前提未割り当てのまま後続を割り当て済み、の4種 | 不使用（Phase 5の`DependencyGraph`を再利用） |
| 4. Workload | assignments+tasksから割り当て時間を再集計し、稼働率・過負荷を判定 | 不使用 |
| 5. Skill Mismatch | 必要スキル(名前+任意でレベル) vs 担当メンバーのスキル | 不使用 |
| 6. Assignment Constraints | 確定した割り当てが、Phase 7のハード制約(必要スキル・稼働可否・工数上限・明示的制約)を満たすかを再確認 | 不使用（Phase 7の`filters.py`を再利用） |

## なぜCHECK 6が必要か

Phase 7のHuman Override（`backend/pipeline/assignment/override.py`）は、
マネージャーがAIの推薦を無視して別のメンバーを割り当てることを明示的に
許可している。その上書きがハード制約に違反していないかは、Phase 7自身
では再確認されない（人間の最終決定を制限しないという設計上の判断）。
CHECK 6は、**確定した割り当て一覧**に対してその確認をやり直す、最後の
安全網である。違反があっても割り当てを取り消したりはせず、
`constraint_violations`として報告するだけ。

## CHECK 4とCHECK 6のワークロードの違い

- CHECK 4は、`assignments`+`tasks`から**このプロジェクト計画における
  合計割り当て時間**をメンバーごとに再集計する（複数タスクの積み上げを
  検出できる）。
- CHECK 6が再利用するPhase 7の`check_workload`は、**個々のタスク1件**が
  `Member.availability`のスナップショット（他の業務等を含むかもしれない
  既存の稼働状況）に収まるかだけを見る。

両方が必要: CHECK 4は「このプロジェクト内での積み上げ」、CHECK 6は
「個々の割り当てがそもそも成立するか」を別の角度から検証する。

## 実行方法

```bash
python -m backend.pipeline.validation.runner \
    requirements.json tasks.json dependencies.json members.json assignments.json [--llm]
```

`assignments.json`は`{"TASK-001": "M-001", ...}`という単純なマッピング。
Phase 7の`FinalAssignment`一覧から作る場合は
`runner.assignments_from_final(final_assignments)`を使う。

## 既知の限界

- CHECK 2の重複検出はタイトルの文字列類似度のみを見る。意味は近いが
  表現が大きく異なるタスクは検出できない（LLM検証はあくまで「検出済みの
  候補」の確認用であり、新しい候補の発見には使わない）。
- CHECK 5/6のスキルレベル要求は、Phase 4の`Task.required_skills`
  （レベル無し、名前のみ）にフォールバックした場合、レベル1(Beginner)
  以上を持っていればよいという最も緩い判定になる。より厳密な判定をしたい
  場合は`required_skill_levels`（`task_id -> List[RequiredSkill]`）を渡す。
