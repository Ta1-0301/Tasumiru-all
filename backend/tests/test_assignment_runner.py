# backend/tests/test_assignment_runner.py
"""backend/pipeline/assignment/runner.py の結合テスト。

依頼された8つのテストケースをすべてカバーする:
  perfect match / partial match / overloaded member / unavailable member /
  constraint violation / no suitable member / multiple candidates /
  equal candidates
"""

import json

import pytest

from backend.pipeline.assignment.runner import run_assignment, save_assignment_result
from backend.pipeline.assignment.schema import AssignmentTask, RequiredSkill
from backend.pipeline.members.schema import Availability, Constraint, Member, Skill


def _member(id="M-001", **overrides) -> Member:
    defaults = dict(
        name=id,
        skills=[Skill(skill="Python", level=5, experience_years=5)],
        availability=Availability(available_hours_per_week=40, working_days=["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"], current_assigned_hours=5),
        constraints=[],
    )
    defaults.update(overrides)
    return Member(id=id, **defaults)


def _task(**overrides) -> AssignmentTask:
    defaults = dict(
        task_id="TASK-001",
        title="バックエンドAPIを実装する",
        required_skills=[RequiredSkill(skill="Python", min_level=3)],
        estimated_hours=8,
    )
    defaults.update(overrides)
    return AssignmentTask(**defaults)


# --- perfect match ---

@pytest.mark.asyncio
async def test_perfect_match_is_recommended_with_high_score():
    member = _member(skills=[Skill(skill="Python", level=5, experience_years=5)])
    result = await run_assignment(_task(), [member])

    assert result.status == "recommended"
    assert result.recommended_member_id == "M-001"
    assert result.score > 80


# --- partial match ---

@pytest.mark.asyncio
async def test_partial_match_is_recommended_with_lower_score_than_perfect_match():
    task = _task()
    minimal = _member(id="M-partial", skills=[Skill(skill="Python", level=3, experience_years=None)], experience_years=None)
    expert = _member(id="M-perfect", skills=[Skill(skill="Python", level=5, experience_years=5)])

    partial_result = await run_assignment(task, [minimal])
    perfect_result = await run_assignment(task, [expert])

    assert partial_result.status == "recommended"
    assert partial_result.score < perfect_result.score


# --- overloaded member ---

@pytest.mark.asyncio
async def test_overloaded_member_is_excluded_and_reported():
    overloaded = _member(availability=Availability(available_hours_per_week=40, current_assigned_hours=35))
    result = await run_assignment(_task(estimated_hours=10), [overloaded])

    assert result.status == "no_suitable_member"
    assert any("workload exceeds maximum" in r for r in result.rejected_candidates[0].reasons)


# --- unavailable member ---

@pytest.mark.asyncio
async def test_unavailable_member_is_excluded_and_reported():
    unavailable = _member(availability=Availability(available_hours_per_week=40, current_assigned_hours=40))
    result = await run_assignment(_task(), [unavailable])

    assert result.status == "no_suitable_member"
    assert any("unavailable" in r for r in result.rejected_candidates[0].reasons)


# --- constraint violation ---

@pytest.mark.asyncio
async def test_constraint_violation_is_excluded_and_reported():
    restricted = _member(constraints=[Constraint(type="scope_restriction", value="frontend")])
    result = await run_assignment(_task(domain="backend"), [restricted])

    assert result.status == "no_suitable_member"
    assert any("対象領域" in r for r in result.rejected_candidates[0].reasons)


@pytest.mark.asyncio
async def test_requires_review_constraint_produces_a_warning_not_a_rejection():
    member = _member(constraints=[Constraint(type="requires_review", value="senior member")])
    result = await run_assignment(_task(), [member])

    assert result.status == "recommended"
    assert any("レビュー要件" in w for w in result.warnings)


# --- no suitable member ---

