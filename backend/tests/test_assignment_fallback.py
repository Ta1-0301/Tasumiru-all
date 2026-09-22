# backend/tests/test_assignment_fallback.py
"""Fallback Assignment(STEP7)の単体テスト。

既存のハード制約(filters.py)・スコアリング(scoring.py)は一切変更しない。
availability/workload/explicit constraintで拒否された候補は、
スキル類似度がどれだけ高くてもFallback対象にしないことを重点的に確認する。
"""

import pytest

from backend.pipeline.assignment.audit import find_fallback_candidate
from backend.pipeline.assignment.filters import filter_candidates
from backend.pipeline.assignment.runner import run_assignment
from backend.pipeline.assignment.schema import AssignmentTask, RequiredSkill
from backend.pipeline.members.schema import Availability, Constraint, Member, Skill
from backend.services.skill_matching import skill_similarity


def _member(**overrides) -> Member:
    defaults = dict(
        id="M-001",
        name="山田太郎",
        skills=[Skill(skill="Python", level=5)],
        availability=Availability(available_hours_per_week=40, working_days=["Monday"], current_assigned_hours=0),
        constraints=[],
    )
    defaults.update(overrides)
    return Member(**defaults)


def _task(**overrides) -> AssignmentTask:
    defaults = dict(
        task_id="TASK-001",
        title="何かを実装する",
        required_skills=[RequiredSkill(skill="Python", min_level=1), RequiredSkill(skill="Ruby", min_level=1)],
        estimated_hours=8,
    )
    defaults.update(overrides)
    return AssignmentTask(**defaults)


# --- find_fallback_candidate ---

def test_finds_fallback_when_skill_similarity_above_threshold():
    """要求=[Python, Ruby]、メンバー=[Python, Go]。Rubyは完全一致せずハード拒否
    されるが、Pythonが共通のためskill_similarityが閾値を超える。"""
    member = _member(skills=[Skill(skill="Python", level=5), Skill(skill="Go", level=5)])
    task = _task()
    survivors, rejections = filter_candidates(task, [member])
    assert survivors == []  # Rubyを持たないためハード拒否される

    fallback = find_fallback_candidate(task, [member], rejections)
    assert fallback is not None
    assert fallback.member_id == "M-001"
    assert fallback.skill_similarity >= 0.3


def test_no_fallback_when_similarity_below_threshold():
    """要求とメンバーのスキルに全く重なりが無ければFallbackも見つからない。"""
    member = _member(skills=[Skill(skill="Go", level=5)])
    task = AssignmentTask(task_id="TASK-002", required_skills=[RequiredSkill(skill="Elixir", min_level=1)])
    survivors, rejections = filter_candidates(task, [member])
    assert survivors == []

    fallback = find_fallback_candidate(task, [member], rejections)
    assert fallback is None


def test_availability_rejection_is_never_a_fallback_candidate():
    """稼働可能キャパシティが無いメンバーは、スキルが完全一致していても
    Fallback対象にしない（ハード制約を勝手に緩和しない）。"""
    member = _member(
        skills=[Skill(skill="Python", level=5), Skill(skill="Ruby", level=5)],
        availability=Availability(available_hours_per_week=40, current_assigned_hours=40),
    )
    task = _task()
    survivors, rejections = filter_candidates(task, [member])
    assert survivors == []

    fallback = find_fallback_candidate(task, [member], rejections)
    assert fallback is None


def test_workload_rejection_is_never_a_fallback_candidate():
    member = _member(
        skills=[Skill(skill="Python", level=5), Skill(skill="Ruby", level=5)],
        availability=Availability(available_hours_per_week=10, current_assigned_hours=5),
    )
    task = _task(estimated_hours=8)  # 残り5hに対し8h
    survivors, rejections = filter_candidates(task, [member])
    assert survivors == []

    fallback = find_fallback_candidate(task, [member], rejections)
    assert fallback is None


def test_explicit_constraint_rejection_is_never_a_fallback_candidate():
    member = _member(
        skills=[Skill(skill="Python", level=5), Skill(skill="Ruby", level=5)],
        constraints=[Constraint(type="scope_restriction", value="frontend")],
    )
    task = _task(domain="backend")
    survivors, rejections = filter_candidates(task, [member])
    assert survivors == []

    fallback = find_fallback_candidate(task, [member], rejections)
    assert fallback is None


def test_highest_similarity_candidate_is_chosen_among_multiple():
    """2人ともFallback対象になりうる場合、実際にskill_similarityが高い方が
    選ばれることを確認する（どちらが高くなるかは既存のTF-IDF実装の挙動に
    従うため、期待値を決め打ちせず実際の計算結果と突き合わせる）。"""
    m1 = _member(id="M-001", skills=[Skill(skill="Python", level=5)])
    m2 = _member(id="M-002", skills=[Skill(skill="Python", level=5), Skill(skill="Go", level=5)])
    task = _task()
    survivors, rejections = filter_candidates(task, [m1, m2])
    assert survivors == []

    sim1 = skill_similarity(["Python", "Ruby"], ["Python"])
    sim2 = skill_similarity(["Python", "Ruby"], ["Python", "Go"])
    expected_winner = "M-001" if sim1 > sim2 else "M-002"

    fallback = find_fallback_candidate(task, [m1, m2], rejections)
    assert fallback is not None
    assert fallback.member_id == expected_winner
    assert fallback.skill_similarity == max(sim1, sim2)


# --- run_assignment() 統合: Fallbackがwarningsに反映され、status="recommended"になる ---

@pytest.mark.asyncio
async def test_run_assignment_uses_fallback_and_flags_warning():
    member = _member(skills=[Skill(skill="Python", level=5), Skill(skill="Go", level=5)])
    task = _task()
    result = await run_assignment(task, [member])

    assert result.status == "recommended"
    assert result.recommended_member_id == "M-001"
    assert "REQUIRED_SKILL_NOT_EXACT_MATCH" in result.warnings
    assert result.unassigned_reason is None


@pytest.mark.asyncio
async def test_run_assignment_stays_unassigned_when_no_fallback_found():
    member = _member(skills=[Skill(skill="Go", level=5)])
    task = AssignmentTask(task_id="TASK-003", required_skills=[RequiredSkill(skill="Elixir", min_level=1)])
    result = await run_assignment(task, [member])

    assert result.status == "no_suitable_member"
    assert result.recommended_member_id is None
    assert result.unassigned_reason == "NO_REQUIRED_SKILL"


@pytest.mark.asyncio
async def test_run_assignment_never_falls_back_for_availability_violation():
    """全候補が稼働不可の場合、Fallbackを使ってでも誰かに割り当てたりしない。"""
    member = _member(
        skills=[Skill(skill="Python", level=5), Skill(skill="Ruby", level=5)],
        availability=Availability(available_hours_per_week=40, current_assigned_hours=40),
    )
    task = _task()
    result = await run_assignment(task, [member])

    assert result.status == "no_suitable_member"
    assert result.unassigned_reason == "NO_AVAILABILITY"
