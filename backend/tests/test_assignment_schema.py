# backend/tests/test_assignment_schema.py
"""backend/pipeline/assignment/schema.py の単体テスト。"""

import pytest

from backend.pipeline.assignment.schema import ScoringWeights


def test_scoring_weights_defaults_match_the_spec_example():
    w = ScoringWeights()
    assert w.skill_match == 0.50
    assert w.workload == 0.20
    assert w.experience == 0.20
    assert w.availability == 0.10


def test_scoring_weights_normalized_sums_to_one():
    w = ScoringWeights(skill_match=1, workload=1, experience=1, availability=1).normalized()
    assert w.skill_match == pytest.approx(0.25)
    assert w.workload == pytest.approx(0.25)
    assert w.experience == pytest.approx(0.25)
    assert w.availability == pytest.approx(0.25)


def test_scoring_weights_already_summing_to_one_are_unchanged():
    w = ScoringWeights().normalized()
    assert w.skill_match == pytest.approx(0.50)
    assert w.workload == pytest.approx(0.20)


def test_scoring_weights_rejects_zero_total():
    with pytest.raises(ValueError):
        ScoringWeights(skill_match=0, workload=0, experience=0, availability=0).normalized()
