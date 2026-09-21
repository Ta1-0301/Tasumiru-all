# backend/evaluation/runners/run_evaluation.py
"""
評価フレームワークの実行スクリプト（モデル非依存）。

Specification → LLM → Generated Tasks → Evaluation のパイプラインを、
本番コード(backend.services.pipeline.runner.run_pipeline)をそのまま
（一切変更せず）呼び出して実行し、rule_metrics + llm_judgeを適用する。

使い方:
    source .venv/bin/activate
    export OLLAMA_BASE_URL=http://localhost:11434
    python -m backend.evaluation.runners.run_evaluation --model model_a
    python -m backend.evaluation.runners.run_evaluation --model model_a --repeats 3

結果は backend/evaluation/reports/results/ にJSON
（`ReproducibilityRecord`のリスト）として保存される。
LLM呼び出しを含むため、実行には数分かかる。

Model A / Model B / Model C を比較する場合は --model を切り替えて複数回実行し、
`backend/evaluation/reports/build_report.py` で結果を横並びにまとめる。
"""

from __future__ import annotations

import argparse
import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import List

from backend.evaluation.datasets.specs import EVALUATION_DATASET, EvaluationSpec
from backend.evaluation.evaluators.llm_judge import JudgeError, judge_coverage, judge_task
from backend.evaluation.metrics.rule_based import (
    score_actionability,
    score_coverage_band,
    score_effort_plausibility,
    score_granularity,
    score_non_duplication,
    score_skill_accuracy,
    score_traceability,
)
from backend.evaluation.runners.model_registry import (
    DEFAULT_JUDGE_MODEL_KEY,
    MODEL_REGISTRY,
    compute_prompt_version,
)
from backend.evaluation.schemas.models import (
    DocumentEvaluation,
    ReproducibilityRecord,
    ScoreDetail,
    SourceTraceability,
    TaskEvaluation,
)
from backend.services.pipeline.runner import run_pipeline
from backend.services.pipeline.structure import decompose_document

REPORTS_DIR = Path(__file__).resolve().parent.parent / "reports" / "results"


