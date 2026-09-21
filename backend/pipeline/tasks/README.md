# backend/pipeline/tasks/

Phase 4: Phase 3で生成された構造化要求（`backend/pipeline/requirements/`の
`RequirementDocument`）を、実行可能な開発タスクに分解するパイプライン。

```
Requirements (Phase 3の出力)
    ↓
LLM Task Decomposition   (decomposer.py — Requirementごとに逐次実行)
    ↓
Task Validation          (validator.py — 決定的。無効な結果は修復せず
                           needs_review/review_reasonsとして印を付けるだけ)
    ↓
tasks.json                (runner.py が output/ に保存)
```

**メンバーへの割り当て・タスク間の依存関係の構築はこのフェーズでは行わない。**
`backend/services/matcher.py`は呼び出さない。

**元の仕様書は直接パースし直さない。** 各タスクの出典(`source_reference`)は
入力のRequirementから機械的に引き継ぐだけ。元の仕様書テキストを渡した場合に
限り、出典の再検証（`validator.check_source_text_matches_document`）だけに
使われる。

## モジュール構成

| ファイル | 役割 |
|---|---|
| `schema.py` | `Task`/`TaskDocument`等。`SourceReference`/`Priority`はPhase 3のものを再利用 |
| `decomposer.py` | LLM Task Decomposition。`BaseLLMClient`のみに依存し、プロバイダー固有の処理を含まない |
| `validator.py` | Task Validation。要求無しタスク・重複・広すぎ/細かすぎ・出典欠落・完了基準欠落・工数の妥当性を検出する決定的な処理。**修復はしない** |
| `evaluation.py` | 評価支援。GOAL節の「良いタスク」の条件（明確な目的/着手可能性/明確な完了基準/適切な粒度/出典保持）を0-5で自己点検する |
| `runner.py` | 全体のオーケストレーターとCLIエントリポイント |

## 実行方法

```bash
source .venv/bin/activate
export LLM_PROVIDER=ollama OLLAMA_BASE_URL=http://localhost:11434
python -m backend.pipeline.tasks.runner backend/pipeline/requirements/output/spec_a_20260101T000000Z.requirements.json
```

出典の再検証もしたい場合は、元の仕様書テキストファイルを第2引数に渡す:

```bash
python -m backend.pipeline.tasks.runner path/to/requirements.json path/to/original_spec.txt
```

モデルは`LLM_PROVIDER`で切り替えられる（既存の`get_llm_client()`をそのまま
使用。このパッケージのコードはOllama固有の処理を一切含まない）。

## 「無効な結果を黙って修復しない」について

`validator.validate_tasks()`は問題点を`ValidationIssue`として返すだけで、
タスクのどのフィールドも書き換えない。`validator.apply_review_flags()`が
その結果を`Task.needs_review`/`Task.review_reasons`として反映するが、
これも「印を付ける」だけであり、`title`/`estimated_hours`等の値そのものを
補正することは一切しない。

## 既知の限界

- `check_overly_broad_tasks`/`check_overly_granular_tasks`は字面ベースの
  簡易ヒューリスティックであり、意味理解を伴わない。
- `evaluation.py`はタスクを個別に採点するのみで、要求全体に対するタスク群
  としての網羅性（Phase 2の`coverage`相当）は評価しない。
