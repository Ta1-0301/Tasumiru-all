# backend/tests/test_assignment_load_balancing.py
"""負荷率100%以内・負荷の均一化のテスト（決定的、LLM不使用）。

各メンバーは週40h・月〜金。現在の負荷は台帳(AssignmentLedger)に割当済み工数として
記録する（例: 36h = 90%）。納期情報は無い（週40h基準）。
"""

import random
from pathlib import Path

import pytest

from backend.jobs.manager import JobManager
from backend.pipeline.assignment.deadline import AssignmentLedger
from backend.pipeline.assignment.runner import run_assignment
from backend.pipeline.assignment.schema import AssignmentTask, RequiredSkill
from backend.pipeline.dependencies.schema import DependencyDocument
from backend.pipeline.members.schema import Availability, Member, MemberDirectory, Skill
from backend.pipeline.tasks.schema import Task, TaskDocument
from backend.pipeline.validation.workload import check_workload

WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri"]


def _member(id, level=3, skills=None, current=0.0) -> Member:
    return Member(
        id=id,
        name=f"メンバー{id}",
        skills=skills if skills is not None else [Skill(skill="Python", level=level)],
        availability=Availability(available_hours_per_week=40, working_days=WEEKDAYS, current_assigned_hours=current),
    )


def _task(hours, skills=("Python",)) -> AssignmentTask:
    return AssignmentTask(
        task_id="TASK-001",
        required_skills=[RequiredSkill(skill=s) for s in skills],
        estimated_hours=hours,
    )


def _ledger(**loads_in_percent) -> AssignmentLedger:
    ledger = AssignmentLedger()
    for member_id, pct in loads_in_percent.items():
        ledger.commit(member_id, 40 * pct / 100, None)
    return ledger


# --- Case 1: A=90%, B=40%, C=30% → B/Cを優先 ---

@pytest.mark.asyncio
async def test_case1_prefers_less_loaded_members():
    members = [_member("A"), _member("B"), _member("C")]
    result = await run_assignment(_task(4), members, ledger=_ledger(A=90, B=40, C=30))
    assert result.recommended_member_id == "C"  # 割当後: A100% / B50% / C40%


# --- Case 2: A=90%, B=95%, C=30% → Cを優先 ---

@pytest.mark.asyncio
async def test_case2_assigns_to_member_with_room():
    members = [_member("A"), _member("B"), _member("C")]
    result = await run_assignment(_task(4), members, ledger=_ledger(A=90, B=95, C=30))
    assert result.recommended_member_id == "C"


# --- Case 3: A=90%, B=90% → どちらも100%超過 → 未割当 ---

@pytest.mark.asyncio
async def test_case3_unassigned_when_everyone_would_exceed_100():
    members = [_member("A"), _member("B")]
    result = await run_assignment(_task(6), members, ledger=_ledger(A=90, B=90))  # 両者105%
    assert result.status == "no_suitable_member"
    assert result.unassigned_reason == "WORKLOAD_TOO_HIGH"
    assert all("100%を超えます" in r.reasons[0] for r in result.rejected_candidates)


# --- Case 4: A=95%(スキル高), B=60% → 同等のスキルならBを選ぶ ---

@pytest.mark.asyncio
async def test_case4_prefers_comparable_skill_member_with_lower_load():
    a, b = _member("A", level=5), _member("B", level=4)
    result = await run_assignment(_task(2), [a, b], ledger=_ledger(A=95, B=60))
    assert result.recommended_member_id == "B"  # Aは100%ちょうどで割当可能だがBは65%
    assert any("負荷の均一化" in w for w in result.warnings)


@pytest.mark.asyncio
async def test_case4_skill_gap_beyond_tolerance_keeps_the_skilled_member():
    """どちらも80%以内なら、スキル差が1レベルを超える人を負荷だけで選ばない"""
    a, b = _member("A", level=5), _member("B", level=2)
    result = await run_assignment(_task(4), [a, b], ledger=_ledger(A=50, B=10))
    assert result.recommended_member_id == "A"


# --- Case 5: A=90%, B=40%, C=35% → 複数タスクをB/Cに振り分けて均一化 ---

def _pipeline_task(task_id, hours, skills=("Python",)) -> Task:
    return Task(id=task_id, title=task_id, description="d", estimated_hours=hours,
                required_skills=list(skills), confidence=0.9)


