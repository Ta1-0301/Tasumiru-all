# backend/pipeline/dependencies/

Phase 5: Phase 4で生成された検証済みタスク一覧
（`backend/pipeline/tasks/`の`TaskDocument`）から、タスク間の依存関係を
識別するパイプライン。

```
Tasks (Phase 4の出力)
    ↓
LLM Dependency Proposal   (proposer.py — タスク一覧全体を1回で提案)
    ↓
Dependency Validation     (validator.py — 決定的。循環依存・自己依存・
                            存在しないタスク参照・重複・実行不可能なグラフを検出)
    ↓
DependencyGraph表現       (graph.py)
    ↓
dependencies.json          (runner.py が output/ に保存)
```

**メンバーへの割り当てはこのフェーズでも行わない。**

## 依存関係の方向

辺 `(from_task_id, to_task_id)` は「`from_task_id`が完了しないと
`to_task_id`に着手できない」という意味（fromが先行タスク、toが後続タスク）。

```
TASK-001 (Database design)
    ↓                        from_task_id="TASK-001", to_task_id="TASK-002"
TASK-002 (Backend API)
    ↓                        from_task_id="TASK-002", to_task_id="TASK-003"
TASK-003 (Frontend integration)
```

## モジュール構成

| ファイル | 役割 |
|---|---|
| `schema.py` | `Dependency`/`DependencyDocument`等。依存関係にIDは無く、`(from_task_id, to_task_id)`のペアで識別する |
| `proposer.py` | LLM Dependency Proposal。`BaseLLMClient`のみに依存し、提案するだけ（グラフの正しさは検証しない） |
| `validator.py` | Dependency Validation。循環依存・自己依存・存在しないタスク参照・重複・実行不可能なグラフ(requiredのみのサイクル)・理由欠落を検出する決定的な処理 |
| `graph.py` | `DependencyGraph`表現。サイクル検出・位相ソート・並行実行レベルの計算 |
| `runner.py` | 全体のオーケストレーターとCLIエントリポイント |

## 実行方法

```bash
source .venv/bin/activate
export LLM_PROVIDER=ollama OLLAMA_BASE_URL=http://localhost:11434
python -m backend.pipeline.dependencies.runner backend/pipeline/tasks/output/spec_a_20260101T000000Z.tasks.json
```

## circular dependencies と impossible dependency graphs の違い

- `check_circular_dependencies`: 種別を問わず、依存関係グラフ全体にサイクルが
  あれば警告する（recommended/optionalだけのサイクルは無視すれば実行できる）。
- `check_impossible_graph`: **required種別の依存関係だけ**でサイクルがある
  場合を検出する。requiredは無視できない制約のため、この場合は実行順序を
  一切決定できない、より深刻な問題として区別して報告する
  (`IMPOSSIBLE_DEPENDENCY_GRAPH`)。

## 既知の限界

- LLMは依存関係を1回のプロンプトでタスク一覧全体から提案する。タスク数が
  非常に多い場合はプロンプトが大きくなる（チャンク分割は行っていない）。
- `graph.levels()`はrequired種別の辺だけを使った最長経路レイヤリングであり、
  recommended/optionalは並行実行レベルの計算に影響しない。
