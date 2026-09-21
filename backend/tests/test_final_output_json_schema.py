# backend/tests/test_final_output_json_schema.py
"""backend/pipeline/final_output/json_schema.py の単体テスト。"""

from backend.pipeline.final_output.json_schema import get_json_schema, validate_output_json


def _valid_output_dict():
    return {
        "project": {"document_id": "doc_1"},
        "requirements": [],
        "tasks": [],
        "dependencies": [],
        "members": [],
        "assignments": [],
        "validation": {
            "status": "valid", "critical_issue_count": 0, "warning_issue_count": 0,
            "traceability_errors": [],
            "report": {"valid": True},
        },
        "metadata": {"generated_at": "2026-01-01T00:00:00+00:00", "pipeline_version": "1.0.0"},
    }


def test_get_json_schema_returns_a_real_schema_document():
    schema = get_json_schema()
    assert schema["type"] == "object"
    assert "properties" in schema
    for key in ("project", "requirements", "tasks", "dependencies", "members", "assignments", "validation", "metadata"):
        assert key in schema["properties"]


def test_validate_output_json_accepts_a_conforming_document():
    assert validate_output_json(_valid_output_dict()) == []


def test_validate_output_json_reports_missing_required_field():
    data = _valid_output_dict()
    del data["metadata"]
    errors = validate_output_json(data)
    assert errors
    assert any("metadata" in e for e in errors)


def test_validate_output_json_reports_invalid_status_value():
    data = _valid_output_dict()
    data["validation"]["status"] = "totally_fine"  # valid/warning/error以外
    errors = validate_output_json(data)
    assert errors
    assert any("status" in e for e in errors)


def test_validate_output_json_reports_multiple_errors_at_once():
    data = _valid_output_dict()
    del data["project"]
    del data["tasks"]
    errors = validate_output_json(data)
    assert len(errors) >= 2
