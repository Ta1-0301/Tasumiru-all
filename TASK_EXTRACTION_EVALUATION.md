# タスク抽出 評価フレームワーク

タスみるのタスク自動生成パイプライン（`backend/services/pipeline/`、
`backend/routers/tasks.py`から呼び出される本番コード）の品質を、
**どのLLMを使っても同じ基準で計測できる、モデル非依存の評価フレームワーク**
として実装した。**本番のタスク生成コードは一切変更していない。**

実装場所: `backend/evaluation/`（コード、詳細は[evaluation/README.md](backend/evaluation/README.md)）、
本ファイル（報告書）。

このドキュメントの§1〜§7がPhase 2（モデル非依存評価フレームワーク化）の内容、
Appendix AがPhase 1（初回の評価・パイプライン改善前の実測結果）の記録。

---

## 1. アーキテクチャ

```
Specification → LLM → Generated Tasks → Evaluation
```

- **Specification → LLM → Generated Tasks**: `backend/services/pipeline/runner.py`の
  `run_pipeline()`（本番コード、変更なし）がそのまま実行される。
- **Generated Tasks → Evaluation**: `backend/evaluation/`が担当。ルールベース指標・
  LLM-as-judge・人手評価の3種類のスコアを、同じ0-5ルーブリックの上でマージする。

比較対象モデル（現行のOllamaモデル・Meta Llama・将来のクラウドモデル等）は
`backend/evaluation/runners/model_registry.py`の`MODEL_REGISTRY`に登録するだけで
差し替えられ、`metrics/`・`evaluators/`のコードは一切変更する必要がない
（後述§5）。

---

## 2. 評価基準とルーブリック（0-5の6段階）

依頼された9つの基準すべてに、**0/1/2/3/4/5の明示的なルーブリック**を定義した
（`backend/evaluation/schemas/rubric.py`のRUBRICが正本）。

| 点数 | 意味 |
|---|---|
| 0 | unacceptable（不合格） |
| 1 | poor（不十分） |
| 2 | partially acceptable（部分的に許容できる） |
| 3 | acceptable（許容できる） |
| 4 | good（良好） |
| 5 | excellent（優秀） |

9基準は性質の異なる2グループに分けている（Phase 1から継続）。

### タスク単位の基準

| 基準 | 判定方法 | 実装 |
|---|---|---|
| Traceability（追跡可能性） | 出典(`source_reference`)が仕様書本文の実在箇所を指しているか、章/条項まで特定できるか | ルールベース |
| Specificity（具体性） | 曖昧でなく何をすべきかが具体的か | LLM-judge |
| Completeness（完結性） | そのタスク単体で着手できる情報が揃っているか | LLM-judge |
| Appropriate granularity（粒度） | 広すぎ/細かすぎず、複数タスクを束ねていないか | ルールベース |
| Actionability（行動可能性） | 明確な行動動詞を持ち着手可能か | ルールベース |
| Required skill accuracy（スキル推定の正確性） | `required_skills`がタスク内容と整合するか | ルールベース |
| Estimated effort plausibility（工数の妥当性） | `estimated_hours`が現実的で優先度と矛盾しないか | ルールベース |

### 文書単位の基準

| 基準 | 判定方法 | 実装 |
|---|---|---|
| Coverage（網羅性） | 正解タスク一覧をどれだけ拾えているか | LLM-judge（該当判定） + ルールベース（採点バンド） |
| Non-duplication（非重複性） | タスク間に重複がないか | ルールベース |

各基準の0-5すべての点数について「何を指すか」を`rubric.py`に文章で定義している
（例: traceabilityの5点="出典は実在し、章/条項の見出し（section）まで特定できている"）。
評価コードのコメントはこのルーブリックの番号と1対1で対応する。

`overall_score`は、タスク単位は7基準の**有効スコア**（後述§4）の平均、文書単位は
coverage/non_duplication/タスク平均スコアの3者平均（`schemas/models.py`の
`@computed_field`として実装、保存時に自動計算される）。

---

## 3. 出典トレーサビリティ（document_id / page / section / paragraph / source_text）

