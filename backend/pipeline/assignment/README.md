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
| `deadline.py` | 割当済み工数の台帳(`AssignmentLedger`)、期限までの稼働可能時間の計算、累積負荷100%超過(`check_cumulative_workload`)・期限内に完了できない候補(`check_deadline`)の除外 |
| `workload_balancing.py` | 推薦者の選択。台帳がある場合は、100%以内の候補から負荷が均一になる候補を選ぶ |
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

## 負荷率100%以内・負荷の均一化

JobManagerはタスクを1件ずつ逐次割り当て、割り当てた工数を`AssignmentLedger`に記録する。

- 負荷率 = (既存業務 + 割当済み + このタスク) / 稼働可能時間。稼働可能時間は、納期情報が
  無ければ1週間（`available_hours_per_week`）、あれば計画期間（下記）。Validation(CHECK 4)と同じ定義。
- 割当後に100%を超える候補はハード制約として除外する（未割当理由は既存の`WORKLOAD_TOO_HIGH`）。
- 残った候補の選び方（`workload_balancing._select_balanced_candidate`）:
  1. 割当後80%以下の候補がいればその中から（既存の閾値ロジックと同じ考え方）
  2. スキル一致度(skill_match)が最良から1レベル(0.2)以内の候補を「同等」とみなし
  3. その中で割当後の負荷率が最も低い候補を選ぶ（同率ならスコア順）
- 必要スキルを持つ人がいるのに負荷・納期で埋まっている場合は、別スキルの人へのFallbackを行わない。
- 注意: 納期が無い場合の上限は「1週間分」なので、1週間で終わらない量のタスクは未割当になる。
  プロジェクト全体を割り当てる場合は納期を設定する。

## 納期考慮（任意）

プロジェクトの納期(`ProjectModel.due_date`)またはタスク個別の`Task.due_date`が
1つでもある場合だけ有効になる。どちらも無ければ従来と完全に同じ挙動。

- 期限までの稼働可能時間 = 週あたり稼働可能時間 / 週の稼働日数 × 基準日〜期限の稼働日数
  （両端を含む。基準日は`ProjectModel.start_date`、未設定ならジョブ実行日）。
  Assignmentの判定では`current_assigned_hours`を差し引き、`max_hours_per_week`で頭打ちにする。
- JobManagerは期限の早い順に逐次割り当て、割り当てた工数を`AssignmentLedger`に記録する。
  「各期限dまでの累積工数 <= 期限dまでの稼働可能時間」を満たせない候補はハード制約として
  除外され（`DEADLINE_INFEASIBLE`）、Fallback候補にもならない。既存の4チェックは変更しない。
- Validation(CHECK 4)は分子（割当タスクの見積り合計）を変えず、分母を計画期間
  （基準日〜最も遅い期限）の稼働可能時間にする（`WorkloadSummary.basis="period"`）。
  計画期間の終わりより前の期限で累積超過があれば`DEADLINE_OVERLOAD`を警告する。

## 既知の限界

- `day_unavailable`制約は、`AssignmentTask`が特定の日付を持たないため
  このフェーズでは判定できない（将来、スケジューリング機能を追加する際に
  対応する）。
- 前提タスクの未完了チェック(`_build_unmet_dependency_warnings`)は、
  呼び出し側が`completed_task_ids`を明示的に渡した場合のみ機能する
  （このフェーズはタスクの実施状況を追跡しない）。
