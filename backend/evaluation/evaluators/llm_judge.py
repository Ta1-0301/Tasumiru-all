# backend/evaluation/evaluators/llm_judge.py
"""
LLM-as-judgeによる評価（specificity / completeness / coverageの判定材料）。

これらは「意味を理解した上での判断」が必要で、単純な文字列一致では
測れないためLLMに判定させる。ただし本番のタスク生成プロンプト
(backend/services/pipeline/stages.py)とは完全に独立した、評価専用の
プロンプトを使う（本番の挙動には一切影響しない）。

モデル非依存: この評価器は `backend.services.llm.BaseLLMClient` のインターフェース
だけに依存し、渡されたクライアントがOllamaかAnthropicか等を一切分岐しない。
どのモデルを判定者(judge)として使うかは呼び出し側
(backend/evaluation/runners/run_evaluation.py)が選ぶ。

NOTE: LLMの判定結果は実行するたびに多少ぶれうる（決定的ではない）。
      これはmetrics/rule_based.pyとの明確な違いであり、
      TASK_EXTRACTION_EVALUATION.md にもその旨を明記している。
      この非決定性への対策として「LLM-as-judgeだけに依存しない」ため、
      evaluators/human.py による人手評価の上書きを許容している。

coverageについては、どのタスクがカバーされているかの判定はLLMに委ねるが、
それを何点にするか（0-5のバンド）はLLMには決めさせず、
`metrics.rule_based.score_coverage_band` が決定的に計算する
（採点自体の再現性を保つため）。
"""

from __future__ import annotations

import json
from typing import Any, Dict, List

from backend.evaluation.datasets.specs import GroundTruthTask
from backend.evaluation.schemas.rubric import render_bands
from backend.services.llm import BaseLLMClient
from backend.services.pipeline.llm_json import call_llm_json

_VALID_SCORES = set(range(6))

_TASK_JUDGE_PROMPT = """\
あなたはプロジェクト管理の専門家として、以下の1件のタスク記述の品質を評価します。
仕様書の原文も参考に、次の2つの観点を0〜5の6段階で採点してください。

## specificity（具体性）の採点基準
{specificity_bands}

## completeness（完結性）の採点基準
{completeness_bands}

出力は必ず以下のJSON形式のみ。説明文やMarkdownは一切不要です。

{{"specificity_score": 0, "completeness_score": 0, "issues": ["短い理由"]}}

## 仕様書の原文
{spec_text}

## 評価対象のタスク
タイトル: {title}
説明: {description}
必要スキル: {required_skills}
優先度: {priority}
見積り工数: {estimated_hours}
完了条件: {acceptance_criteria}
"""

_COVERAGE_JUDGE_PROMPT = """\
あなたはプロジェクト管理の専門家です。以下の仕様書から本来抽出されるべき
「正解タスク一覧」と、実際にAIが生成した「生成タスク一覧」を比較してください。
表現が違っても意味的に対応していればカバーされているとみなします。

点数はあなたが付けるのではなく、正解タスクIDのうち「どれが生成タスク一覧で
カバーされているか」「どれがカバーされていないか」だけを判定してください
（スコアへの変換は呼び出し側が機械的に行います）。

出力は必ず以下のJSON形式のみ。

{{"covered_ground_truth_ids": [], "missed_ground_truth_ids": [], "issues": ["短い理由"]}}

## 仕様書の原文
{spec_text}

## 正解タスク一覧
{ground_truth_json}

## 生成タスク一覧
{generated_json}
"""


class JudgeError(Exception):
    """LLM judgeの呼び出し・パースに失敗した場合。捏造を避けるため、失敗を握りつぶさず送出する。"""


async def judge_task(client: BaseLLMClient, spec_text: str, task: Dict[str, Any]) -> Dict[str, Any]:
    """1件のタスクについて specificity / completeness を判定する（0-5）"""
    prompt = _TASK_JUDGE_PROMPT.format(
        specificity_bands=render_bands("specificity"),
        completeness_bands=render_bands("completeness"),
        spec_text=spec_text,
        title=task.get("title", ""),
        description=task.get("description") or "(なし)",
        required_skills=", ".join(task.get("required_skills") or []) or "(なし)",
        priority=task.get("priority", ""),
        estimated_hours=task.get("estimated_hours"),
        acceptance_criteria=", ".join(task.get("acceptance_criteria") or []) or "(なし)",
    )
    result, error = await call_llm_json(client, prompt)
    if result is None:
        raise JudgeError(error or "judgeの呼び出しに失敗しました")

    for key in ("specificity_score", "completeness_score"):
        if key not in result or result[key] not in _VALID_SCORES:
            raise JudgeError(f"judge出力に妥当な{key}(0-5)が含まれていません: {result}")

    return result


async def judge_coverage(
    client: BaseLLMClient,
    spec_text: str,
    ground_truth_tasks: List[GroundTruthTask],
    generated_tasks: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """正解タスク一覧のうちどれが生成タスク一覧でカバーされているかを判定する"""
    ground_truth_json = json.dumps(
        [{"id": t.id, "description": t.description} for t in ground_truth_tasks],
        ensure_ascii=False,
    )
    generated_json = json.dumps(
        [{"title": t.get("title", ""), "description": t.get("description")} for t in generated_tasks],
        ensure_ascii=False,
    )
    prompt = _COVERAGE_JUDGE_PROMPT.format(
        spec_text=spec_text,
        ground_truth_json=ground_truth_json,
        generated_json=generated_json,
    )
    result, error = await call_llm_json(client, prompt)
    if result is None:
        raise JudgeError(error or "judgeの呼び出しに失敗しました")

    covered = result.get("covered_ground_truth_ids")
    if not isinstance(covered, list):
        raise JudgeError(f"judge出力にcovered_ground_truth_idsが含まれていません: {result}")

    # 存在しない正解タスクIDの自己申告は無視する（judgeによる捏造の混入防止）
    valid_ids = {t.id for t in ground_truth_tasks}
    covered = [c for c in covered if c in valid_ids]
    missed = [t.id for t in ground_truth_tasks if t.id not in covered]

    return {
        "covered_ground_truth_ids": covered,
        "missed_ground_truth_ids": missed,
        "issues": result.get("issues", []),
    }
