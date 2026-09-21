# backend/tests/test_dependencies_schema.py
"""backend/pipeline/dependencies/schema.py の単体テスト。"""

import pytest
from pydantic import ValidationError

from backend.pipeline.dependencies.schema import Dependency


def test_dependency_accepts_valid_data():
    dep = Dependency(
        from_task_id="TASK-001", to_task_id="TASK-002", type="required",
        reason="データベース設計が終わらないとAPIを実装できない", confidence=0.9,
    )
    assert dep.from_task_id == "TASK-001"
    assert dep.type == "required"


def test_dependency_defaults_type_to_optional():
    dep = Dependency(from_task_id="TASK-001", to_task_id="TASK-002", confidence=0.5)
    assert dep.type == "optional"
    assert dep.reason == ""


def test_dependency_rejects_unknown_type():
    with pytest.raises(ValidationError):
        Dependency(from_task_id="TASK-001", to_task_id="TASK-002", type="mandatory", confidence=0.5)


def test_dependency_rejects_confidence_out_of_range():
    with pytest.raises(ValidationError):
        Dependency(from_task_id="TASK-001", to_task_id="TASK-002", confidence=1.5)
    with pytest.raises(ValidationError):
        Dependency(from_task_id="TASK-001", to_task_id="TASK-002", confidence=-0.1)