依頼された5フィールドを`SourceTraceability`（`schemas/models.py`）として構造化した。

| フィールド | 由来 | 備考 |
|---|---|---|
| `document_id` | 評価対象の仕様書ID | 常に値が入る |
| `page` | ページ番号 | **常に`None`**。プレーンテキスト仕様書にはページの概念が無いため、無い情報を捏造せず誠実に空欄にしている |
| `section` | チャンクの見出し（例: `第2条(納期)`） | `backend/services/pipeline/structure.py`の`decompose_document()`（本番の文書構造抽出、読み取り専用で呼び出す）が機械的に検出した見出し |
| `paragraph` | チャンクID (`chunk_id`) | 段落/チャンクの識別子 |
| `source_text` | 出典の原文抜粋 | 本番パイプラインの`SourceReference.excerpt`（LLMが自由記述したものではなく、`DocumentChunk`から機械的に転記された実在の部分文字列） |

**出典を絶対に捏造しない**という設計は本番パイプライン（`services/pipeline/schema.py`
の設計方針コメント参照）から引き継いでおり、評価フレームワーク側も
`source_excerpt not in spec_text`を検知したらtraceability 0点＋issue記録とする
（`metrics/rule_based.py::score_traceability`）。

---

## 4. LLM-as-judgeと人手評価の統合（LLM-judgeだけに依存しない）

`ScoreDetail`（`schemas/models.py`）が1つの基準につき
`rule_score` / `llm_score` / `human_score`を同時に保持し、
**人手評価 > LLM-judge > ルールベース** の優先順位で「今使う値」
（`effective_score`）を決定する。

人手評価の入力は`backend/evaluation/evaluators/human.py`が担当する。

```json
[
  {"document_id": "spec_a_simple", "task_id": "T-001",
   "criterion": "specificity", "score": 4, "rater": "yamada", "comment": "..."},
  {"document_id": "spec_a_simple", "task_id": null,
   "criterion": "coverage", "score": 3, "rater": "yamada"}
]
```

`load_human_scores()`で読み込み、`apply_human_scores()`で該当する
`ScoreDetail`に人手スコアをマージする（元のオブジェクトは変更しない）。
`task_id`が`null`の項目は文書単位の基準（coverage/non_duplication）への評価。

これにより、LLM-judgeの非決定性・自己評価バイアス（後述Appendix A §6）を
人間のレビューで訂正できる経路を用意した。

---

## 5. モデル非依存の実行（Model A / Model B / Model C）

`backend/evaluation/runners/model_registry.py`の`MODEL_REGISTRY`が
比較対象モデルの設定（`ModelConfig`: provider/model/model_version/temperature）
を保持する。例として3エントリを登録済み:

| キー | provider | model | 備考 |
|---|---|---|---|
| `model_a` | ollama | `llama3.1:8b` | 現行の本番採用モデル |
| `model_b` | ollama | `llama3.1:70b` | 比較用の例（要: 対応するOllamaサーバー） |
| `model_c` | anthropic | `claude-sonnet-5` | 比較用の例（要: `ANTHROPIC_API_KEY`） |

**`backend/evaluation/metrics/`・`backend/evaluation/evaluators/`はこれらの
provider/modelを一切分岐しない。** `run_pipeline()`（本番コード）・
`judge_task()`・`judge_coverage()`はすべて`BaseLLMClient.complete()`という
共通インターフェースだけを使う。新しいモデルを比較対象に加えたい場合、
`MODEL_REGISTRY`に1エントリ追加するだけでよい。

`backend/services/llm.py`の本番クライアント(`OllamaClient`)はモデル名が
`"llama3.1:8b"`にハードコードされており複数モデル比較には使えないため、
評価専用に`EvaluationOllamaClient`/`EvaluationAnthropicClient`
（`runners/llm_clients.py`）を追加した。**本番の`services/llm.py`は変更していない。**

生成モデルとLLM-judgeを同一モデルにすると自己評価バイアスが排除できない
（Appendix A §6の既知の限界）ため、既定では判定者モデル(`DEFAULT_JUDGE_MODEL_KEY`)
を評価対象モデルと分けて実行する（`--judge-model`で明示指定も可能）。

