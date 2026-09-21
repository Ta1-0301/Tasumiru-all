# backend/tests/test_final_output_runner.py
"""backend/pipeline/final_output/runner.py の単体テスト（save/load）。"""

import json

from backend.pipeline.final_output.assembler import assemble_final_output
from backend.pipeline.final_output.runner import load_final_output, save_final_output
from backend.pipeline.dependencies.schema import DependencyDocument
from backend.pipeline.members.schema import Availability, Member, MemberDirectory
from backend.pipeline.requirements.schema import Requirement, RequirementDocument
from backend.pipeline.tasks.schema import Task, TaskDocument
from backend.pipeline.validation.schema import ValidationReport


def _build_output():
    req_doc = RequirementDocument(
        document_id="spec_a",
        requirements=[Requirement(id="REQ-001", type="functional", title="t", description="d", confidence=0.9)],
    )
    task_doc = TaskDocument(
        document_id="spec_a",
        tasks=[Task(id="TASK-001", requirement_ids=["REQ-001"], title="t", description="d", confidence=0.9)],
    )
    dep_doc = DependencyDocument(document_id="spec_a", dependencies=[])
    member_dir = MemberDirectory(members=[Member(id="M-001", name="M", availability=Availability(available_hours_per_week=40))])
    return assemble_final_output(req_doc, task_doc, dep_doc, member_dir, [], ValidationReport(valid=True))


def test_save_final_output_writes_valid_json(tmp_path):
    output = _build_output()
    out_path = save_final_output(output, output_dir=tmp_path)

    assert out_path.exists()
    loaded_json = json.loads(out_path.read_text(encoding="utf-8"))
    assert loaded_json["project"]["document_id"] == "spec_a"
    assert loaded_json["validation"]["status"] == "valid"


def test_save_and_load_round_trip_preserves_all_data(tmp_path):
    output = _build_output()
    out_path = save_final_output(output, output_dir=tmp_path)
    reloaded = load_final_output(out_path)

    assert reloaded.project.document_id == output.project.document_id
    assert reloaded.requirements == output.requirements
    assert reloaded.tasks == output.tasks
    assert reloaded.validation.status == output.validation.status


def test_loading_reapplies_full_schema_validation(tmp_path):
    """保存済みJSONを直接改変しても、再読み込み時にスキーマ検証がかかる"""
    output = _build_output()
    out_path = save_final_output(output, output_dir=tmp_path)

    data = json.loads(out_path.read_text(encoding="utf-8"))
    del data["metadata"]
    out_path.write_text(json.dumps(data), encoding="utf-8")

    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        load_final_output(out_path)