@pytest.mark.asyncio
async def test_no_suitable_member_when_no_one_passes_filtering():
    member = _member(skills=[Skill(skill="Go", level=5)])  # 必要スキルを持たない
    result = await run_assignment(_task(), [member])

    assert result.status == "no_suitable_member"
    assert result.recommended_member_id is None
    assert result.score is None
    assert result.candidate_scores == []


@pytest.mark.asyncio
async def test_no_suitable_member_for_empty_member_list():
    result = await run_assignment(_task(), [])
    assert result.status == "no_suitable_member"


# --- multiple candidates ---

@pytest.mark.asyncio
async def test_multiple_candidates_are_all_scored_and_ranked():
    strong = _member(id="M-strong", skills=[Skill(skill="Python", level=5, experience_years=5)])
    medium = _member(id="M-medium", skills=[Skill(skill="Python", level=4, experience_years=2)])
    weak = _member(id="M-weak", skills=[Skill(skill="Python", level=3, experience_years=None)])

    result = await run_assignment(_task(), [weak, strong, medium])

    assert result.status == "recommended"
    assert result.recommended_member_id == "M-strong"
    assert [c.member_id for c in result.candidate_scores] == ["M-strong", "M-medium", "M-weak"]
    assert len(result.candidate_scores) == 3


# --- equal candidates ---

@pytest.mark.asyncio
async def test_equal_candidates_produce_a_tie_warning():
    a = _member(id="M-A", skills=[Skill(skill="Python", level=5, experience_years=5)])
    b = _member(id="M-B", skills=[Skill(skill="Python", level=5, experience_years=5)])

    result = await run_assignment(_task(), [a, b])

    assert result.status == "recommended"
    assert result.candidate_scores[0].score == result.candidate_scores[1].score
    assert any("僅差" in w for w in result.warnings)
    # 同点でも決定的に一意の推薦を出す（member_id昇順でタイブレーク）
    assert result.recommended_member_id == "M-A"


# --- dependency awareness (bonus: uses Phase 5 task IDs as explicit constraint signal) ---

@pytest.mark.asyncio
async def test_unmet_dependency_produces_a_warning():
    member = _member()
    task = _task(dependencies=["TASK-000"])
    result = await run_assignment(task, [member], completed_task_ids=set())
    assert any("前提タスクが未完了" in w for w in result.warnings)


@pytest.mark.asyncio
async def test_met_dependency_produces_no_warning():
    member = _member()
    task = _task(dependencies=["TASK-000"])
    result = await run_assignment(task, [member], completed_task_ids={"TASK-000"})
    assert not any("前提タスクが未完了" in w for w in result.warnings)


# --- LLM reasoning is optional and additive only ---

@pytest.mark.asyncio
async def test_llm_reasoning_is_skipped_without_a_client():
    member = _member()
    result = await run_assignment(_task(), [member], client=None)
    assert result.recommended_member_id == "M-001"  # 決定的スコアリングだけで確定する


@pytest.mark.asyncio
async def test_llm_reasoning_appends_but_never_changes_the_recommendation():
    from backend.services.llm import BaseLLMClient

    class FakeLLMClient(BaseLLMClient):
        async def complete(self, prompt: str, *, json_mode: bool = False) -> str:
            return json.dumps({
                "reasons": ["LLMによる追加の説明"], "warnings": [],
                "recommended_member_id": "M-999",  # 無視されるはず
            }, ensure_ascii=False)

    member = _member()
    result = await run_assignment(_task(), [member], client=FakeLLMClient())

    assert result.recommended_member_id == "M-001"
    assert "LLMによる追加の説明" in result.reasons


def test_save_assignment_result_writes_valid_json(tmp_path):
    import asyncio
    member = _member()
    result = asyncio.run(run_assignment(_task(), [member]))
    out_path = save_assignment_result(result, output_dir=tmp_path)

    assert out_path.exists()
    loaded = json.loads(out_path.read_text(encoding="utf-8"))
    assert loaded["task_id"] == "TASK-001"
    assert loaded["status"] == "recommended"