---

## 6. 再現性（Reproducibility）

`ReproducibilityRecord`（`schemas/models.py`）が1回の評価実行につき
以下を記録する:

| フィールド | 内容 |
|---|---|
| `model` | 使用したモデル名 |
| `model_version` | モデルバージョン（`ModelConfig.model_version`） |
| `prompt_version` | **本番の抽出プロンプト文面（`stages.py`の`_REQUIREMENT_PROMPT`+`_CANDIDATE_TASK_PROMPT`）から計算したSHA-256フィンガープリント（先頭12桁）**。プロンプトが1文字変わればこの値も変わるため、後から「どのプロンプトで生成したか」を一意に確認できる。本番プロンプトへの変更は一切不要（読み取り専用でハッシュ化するだけ） |
| `temperature` | `ModelConfig.temperature` |
| `timestamp` | 実行時刻（UTC） |
| `input_document_id` / `input_document_text` | 入力文書そのもの |
| `generated_result` | パイプラインが生成した生タスク一覧 |
| `evaluation_result` | `DocumentEvaluation`（本ドキュメント§2-4の全評価結果） |

`backend/evaluation/runners/run_evaluation.py`を実行すると、
`backend/evaluation/reports/results/`に`ReproducibilityRecord`のJSON配列として
保存される。複数モデルの結果を`backend/evaluation/reports/build_report.py`に
渡すと、モデルごとの平均スコアを横並びにしたMarkdownレポートが生成される。

---

## 7. Phase 2で実施したこと・実施していないこと

### 実施したこと

- 評価コードを`backend/evaluation/{schemas,datasets,metrics,evaluators,runners,reports}/`
  という単一責務のパッケージに再構成した（旧: フラットな`backend/evaluation/*.py`）
- 採点スケールを0-2から0-5に拡張し、9基準すべてに明示的なルーブリックを定義した
- 出典を`document_id`/`page`/`section`/`paragraph`/`source_text`の構造にした
  （`page`は仕様書に存在しない情報のため誠実に`None`のまま）
- 人手評価の読み込み・マージ機構(`evaluators/human.py`)を追加した
- モデル非依存の実行機構（`ModelConfig`レジストリ、評価専用クライアント、
  再現性フィンガープリント）を追加した
- ルールベース指標41件+schemas/human/registry/report関連26件、
  計67件の新規単体テスト（既存と合わせて`backend/tests/`全89件がPASS）

### 実施していないこと（正直な申告）

- **このフェーズ用の新規LLM実行は行っていない**。開発環境にOllamaサーバーが
  起動しておらず（`http://localhost:11434`は接続拒否）、実データでの評価実行は
  できなかった。**フェーズ2の成果として捏造した実行結果は一切無い。**
  ルールベース指標・スキーマ・人手評価マージ・モデルレジストリ・
  再現性フィンガープリント・レポート生成のロジックはすべて単体テストで検証済み
  （LLM呼び出しを含まない決定的な部分）。
- 本番のタスク生成コード（`backend/services/pipeline/`,
  `backend/routers/tasks.py`, `backend/services/llm.py`）は一切変更していない。
- Model B (`llama3.1:70b`) / Model C (`claude-sonnet-5`) は`MODEL_REGISTRY`への
  登録例であり、実際にこの環境で実行して比較した結果ではない
  （対応するサーバー/APIキーが無いため）。

### 次にやるべきこと

1. Ollamaサーバーが起動できる環境で`python -m backend.evaluation.runners.run_evaluation --model model_a`
   を実行し、新しいスキーマでの実測ベースラインを取得する
2. 同じデータセット・同じ評価コードで`--model model_b`等を実行し、
   `build_report.py`でモデル間比較レポートを生成する
3. 実測結果に対して人手評価ファイルを作成し、LLM-judgeとの一致率を確認する

---

# Appendix A: Phase 1の実測結果（履歴・旧0-2スケール）

