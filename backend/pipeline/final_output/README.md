# backend/pipeline/final_output/

Phase 9: 検証済みの中間結果から、最終的な構造化プロジェクト出力を組み立てる。

```
requirements (Phase 3) + tasks (Phase 4) + dependencies (Phase 5)
    + members (Phase 6) + assignments (Phase 7) + validation (Phase 8)
    ↓
assemble_final_output()   (assembler.py — LLM不使用、新しい情報を生成しない)
    ↓
FinalProjectOutput          (schema.py。runner.py が output/ に保存)
```

**このフェーズはLLMを一切呼ばない。** 前フェーズの出力をそのまま転記・
再構成するだけ。

## モジュール構成

| ファイル | 役割 |
|---|---|
| `schema.py` | `FinalProjectOutput`。依頼のFINAL JSON節と1対1対応。`requirements`/`tasks`/`dependencies`/`members`/`assignments`はPhase 3-7の型をそのまま再利用する |
| `traceability.py` | 「すべてのタスクが1つ以上の要求に紐づいているか」を検証する（Phase 8のCHECK 1とは逆方向。このフェーズ独自） |
| `metadata.py` | 再現性情報（model/model_version/prompt_versions/pipeline_version）の計算 |
| `validation_summary.py` | Phase 8の`ValidationReport`(bool一本)を valid/warning/error の3段階に分類する |
| `assembler.py` | 組み立て本体。`ensure_safe_to_publish()`という明示的なゲート関数も提供する |
| `json_schema.py` | `FinalProjectOutput`のJSON Schema出力・任意JSONの検証 |
| `runner.py` | CLIエントリポイントと永続化 |

## valid / warning / error の分類

Phase 8の`ValidationReport`は`valid: bool`しか持たない。このフェーズは
依頼の"Clearly distinguish: valid / warning / error"を満たすため、
`validation_summary.py`で3段階に分類し直す:

| 分類 | 対応する問題 |
|---|---|
| error（critical） | missing_requirements / constraint_violations / dependency_errors中のCIRCULAR_DEPENDENCY・IMPOSSIBLE_ORDERING・MISSING_DEPENDENCY_REFERENCE / タスク→要求のトレーサビリティ欠落 |
| warning | duplicate_tasks / dependency_errors中のASSIGNED_BEFORE_DEPENDENCY / workload_warnings / skill_mismatches |
| valid | 上記のいずれも無い |

## 「重大なエラーがあるのに正常に見える出力を出さない」について

`assemble_final_output()`自体は`status=="error"`でも組み立てを拒否しない
——検証結果を隠さず常に完全な形で報告するのがこのフェーズの役目だから。
代わりに`ensure_safe_to_publish(output)`という明示的なゲート関数を提供する。
これは、この出力を「確定済みの成果物」として配信・表示する側
（エクスポートAPI等）が呼ぶべきもので、`status=="error"`なら
`CriticalValidationError`を発生させる。

```python
output = assemble_final_output(req_doc, task_doc, dep_doc, member_dir, assignments, validation_report)
ensure_safe_to_publish(output)  # status=="error"ならここで例外
```

## 再現性(REPRODUCIBILITY)

`metadata`に以下を記録する:

| フィールド | 内容 |
|---|---|
| `generated_at` | 生成時刻(UTC, ISO8601) |
| `pipeline_version` | `metadata.py`の`PIPELINE_VERSION`定数 |
| `model` / `model_version` | Phase 3-5のドキュメントが記録した`model`が全フェーズで一致する場合のみ設定。一致しない/不明な場合はNoneのままにし、`models_by_phase`に詳細を残す（捏造しない） |
| `prompt_versions` | 各フェーズの本番プロンプト文面から計算したSHA-256フィンガープリント（読み取り専用。プロンプト自体は変更しない） |
| `document_id` | 元の仕様書のID（`RequirementDocument.document_id`） |

## JSON Schema

```python
from backend.pipeline.final_output.json_schema import get_json_schema, validate_output_json

schema = get_json_schema()               # 標準的なJSON Schema(dict)
errors = validate_output_json(some_dict)  # [] なら合致、そうでなければエラー文字列のリスト
```

## 既知の限界

- `project.name`は明示的に渡されなければ`None`のままにする（存在しない
  プロジェクト名を作り出さない）。
- `model`/`model_version`は、各フェーズが実際に記録した値からのみ解決する。
  1つのフェーズでもLLMを呼ばなかった（`model`が記録されていない）場合、
  そのフェーズは`models_by_phase`の集計に含まれない。
