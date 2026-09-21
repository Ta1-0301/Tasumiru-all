# backend/pipeline/assignment/

Phase 7: タスクへのメンバーアサインを推薦するエンジン。

**LLMだけで最終的な割り当てを決定させない。** 決定的スコアリング・
（有用な場合の）LLMによる補足説明・明示的な制約の3つを組み合わせる。

```
Task (AssignmentTask) + Members (Phase 6のMember一覧)
    ↓
Step 1  Candidate Filtering   (filters.py — 決定的、ハード制約で除外)
    ↓
Step 2  Scoring               (scoring.py — 決定的、設定可能な重み付け)
    ↓
Step 3  LLM Reasoning（任意）  (reasoning.py — 説明文だけを追加、判断は変えない)
    ↓
AssignmentResult               (runner.py が output/ に保存)
    ↓
Human Override                 (override.py — AIの推薦とは別に最終決定を保持)
```

## モジュール構成

| ファイル | 役割 |
|---|---|
| `schema.py` | `AssignmentTask`/`ScoringWeights`/`CandidateScore`/`AssignmentResult`/`FinalAssignment`。`Member`はPhase 6のものを再利用 |
| `filters.py` | Step 1。必要スキル不足・稼働不可・工数超過・明示的な制約違反を検出し、候補者を除外する |
| `scoring.py` | Step 2。skill_match/workload/experience/availabilityの4指標を計算し、`ScoringWeights`で重み付けした0-100点を出す。上位候補が僅差かどうかの判定もここ（決定的） |
| `reasoning.py` | Step 3（任意）。上位候補についてLLMに説明文だけを生成させる。`recommended_member_id`やスコアには影響しない |
| `override.py` | Human Override。AIの推薦(`AssignmentResult`)と人間の最終決定(`FinalAssignment`)を分離して保持する |
| `runner.py` | 全体のオーケストレーターとCLIエントリポイント |

## LLMが「最終判断を単独で行わない」ことの実装上の保証

- Step 1（フィルタリング）はLLMを一切呼ばない。ハード制約で除外された
  メンバーはStep 3にすら渡されない。
- Step 2（スコアリング）もLLMを一切呼ばない。`recommended_member_id`と
  `score`はこの時点で確定する。
- Step 3でLLMから受け取るのは`reasons: List[str]`と`warnings: List[str]`
  だけ（`reasoning.generate_llm_reasoning`の戻り値の型を参照）。
  `recommended_member_id`やスコア、候補者一覧を書き換えるコードパスは
  存在しない。
- `client`を渡さなければStep 3自体が実行されない
  （"Optionally provide top candidates to the LLM"への対応）。

## スコアリングの重み

依頼の例（skill_match 0.50 / workload 0.20 / experience 0.20 /
availability 0.10）を`ScoringWeights`のデフォルト値とする。**この数値は
`schema.py`の`ScoringWeights`にしか書かれていない** —
重みを変更したい場合は呼び出し側で`ScoringWeights(skill_match=..., ...)`
を作って`run_assignment(..., weights=...)`に渡す。

## Human Override

```python
from backend.pipeline.assignment.override import accept_recommendation, override_recommendation

final = accept_recommendation(result)                       # 推薦をそのまま採用
final = override_recommendation(result, "M-002", "経験を積ませたいため")  # 別のメンバーに変更
final = override_recommendation(result, None, "今回は見送り")            # 誰にも割り当てない
```

`FinalAssignment.ai_recommendation`には常に元のAI推薦がそのまま残るため、
「AIは何を推薦し、人間は最終的に何を決めたか」を常に区別して追跡できる。

## 既知の限界

- `day_unavailable`制約は、`AssignmentTask`が特定の日付を持たないため
  このフェーズでは判定できない（将来、スケジューリング機能を追加する際に
  対応する）。
- 前提タスクの未完了チェック(`_build_unmet_dependency_warnings`)は、
  呼び出し側が`completed_task_ids`を明示的に渡した場合のみ機能する
  （このフェーズはタスクの実施状況を追跡しない）。
