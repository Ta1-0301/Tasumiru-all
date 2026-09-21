# backend/evaluation/reports/build_report.py
"""
複数の実行結果(reports/results/*.json、`ReproducibilityRecord`のリスト)を読み込み、
モデル間比較・文書単位/タスク単位の集計結果をMarkdownレポートとして生成する。

Model A / Model B / Model C を横並びで比較できるようにすることが目的。
このモジュール自身は各モデルの生成ロジックを一切知らず、
`ReproducibilityRecord.model` フィールドでグルーピングするだけ
（モデル固有の分岐を一切持たない）。

スコアは `ScoreDetail.effective_score`（人手 > LLM-judge > ルールベース）を
採用するため、人手評価が入力されていればレポートにも自動的に反映される。

使い方:
    python -m backend.evaluation.reports.build_report backend/evaluation/reports/results/*.json
    python -m backend.evaluation.reports.build_report backend/evaluation/reports/results/*.json --out summary.md
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
from statistics import mean
from typing import Any, Dict, List

CRITERIA_ORDER = [
    "coverage", "traceability", "specificity", "completeness", "granularity",
    "actionability", "skill_accuracy", "effort_plausibility", "non_duplication",
]


def load_records(paths: List[Path]) -> List[Dict[str, Any]]:
    records: List[Dict[str, Any]] = []
    for path in paths:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        records.extend(data if isinstance(data, list) else [data])
    return records


def _effective(score_detail: Dict[str, Any]) -> Any:
    return score_detail.get("effective_score")


def _criterion_values(records: List[Dict[str, Any]], criterion: str) -> List[float]:
    values: List[float] = []
    for r in records:
        doc = r["evaluation_result"]
        if criterion in doc.get("scores", {}):
            v = _effective(doc["scores"][criterion])
            if v is not None:
                values.append(v)
        for task in doc.get("task_evaluations", []):
            if criterion in task.get("scores", {}):
                v = _effective(task["scores"][criterion])
                if v is not None:
                    values.append(v)
    return values


def build_markdown_report(records: List[Dict[str, Any]]) -> str:
    by_model: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for r in records:
        by_model[r.get("model", "unknown")].append(r)

    lines = ["# タスク抽出 モデル比較レポート", ""]
    lines.append(f"対象モデル数: {len(by_model)} / 実行総数: {len(records)}")
    lines.append("")
    header = ["モデル", "実行回数", "文書overall平均", *CRITERIA_ORDER]
    lines.append("| " + " | ".join(header) + " |")
    lines.append("|" + "---|" * len(header))

    for model, recs in sorted(by_model.items()):
        overall_values = [
            r["evaluation_result"].get("overall_score")
            for r in recs
            if r["evaluation_result"].get("overall_score") is not None
        ]
        overall_mean = round(mean(overall_values), 2) if overall_values else None
        row = [model, str(len(recs)), str(overall_mean) if overall_mean is not None else "N/A"]
        for criterion in CRITERIA_ORDER:
            values = _criterion_values(recs, criterion)
            row.append(f"{round(mean(values), 2)}" if values else "N/A")
        lines.append("| " + " | ".join(row) + " |")

    lines.append("")
    lines.append(
        "注: 各基準のスコアは `ScoreDetail.effective_score`"
        "（人手評価があれば人手評価を最優先、無ければLLM-judge、無ければルールベース）を採用している。"
    )
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="評価結果からモデル比較レポートを生成する")
    parser.add_argument("inputs", nargs="+", help="reports/results/*.json のパス（複数指定可）")
    parser.add_argument("--out", default=None, help="出力先Markdownファイル（省略時は標準出力）")
    args = parser.parse_args()

    records = load_records([Path(p) for p in args.inputs])
    report = build_markdown_report(records)

    if args.out:
        Path(args.out).write_text(report, encoding="utf-8")
        print(f"レポートを書き出しました: {args.out}")
    else:
        print(report)


if __name__ == "__main__":
    main()