以下はPhase 1（新パイプライン`backend/services/pipeline/`導入**前**）に、
当時の単発LLM呼び出し実装（`backend/services/llm.py`の
`TASK_DECOMPOSITION_PROMPT`＋`backend/routers/tasks.py`の正規化ロジック）を
対象に実施した評価の記録。**この節の内容は当時のまま変更していない**
（採点スケールは旧0-2のまま。現在の0-5ルーブリックとは対応しない）。
ここで見つかった問題（特にAppendix A §5.1・5.2）が、現行の
`backend/services/pipeline/`への書き換えの動機になった。生ログは
`backend/evaluation/reports/results/legacy/evaluation_20260818T070647Z.json`
に保存されている。

## A.1 評価データセット（手動ラベル付け、2件）

既存の「テスト用仕様書」ファイルはリポジトリに存在しなかった（過去の統合テストで
その場限りのテキストを使っていただけ）ため、実際のプロコン提出書類を模した
仕様書テキストを2件、新規に手動作成し、正解タスク一覧を人手で付与した
（現在は`backend/evaluation/datasets/specs.py`）。

| ID | 内容 | 正解タスク数 |
|---|---|---|
| `spec_a_simple` | 短文・シンプルな仕様書 | 2 |
| `spec_b_multi_pattern` | 明示的指示・締切・条件付き要件・禁止事項が混在する実践的な仕様書 | 5 |

正解タスクの`source_excerpt`は**仕様書本文からの実在の抜粋**であり、
`EvaluationSpec`の`model_validator`で「本文に実在するか」を機械的に検証している
（存在しなければ`ValueError`でデータセットのロード自体が失敗する = 正解データの
捏造を構造的に防止）。実行して確認済み:

```
spec_a_simple 2 tasks - excerpts verified OK
spec_b_multi_pattern 5 tasks - excerpts verified OK
```

## A.2 評価手法

当時の`run_evaluation.py`が以下を行った:

1. **本番コードをそのまま呼ぶ**: `backend.services.llm.get_llm_client()`
   （変更なし）で実際にOllama(`llama3.1:8b`)を呼び出し、生のタスク一覧を取得する
2. **本番と同じ正規化を複製**: `backend/routers/tasks.py`の`generate_tasks()`内に
   あるガードレール（`title`/`skill_required`/`priority`/`source_section`の
   フォールバック処理）を評価用に複製する（本番コードはimportせず変更もしない）
3. 各タスクに5つのルールベース指標 + 2つのLLM-judge指標を適用
4. 文書全体にNon-duplication（ルールベース）+ Coverage（LLM-judge）を適用
5. 各仕様書につき**3回**生成を試行し、統計的なばらつきを見た

## A.3 実行結果（実測値。捏造なし）

2仕様書 × 3回 = **合計6回**、実際にOllamaを呼び出して評価した。

### A.3.1 最初に判明した支配的な問題

**6回中6回（100%）、LLMの生出力がJSON配列ではなく単一のJSONオブジェクトだった。**

```
=== フォーマット統計 ===
  dict: 6/6 回
```

`backend/routers/tasks.py`のガードレール（`for i, t in enumerate(raw_tasks)`）は
`raw_tasks`が`dict`の場合、**そのキー名を1件ずつタスクとして扱ってしまう**。
結果として、生成される「タスク」は毎回ほぼ以下の3つになった:

```json
[{"title": "name"}, {"title": "skill_required"}, {"title": "priority"}]
```

これは当時の本番プロンプト(`TASK_DECOMPOSITION_PROMPT`)の出力例が
`[{{"name": ..., "skill_required": ..., "priority": ...}}, {{...}}]`という
配列だが、`llama3.1:8b`の`format: "json"`モードが**単一オブジェクトに
収束してしまう**ことが原因と推測される（当時は原因の深掘り・修正はしなかった）。

### A.3.2 集計スコア（全6回・全18生成タスク分。旧0-2スケール）

