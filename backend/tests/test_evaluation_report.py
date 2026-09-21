# backend/tests/test_evaluation_report.py
"""
backend/evaluation/reports/build_report.py の単体テスト。

NOTE: ここで使うレコードはコードパスを検証するためのテスト用フィクスチャであり、
      実際のLLM実行結果ではない（本物の評価結果として報告・保存はしない）。
"""

from datetime import datetime, timezone

from backend.evaluation.reports.build_report import build_markdown_report
from backend.evaluation.schemas.models import (
    DocumentEvaluation,
    ReproducibilityRecord,
    ScoreDetail,
    SourceTraceability,
    TaskEvaluation,
)


def _make_record(model: str, coverage: int, traceability: int) -> dict:
    task = TaskEvaluation(
        task_id="T-001",
        title="テストタスク",
        source=SourceTraceability(document_id="doc_1"),
        scores={"traceability": ScoreDetail(rule_score=traceability)},
    )
    doc = DocumentEvaluation(
        document_id="doc_1",
        generated_task_count=1,
        ground_truth_task_count=1,
        scores={"coverage": ScoreDetail(llm_score=coverage), "non_duplication": ScoreDetail(rule_score=5)},
        task_evaluations=[task],
    )
    record = ReproducibilityRecord(
        model=model,
        model_version=model,
        prompt_version="testfingerprint",
        temperature=0.0,
        timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
        input_document_id="doc_1",
        input_document_text="テスト仕様書",
        generated_result=[{"title": "テストタスク"}],
        evaluation_result=doc,
    )
    return record.model_dump(mode="json")


def test_build_markdown_report_groups_by_model():
    records = [_make_record("model_a", coverage=5, traceability=4), _make_record("model_b", coverage=2, traceability=1)]
    report = build_markdown_report(records)

    assert "model_a" in report
    assert "model_b" in report
    assert "coverage" in report


def test_build_markdown_report_handles_empty_input():
    report = build_markdown_report([])
    assert "対象モデル数: 0" in report
