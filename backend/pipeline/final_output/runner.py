# backend/pipeline/final_output/runner.py
"""
Phase 9のCLIエントリポイント・永続化。

**LLMは一切呼ばない。** Phase 3-8の保存済み中間結果ファイルを読み込み、
組み立てるだけ。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import List

from backend.pipeline.assignment.schema import FinalAssignment
from backend.pipeline.dependencies.schema import DependencyDocument
from backend.pipeline.final_output.assembler import assemble_final_output
from backend.pipeline.final_output.schema import FinalProjectOutput
from backend.pipeline.members.schema import MemberDirectory
from backend.pipeline.requirements.schema import RequirementDocument
from backend.pipeline.tasks.schema import TaskDocument
from backend.pipeline.validation.schema import ValidationReport

OUTPUT_DIR = Path(__file__).resolve().parent / "output"


def save_final_output(output: FinalProjectOutput, output_dir: Path = OUTPUT_DIR) -> Path:
    """最終出力をJSONファイルとして保存する"""
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = output.metadata.generated_at.replace(":", "").replace("-", "").replace(".", "")
    out_path = output_dir / f"{output.project.document_id}_{timestamp}.final.json"
    out_path.write_text(
        json.dumps(output.model_dump(mode="json"), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return out_path


def load_final_output(path: Path) -> FinalProjectOutput:
    """保存済みの最終出力を読み込み、スキーマとして再検証する"""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return FinalProjectOutput.model_validate(data)


def _main() -> None:
    import sys

    if len(sys.argv) < 7:
        print(
            "使い方: python -m backend.pipeline.final_output.runner "
            "<requirements.json> <tasks.json> <dependencies.json> <members.json> "
            "<assignments.json> <validation.json> [project_name]"
        )
        raise SystemExit(1)

    req_doc = RequirementDocument.model_validate(json.loads(Path(sys.argv[1]).read_text(encoding="utf-8")))
    task_doc = TaskDocument.model_validate(json.loads(Path(sys.argv[2]).read_text(encoding="utf-8")))
    dep_doc = DependencyDocument.model_validate(json.loads(Path(sys.argv[3]).read_text(encoding="utf-8")))
    member_dir = MemberDirectory.model_validate(json.loads(Path(sys.argv[4]).read_text(encoding="utf-8")))

    assignments_raw = json.loads(Path(sys.argv[5]).read_text(encoding="utf-8"))
    assignments: List[FinalAssignment] = [FinalAssignment.model_validate(a) for a in assignments_raw]

    validation_report = ValidationReport.model_validate(
        json.loads(Path(sys.argv[6]).read_text(encoding="utf-8"))
    )

    project_name = sys.argv[7] if len(sys.argv) > 7 else None

    output = assemble_final_output(
        req_doc, task_doc, dep_doc, member_dir, assignments, validation_report, project_name=project_name,
    )
    out_path = save_final_output(output)

    print(f"validation.status={output.validation.status}")
    print(f"保存先: {out_path}")


if __name__ == "__main__":
    _main()