| 基準 | 平均 | 0点の割合 |
|---|---|---|
| traceability_score | **0.00** | 18/18 (100%) |
| actionability_score | **0.00** | 18/18 (100%) |
| skill_accuracy_score | **0.00** | 18/18 (100%) |
| granularity_score | 2.00 | 0/18 |
| effort_plausibility_score | 1.00 | 0/18 |
| specificity_score (judge) | 1.33 | 1/18 |
| completeness_score (judge) | 1.17 | 5/18 |

| 文書単位の基準 | 6回の値 | 平均 |
|---|---|---|
| coverage_score | [1, 0, 0, 1, 0, 1] | 0.50 |
| non_duplication_score | [2, 2, 2, 2, 2, 2] | 2.00 |
| 文書overall_score | [1.25, 0.89, 0.94, 1.29, 0.98, 1.22] | 1.10（0-2満点中） |

### A.3.3 実例（1回分の生データ）

```json
{
  "document_id": "spec_a_simple",
  "generated_task_count": 3,
  "coverage_score": 1,
  "task_evaluations": [
    {
      "task_id": "T-001", "title": "name",
      "traceability_score": 0, "actionability_score": 0, "skill_accuracy_score": 0,
      "issues": [
        "source_sectionが汎用フォールバック値 '§ 自動生成' のまま（実際の出典箇所を示していない）",
        "行動を表す動詞が見当たらない（名詞句だけになっている可能性）",
        "skill_requiredが汎用フォールバック値 'Python FastAPI' のままで、タスク内容と対応しているか確認できない"
      ]
    }
  ],
  "issues": ["未カバーの正解タスク: ['a1']"]
}
```

## A.4 発見された弱点（重要度順）

### A.4.1 【最重要・再現率100%】LLM出力がJSON配列ではなく単一オブジェクトになる

上記A.3.1の通り。**これが起きている限り、タスク生成機能は実質的に機能していなかった**
（意味のあるタスクが1つも生成されない）。

### A.4.2 【構造的・100%】Traceabilityが常にゼロ

当時の`TASK_DECOMPOSITION_PROMPT`（`backend/services/llm.py`）は`name` /
`skill_required` / `priority`のみをLLMに要求しており、`source_section`や
ページ番号・段落番号・原文抜粋を一切要求していなかった。これが現行の
`backend/services/pipeline/`（`SourceReference`をLLMの自由記述ではなく
`DocumentChunk`から機械的に転記する設計）に置き換える直接の動機になった。

### A.4.3 【構造的】Skill accuracyが検証されていない

`skill_required`が空・欠損の場合、当時の`routers/tasks.py`は無条件に
`"Python FastAPI"`を代入していた。LLMが実際に推定したスキルなのか、単なる
デフォルト値なのかを区別する仕組みが無かった。

### A.4.4 【評価フレームワーク自身の限界】LLM-judgeが甘い

`title: "name"`という明らかに無意味なタスクに対しても、judgeは
`specificity_score: 1`や`completeness_score: 2`を付けることがあった。

### A.4.5 【評価フレームワーク自身の限界】Granularityヒューリスティックの誤検知

`"name"`のような1単語タイトルは、動詞の重複や接続詞が無いため
`granularity_score: 2`（良好）になってしまっていた。

### A.4.6 Coverageは平均0.5（6回中4回が0点）

上記A.4.1のバグの影響が大きく、当時この数値を「意味理解能力の低さ」として
解釈するのは早計だった。

## A.5 このフレームワーク自体の限界（正直な申告）

- **LLM-judgeは非決定的**: 同じ入力でも実行のたびにスコアが変わりうる。
  当時は`llama3.1:8b`を判定にも使っており、判定者と生成者が同じモデルである
  ことのバイアス（自分の出力を甘く評価する可能性）は排除できていなかった
  （Phase 2の§5で判定者モデルを分離することで軽減を試みている）。
- **データセットが小さい**: 意図的に2件（正解タスク計7件）に留めた。
- **ルールベース指標は日本語の簡易ヒューリスティック**: 動詞リスト・
  スキルカテゴリ辞書は網羅的ではない。
- **A.4.1のバグにより、本来測りたかった「良い生成における品質」は
  一度も観測できていなかった**（6回とも同じ失敗モードだったため）。
