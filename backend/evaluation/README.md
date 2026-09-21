# backend/evaluation/

タスみるのタスク抽出パイプライン（`backend/services/pipeline/`）を
**モデルに依存せず**評価するためのフレームワーク。詳しい設計背景・ルーブリック・
実測結果は[../../TASK_EXTRACTION_EVALUATION.md](../../TASK_EXTRACTION_EVALUATION.md)を参照。

**このパッケージは本番のタスク生成コードを一切変更しない。**
`backend/services/pipeline/runner.py`の`run_pipeline()`を読み取り専用で
呼び出すだけ。

## ディレクトリ構成

```
backend/evaluation/
    schemas/     評価結果のデータ構造（Score/ScoreDetail/TaskEvaluation/
                 DocumentEvaluation/ModelConfig/ReproducibilityRecord等）と、
                 9基準×0-5段階の採点ルーブリック定義（rubric.py）
    datasets/    手動ラベル付けされた評価用仕様書（正解タスク付き）
    metrics/     決定的なルールベース採点関数（LLM不使用）
    evaluators/  LLM-as-judge（specificity/completeness/coverageの判定材料）
                 と、人手評価の読み込み・マージ
    runners/     評価対象/判定者モデルのレジストリ、評価専用LLMクライアント、
                 実行オーケストレーター（CLI）
    reports/     実行結果の保存先(results/)、モデル間比較レポート生成
```

## 実行方法

```bash
source .venv/bin/activate
export OLLAMA_BASE_URL=http://localhost:11434   # 使うproviderに応じて必要な環境変数

# model_a（既定: llama3.1:8b）で評価を実行
python -m backend.evaluation.runners.run_evaluation --model model_a

# 各仕様書を3回ずつ試行して統計的なばらつきを見る
python -m backend.evaluation.runners.run_evaluation --model model_a --repeats 3

# 判定者(judge)モデルを評価対象と分ける（既定でも分離されている。明示する場合）
python -m backend.evaluation.runners.run_evaluation --model model_a --judge-model model_a
```

結果は`backend/evaluation/reports/results/<model>_<timestamp>.json`
（`ReproducibilityRecord`のJSON配列）として保存される。

複数モデルの結果を比較レポートにまとめる:

```bash
python -m backend.evaluation.reports.build_report backend/evaluation/reports/results/*.json --out summary.md
```

## 新しい比較対象モデルを追加する

`backend/evaluation/runners/model_registry.py`の`MODEL_REGISTRY`に1エントリ
追加するだけでよい。`metrics/`・`evaluators/`側のコード変更は不要
（モデル固有の分岐を持たないことがこのフレームワークの要件）。

```python
MODEL_REGISTRY["model_d"] = ModelConfig(
    key="model_d", provider="ollama", model="mistral:7b", temperature=0.0,
)
```

`provider`は`"ollama"`または`"anthropic"`に対応（`runners/llm_clients.py`）。
別のproviderを追加する場合は`BaseLLMClient`を実装したクライアントを
`runners/llm_clients.py`に追加し、`ModelConfig.build_client()`に分岐を1行足す。

## 人手評価を追加する

LLM-as-judgeの結果だけに依存しないため、人手評価を後から上書きできる。

1. 評価したい`document_id`/`task_id`/`criterion`（9基準のキー）を指定して
   スコア(0-5)を書いたJSON配列ファイルを作る（例は
   `backend/evaluation/evaluators/human.py`のdocstring参照）。
2. `backend.evaluation.evaluators.human.load_human_scores()` で読み込み、
   `apply_human_scores(document_evaluation, entries)`でマージする。
3. 人手評価が入力された基準は、`ScoreDetail.effective_score`で常に
   最優先で採用される。

## テスト

```bash
python -m pytest backend/tests/test_evaluation_metrics.py backend/tests/test_evaluation_schemas.py \
    backend/tests/test_evaluation_registry.py backend/tests/test_evaluation_report.py -q
```

LLM呼び出しを含む`runners/run_evaluation.py`本体はネットワーク依存のため
単体テスト対象外。ルールベース指標・スキーマのマージロジック・
モデルレジストリ・レポート生成はすべて決定的な単体テストで検証している。

## 既知の限界

- LLM-as-judge（specificity/completeness/coverageの該当判定）は非決定的。
  同じ入力でも実行のたびにスコアがぶれる可能性がある。
- `backend/evaluation/reports/results/legacy/`には、旧0-2スケール・
  旧フラット構成時代（Phase 1）の実測結果が履歴として残っている。
  現在のスキーマとは互換性が無い。
