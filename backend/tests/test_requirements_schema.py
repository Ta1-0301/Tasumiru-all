# backend/tests/test_requirements_schema.py
"""backend/pipeline/requirements/schema.py の単体テスト。"""

import pytest
from pydantic import ValidationError

from backend.pipeline.requirements.schema import Requirement, RequirementCandidate, SourceReference


def _make_requirement(**overrides):
    defaults = dict(
        id="REQ-001",
        type="functional",
        title="認証APIを実装する",
        description="招待URL方式で参加できる認証APIを実装する",
        priority="high",
        origin="explicit",
        source_reference=SourceReference(document_id="doc_1", source_text="招待URLで参加できる"),
        confidence=0.9,
    )
    defaults.update(overrides)
    return Requirement(**defaults)


def test_requirement_accepts_valid_data():
    req = _make_requirement()
    assert req.id == "REQ-001"
    assert req.source_reference.page is None


def test_requirement_rejects_invalid_id_format():
    with pytest.raises(ValidationError):
        _make_requirement(id="not-an-id")


def test_requirement_rejects_unknown_type():
    with pytest.raises(ValidationError):
        _make_requirement(type="not_a_real_type")


def test_requirement_rejects_confidence_out_of_range():
    with pytest.raises(ValidationError):
        _make_requirement(confidence=1.5)
    with pytest.raises(ValidationError):
        _make_requirement(confidence=-0.1)


def test_requirement_defaults_priority_and_origin():
    req = Requirement(
        id="REQ-002", type="assumption", title="t", description="d", confidence=0.5,
    )
    assert req.priority == "unknown"
    assert req.origin == "explicit"
    assert req.source_reference is None


def test_source_reference_page_defaults_to_none():
    ref = SourceReference(document_id="doc_1")
    assert ref.page is None
    assert ref.section is None


def test_requirement_candidate_confidence_defaults_mid():
    candidate = RequirementCandidate(type="constraint", title="t", description="d")
    assert candidate.confidence == 0.5