async def evaluate_spec(spec: EvaluationSpec, model_key: str, judge_model_key: str) -> ReproducibilityRecord:
    model_config = MODEL_REGISTRY[model_key]
    judge_config = MODEL_REGISTRY[judge_model_key]

    client = model_config.build_client()
    judge_client = client if judge_model_key == model_key else judge_config.build_client()

    # 文書構造抽出は本番と同じ関数を読み取り専用で呼び、chunk_id→見出しの対応を得る
    # （traceabilityのsection/paragraphを機械的に埋めるためだけに使う。本番の挙動は変えない）
    chunk_heading_by_id = {c.chunk_id: c.heading for c in decompose_document(spec.text)}

    pipeline_result = await run_pipeline(spec.text, client)  # 本番パイプライン。変更しない。
    generated_tasks = [t.model_dump(mode="json") for t in pipeline_result.tasks]

    task_evaluations: List[TaskEvaluation] = []

    for task_dict, pt in zip(generated_tasks, pipeline_result.tasks):
        issues: List[str] = []

        source_excerpt = pt.source_reference.excerpt if pt.source_reference else None
        chunk_id = pt.source_reference.chunk_id if pt.source_reference else None
        heading = chunk_heading_by_id.get(chunk_id) if chunk_id else None

        traceability_score, i1 = score_traceability(source_excerpt, pt.needs_review, spec.text, heading)
        granularity_score, i2 = score_granularity(pt.title, pt.acceptance_criteria)
        actionability_score, i3 = score_actionability(pt.title, pt.description)
        skill_accuracy_score, i4 = score_skill_accuracy(pt.title, pt.required_skills)
        effort_score, i5 = score_effort_plausibility(pt.estimated_hours, pt.priority.value)
        issues += i1 + i2 + i3 + i4 + i5

        specificity_score = None
        completeness_score = None
        try:
            judge_result = await judge_task(judge_client, spec.text, task_dict)
            specificity_score = judge_result["specificity_score"]
            completeness_score = judge_result["completeness_score"]
            issues += judge_result.get("issues", [])
        except JudgeError as e:
            # 捏造しない: judgeが失敗したら未評価(None)のままにし、失敗自体を記録する
            issues.append(f"LLM judge呼び出し失敗のため未評価: {e}")

        source = SourceTraceability(
            document_id=spec.id,
            page=None,  # プレーンテキスト仕様書にページの概念が無いため常にNone（捏造しない）
            section=heading,
            paragraph=chunk_id,
            source_text=source_excerpt,
        )

        task_evaluations.append(TaskEvaluation(
            task_id=pt.task_id,
            title=pt.title,
            source=source,
            scores={
                "traceability": ScoreDetail(rule_score=traceability_score),
                "granularity": ScoreDetail(rule_score=granularity_score),
                "actionability": ScoreDetail(rule_score=actionability_score),
                "skill_accuracy": ScoreDetail(rule_score=skill_accuracy_score),
                "effort_plausibility": ScoreDetail(rule_score=effort_score),
                "specificity": ScoreDetail(llm_score=specificity_score),
                "completeness": ScoreDetail(llm_score=completeness_score),
            },
            issues=issues,
        ))

    doc_issues: List[str] = []
    non_dup_score, non_dup_issues = score_non_duplication(generated_tasks)
    doc_issues += non_dup_issues
    if pipeline_result.dropped_duplicates:
        doc_issues.append(f"パイプライン内で除外された重複: {pipeline_result.dropped_duplicates}")
    if pipeline_result.failed_items:
        doc_issues.append(f"検証に失敗し破棄された項目数: {len(pipeline_result.failed_items)}")

    coverage_score = None
    try:
        coverage_result = await judge_coverage(judge_client, spec.text, spec.ground_truth_tasks, generated_tasks)
        coverage_score, coverage_issues = score_coverage_band(
            len(coverage_result["covered_ground_truth_ids"]), len(spec.ground_truth_tasks)
        )
        doc_issues += coverage_issues + coverage_result.get("issues", [])
        if coverage_result.get("missed_ground_truth_ids"):
            doc_issues.append(f"未カバーの正解タスク: {coverage_result['missed_ground_truth_ids']}")
    except JudgeError as e:
        doc_issues.append(f"LLM judge(coverage)呼び出し失敗のため未評価: {e}")

    document_evaluation = DocumentEvaluation(
        document_id=spec.id,
        generated_task_count=len(generated_tasks),
        ground_truth_task_count=len(spec.ground_truth_tasks),
        scores={
            "coverage": ScoreDetail(llm_score=coverage_score),
            "non_duplication": ScoreDetail(rule_score=non_dup_score),
        },
        task_evaluations=task_evaluations,
        issues=doc_issues,
    )

    return ReproducibilityRecord(
        model=model_config.model,
        model_version=model_config.model_version,
        prompt_version=compute_prompt_version(),
        temperature=model_config.temperature,
        timestamp=datetime.now(timezone.utc),
        input_document_id=spec.id,
        input_document_text=spec.text,
        generated_result=generated_tasks,
        evaluation_result=document_evaluation,
    )


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="タスク抽出パイプラインの評価を実行する（モデル非依存）")
    parser.add_argument(
        "--model", default="model_a", choices=sorted(MODEL_REGISTRY),
        help="評価対象モデル（切り替えても評価ロジックは一切変わらない）",
    )
    parser.add_argument(
        "--judge-model", default=DEFAULT_JUDGE_MODEL_KEY, choices=sorted(MODEL_REGISTRY),
        help="LLM-as-judgeとして使うモデル（既定では評価対象モデルと分け、自己評価バイアスを軽減する）",
    )
    parser.add_argument("--repeats", type=int, default=1, help="各仕様書ごとの試行回数")
    return parser.parse_args()


async def main() -> None:
    args = _parse_args()
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    records: List[ReproducibilityRecord] = []

    for spec in EVALUATION_DATASET:
        for attempt in range(1, args.repeats + 1):
            print(f"=== 評価中: model={args.model} spec={spec.id} (試行 {attempt}/{args.repeats}) ===")
            record = await evaluate_spec(spec, args.model, args.judge_model)
            records.append(record)
            print(f"overall_score={record.evaluation_result.overall_score}  "
                  f"task_count={record.evaluation_result.generated_task_count}")
            print()

    out_path = REPORTS_DIR / f"{args.model}_{timestamp}.json"
    out_path.write_text(
        json.dumps([r.model_dump(mode="json") for r in records], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"結果を保存しました: {out_path}")


if __name__ == "__main__":
    asyncio.run(main())