async def _run_manager(tmp_path: Path, tasks, members):
    manager = JobManager(output_root=tmp_path)

    async def _noop(*args, **kw):
        return None

    manager._update = _noop
    return await manager._run_assignments(
        "job-1", TaskDocument(document_id="doc", tasks=tasks),
        DependencyDocument(document_id="doc", dependencies=[]),
        MemberDirectory(members=members), None, False,
    )


@pytest.mark.asyncio
async def test_case5_multiple_tasks_are_spread_to_equalize_load(tmp_path):
    members = [_member("A", current=36), _member("B", current=16), _member("C", current=14)]
    tasks = [_pipeline_task(f"TASK-00{i}", 4) for i in range(1, 5)]
    result = await _run_manager(tmp_path, tasks, members)

    assigned = [fa.assigned_member_id for fa in result]
    assert None not in assigned and "A" not in assigned
    load = {m.id: m.availability.current_assigned_hours for m in members}
    for fa in result:
        load[fa.assigned_member_id] += 4
    assert load == {"A": 36, "B": 24, "C": 22}  # 90% / 60% / 55%


# --- Case 6: 必要スキルを持つ唯一の人が100%超過 → 別スキルの人へ回さない ---

@pytest.mark.asyncio
async def test_case6_no_fallback_to_other_skill_when_only_skilled_member_is_full():
    skilled = _member("A", skills=[Skill(skill="Python", level=5), Skill(skill="Ruby", level=5)])
    similar = _member("B", skills=[Skill(skill="Python", level=5), Skill(skill="Go", level=5)])
    task = _task(8, skills=("Python", "Ruby"))

    # Aが空いていればAに割り当てる
    free = await run_assignment(task, [skilled, similar], ledger=_ledger())
    assert free.recommended_member_id == "A"

    full = await run_assignment(task, [skilled, similar], ledger=_ledger(A=90))
    assert full.status == "no_suitable_member"
    assert "REQUIRED_SKILL_NOT_EXACT_MATCH" not in full.warnings
    # 既存の分類規則のまま（A: WORKLOAD_TOO_HIGH, B: NO_REQUIRED_SKILL の同数 → 既存の優先順）
    assert full.unassigned_reason == "NO_REQUIRED_SKILL"


@pytest.mark.asyncio
async def test_fallback_still_works_when_nobody_has_the_exact_skill():
    similar = _member("B", skills=[Skill(skill="Python", level=5), Skill(skill="Go", level=5)])
    result = await run_assignment(_task(8, skills=("Python", "Ruby")), [similar], ledger=_ledger())
    assert result.recommended_member_id == "B"
    assert "REQUIRED_SKILL_NOT_EXACT_MATCH" in result.warnings


@pytest.mark.asyncio
async def test_top_scorer_over_100_does_not_make_task_unassigned_when_another_fits():
    a, b = _member("A", level=5), _member("B", level=3)
    result = await run_assignment(_task(8), [a, b], ledger=_ledger(A=100))
    assert result.recommended_member_id == "B"


@pytest.mark.asyncio
async def test_without_ledger_selection_is_unchanged():
    """台帳を渡さない呼び出し（CLI等）は従来の選択ロジックのまま"""
    a, b = _member("A", level=5), _member("B", level=3)
    result = await run_assignment(_task(4), [a, b])
    assert result.recommended_member_id == "A"


# --- 不変条件: どんなタスク列でも最終的な負荷率は100%を超えない ---

@pytest.mark.asyncio
async def test_final_workload_never_exceeds_100_percent(tmp_path):
    rng = random.Random(0)
    skills = ["Python", "React", "SQL"]
    members = [
        _member(f"M{i}", skills=[Skill(skill=s, level=rng.randint(1, 5)) for s in rng.sample(skills, 2)],
                current=rng.choice([0, 8, 20]))
        for i in range(4)
    ]
    tasks = [
        _pipeline_task(f"TASK-{i:03d}", rng.choice([2, 4, 8, 16]), [rng.choice(skills)])
        for i in range(1, 41)
    ]
    result = await _run_manager(tmp_path, tasks, members)
    assignments = {fa.task_id: fa.assigned_member_id for fa in result if fa.assigned_member_id}
    summaries, warnings = check_workload(members, tasks, assignments)

    for m in members:
        total = m.availability.current_assigned_hours + sum(
            t.estimated_hours for t in tasks if assignments.get(t.id) == m.id
        )
        assert total <= m.availability.available_hours_per_week
    assert all(s.workload_percentage <= 100 for s in summaries)
    assert warnings == []
