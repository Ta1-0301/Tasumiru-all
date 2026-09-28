# backend/tests/test_assignment_deadline.py
"""納期（due_date）を考慮したAssignment・Workloadのテスト（決定的、LLM不使用）。

基準日は2026-09-28（月曜）に固定する。稼働日は月〜金、期間は両端を含む。
"""

from datetime import date, timedelta
from pathlib import Path

import pytest

from backend.jobs.manager import JobManager
from backend.pipeline.assignment.audit import find_fallback_candidate
from backend.pipeline.assignment.deadline import (
    AssignmentLedger,
    check_deadline,
    free_hours_until,
    period_hours,
)
from backend.pipeline.assignment.filters import filter_candidates
from backend.pipeline.assignment.runner import run_assignment
from backend.pipeline.assignment.schema import AssignmentTask, RequiredSkill
from backend.pipeline.dependencies.schema import DependencyDocument
from backend.pipeline.members.schema import Availability, Constraint, Member, MemberDirectory, Skill
from backend.pipeline.tasks.schema import Task, TaskDocument
from backend.pipeline.validation.workload import check_workload

REF = date(2026, 9, 28)  # 月曜
WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri"]


def _days(n: int) -> date:
    return REF + timedelta(days=n)


def _member(id="M-001", hours=40.0, skills=None, current=0.0, **overrides) -> Member:
    defaults = dict(
        id=id,
        name=f"メンバー{id}",
        skills=skills if skills is not None else [Skill(skill="Python", level=3)],
        availability=Availability(
            available_hours_per_week=hours, working_days=WEEKDAYS, current_assigned_hours=current,
        ),
    )
    defaults.update(overrides)
    return Member(**defaults)


def _task(task_id="TASK-001", hours=20.0, due=None, skill="Python") -> AssignmentTask:
    return AssignmentTask(
        task_id=task_id,
        title="APIを実装する",
        required_skills=[RequiredSkill(skill=skill, min_level=1)],
        estimated_hours=hours,
        due_date=due,
    )


# --- 期間内の稼働可能時間 ---

def test_period_hours_counts_working_days_inclusive():
    m = _member(hours=40)
    assert period_hours(m, REF, _days(3), 40) == 32.0     # 月〜木の4日 × 8h
    assert period_hours(m, REF, _days(6), 40) == 40.0     # 1週間（土日は稼働しない）
    assert period_hours(m, REF, _days(14), 40) == 88.0    # 11稼働日 × 8h
    assert period_hours(m, REF, _days(-1), 40) == 0.0     # 期限が基準日より前


def test_period_hours_accepts_full_weekday_names_and_falls_back_to_calendar_days():
    full = _member(availability=Availability(available_hours_per_week=40, working_days=["Monday", "Friday"]))
    assert period_hours(full, REF, _days(6), 40) == 40.0  # 月・金の2日 × 20h
    none = _member(availability=Availability(available_hours_per_week=35, working_days=[]))
    assert period_hours(none, REF, _days(13), 35) == 70.0  # 暦日14日 = 2週間分


def test_free_hours_respects_current_assignments_and_max_hours_constraint():
    busy = _member(hours=40, current=20)
    assert free_hours_until(busy, REF, _days(6)) == 20.0
    capped = _member(hours=40, constraints=[Constraint(type="max_hours_per_week", max_hours=10)])
    assert free_hours_until(capped, REF, _days(6)) == 10.0


# --- Case 1: 期限なし（既存仕様と同じ） ---

@pytest.mark.asyncio
async def test_case1_no_due_date_gives_identical_result_with_or_without_context():
    members = [_member("M-001", skills=[Skill(skill="Python", level=5)]), _member("M-002")]
    task = _task(hours=10, due=None)

    without = await run_assignment(task, members)
    with_ctx = await run_assignment(task, members, ledger=AssignmentLedger(reference_date=REF))
    assert with_ctx.model_dump() == without.model_dump()


def test_case1_workload_without_due_dates_is_unchanged_weekly_value():
    m = _member(hours=40)
    tasks = [Task(id="TASK-001", title="t", description="d", estimated_hours=10, confidence=0.9)]
    summaries, warnings = check_workload([m], tasks, {"TASK-001": m.id}, reference_date=REF)
    assert summaries[0].basis == "weekly"
    assert summaries[0].available_hours == 40
    assert summaries[0].workload_percentage == 25.0
    assert warnings == []


# --- Case 2: 短い納期 ---

@pytest.mark.asyncio
async def test_case2_short_deadline_rejects_member_without_enough_hours():
    member = _member(hours=20)  # 1日4h × 月〜木4日 = 16h < 20h
    task = _task(hours=20, due=_days(3))
    ctx = AssignmentLedger(reference_date=REF)

    # 週あたりの既存チェックでは通る（20h <= 残り20h）
    survivors, _ = filter_candidates(task, [member])
    assert len(survivors) == 1

    result = await run_assignment(task, [member], ledger=ctx)
    assert result.status == "no_suitable_member"
    assert result.unassigned_reason == "DEADLINE_INFEASIBLE"
    assert "deadline infeasible" in result.rejected_candidates[0].reasons[0]


# --- Case 3: 長い納期 ---

@pytest.mark.asyncio
async def test_case3_long_deadline_is_feasible_for_40h_member():
    member = _member(hours=40)
    task = _task(hours=20, due=_days(14))
    result = await run_assignment(task, [member], ledger=AssignmentLedger(reference_date=REF))
    assert result.recommended_member_id == member.id
    assert any("期限内に完了可能" in r for r in result.reasons)
    assert "88.0h" in " ".join(result.reasons)


# --- Case 4: 複数タスク（期限ごとの累積負荷） ---

def test_case4_cumulative_load_is_checked_per_deadline():
    ctx = AssignmentLedger(reference_date=REF)
    a, b, c = _task("A", 20, _days(3)), _task("B", 20, _days(7)), _task("C", 20, _days(14))

    # 25h/週（1日5h）: 10/1まで20h, 10/5まで30h, 10/12まで55h
    member = _member(hours=25)
    assert check_deadline(a, member, ctx) == []
    ctx.commit(member.id, 20, a.due_date)
    assert check_deadline(b, member, ctx) != []  # 20+20=40h > 30h
    assert check_deadline(c, member, ctx) == []  # 20+20=40h <= 55h


def test_case4_adding_early_task_rechecks_later_deadlines():
    """早い期限のタスクを後から追加すると、既に割り当てた遅い期限も再確認される"""
    member = _member(hours=25)
    ctx = AssignmentLedger(reference_date=REF)
    ctx.commit(member.id, 50, _days(14))  # 10/12まで55hのうち50hを使用済み
    early = _task("E", 10, _days(3))       # 10/1までの20hには収まるが…
    reasons = check_deadline(early, member, ctx)
    assert reasons and "2026-10-12" in reasons[0]  # 10/12の累積60h > 55h


def test_case4_period_workload_replaces_single_week_denominator():
    m = _member(hours=40)
    tasks = [
        Task(id="TASK-001", title="a", description="d", estimated_hours=20, confidence=0.9, due_date=_days(3)),
        Task(id="TASK-002", title="b", description="d", estimated_hours=20, confidence=0.9, due_date=_days(7)),
        Task(id="TASK-003", title="c", description="d", estimated_hours=20, confidence=0.9, due_date=_days(14)),
    ]
    assignments = {t.id: m.id for t in tasks}

    weekly, weekly_warnings = check_workload([m], tasks, assignments)
    assert weekly[0].workload_percentage == 150.0  # 従来: 60h / 40h
    assert [w.code for w in weekly_warnings] == ["OVERLOAD"]

    period, period_warnings = check_workload([m], tasks, assignments, reference_date=REF)
    s = period[0]
    assert (s.basis, s.available_hours, s.weekly_available_hours) == ("period", 88.0, 40)
    assert (s.period_start, s.period_end) == (REF, _days(14))
    assert s.workload_percentage == round(60 / 88 * 100, 2)
    assert period_warnings == []  # 10/1: 20<=32, 10/5: 40<=48, 10/12: 60<=88


def test_case4_deadline_overload_before_period_end_is_reported():
    m = _member(hours=40)
    tasks = [
        Task(id="TASK-001", title="a", description="d", estimated_hours=40, confidence=0.9, due_date=_days(3)),
        Task(id="TASK-002", title="b", description="d", estimated_hours=8, confidence=0.9, due_date=_days(30)),
    ]
    summaries, warnings = check_workload([m], tasks, {t.id: m.id for t in tasks}, reference_date=REF)
    assert summaries[0].workload_percentage < 100  # 期間全体では収まる
    assert [w.code for w in warnings] == ["DEADLINE_OVERLOAD"]  # 10/1までの40h > 32h
    assert warnings[0].available_hours == 32.0


def test_project_due_date_applies_to_tasks_without_own_due_date():
    m = _member(hours=40)
    tasks = [Task(id="TASK-001", title="a", description="d", estimated_hours=80, confidence=0.9)]
    summaries, _ = check_workload(
        [m], tasks, {"TASK-001": m.id}, reference_date=REF, default_due_date=_days(13),
    )
    assert summaries[0].available_hours == 80.0
    assert summaries[0].workload_percentage == 100.0


# --- Case 5: スキル＋納期 ---

@pytest.mark.asyncio
async def test_case5_higher_skill_member_without_time_loses_to_member_with_time():
    a = _member("M-A", hours=40, skills=[Skill(skill="Python", level=5)])
    b = _member("M-B", hours=40, skills=[Skill(skill="Python", level=3)])
    task = _task(hours=24, due=_days(4))  # 月〜金5日: 40h

    # 納期を考慮しなければスキルの高いAが選ばれる
    plain = await run_assignment(task, [a, b])
    assert plain.recommended_member_id == "M-A"

    ctx = AssignmentLedger(reference_date=REF)
    ctx.commit("M-A", 30, _days(4))  # Aは同じ期限までに既に30h割当済み → 空き10h
    result = await run_assignment(task, [a, b], ledger=ctx)
    assert result.recommended_member_id == "M-B"
    rejected = {r.member_id: r.reasons for r in result.rejected_candidates}
    assert any("deadline infeasible" in r for r in rejected["M-A"])


def test_deadline_rejection_is_never_a_fallback_candidate():
    """スキル不一致 + 期限超過の候補は、スキル類似度が高くてもFallbackにしない"""
    member = _member(hours=40, skills=[Skill(skill="Python", level=5), Skill(skill="Go", level=5)])
    task = AssignmentTask(
        task_id="TASK-001",
        required_skills=[RequiredSkill(skill="Python"), RequiredSkill(skill="Ruby")],
        estimated_hours=8,
        due_date=_days(1),
    )
    ctx = AssignmentLedger(reference_date=REF)
    ctx.commit(member.id, 16, _days(1))  # 火曜までの16hを使い切っている
    _, rejections = filter_candidates(task, [member], ctx)

    assert find_fallback_candidate(task, [member], rejections) is not None  # 期限を知らなければ候補になる
    assert find_fallback_candidate(task, [member], rejections, ledger=ctx) is None


# --- JobManagerの逐次割当（期限の早い順） ---

def _pipeline_task(task_id: str, hours: float, due=None) -> Task:
    return Task(
        id=task_id, title=task_id, description="d", estimated_hours=hours,
        required_skills=["Python"], confidence=0.9, due_date=due,
    )


async def _run_manager_assignments(tmp_path: Path, tasks, members, **kwargs):
    manager = JobManager(output_root=tmp_path)

    async def _noop(*args, **kw):
        return None

    manager._update = _noop  # DBを使わずにAssignmentステージだけを実行する
    return await manager._run_assignments(
        "job-1",
        TaskDocument(document_id="doc", tasks=tasks),
        DependencyDocument(document_id="doc", dependencies=[]),
        MemberDirectory(members=members),
        None,
        False,
        **kwargs,
    )


@pytest.mark.asyncio
async def test_manager_assigns_in_deadline_order_and_accumulates_load(tmp_path):
    a = _member("M-A", hours=40, skills=[Skill(skill="Python", level=5)])
    b = _member("M-B", hours=40, skills=[Skill(skill="Python", level=3)])
    tasks = [
        _pipeline_task("TASK-001", 24, _days(4)),
        _pipeline_task("TASK-002", 24, _days(2)),  # 期限が早いため先に割り当てられる
    ]
    result = await _run_manager_assignments(tmp_path, tasks, [a, b], reference_date=REF)

    assert [fa.task_id for fa in result] == ["TASK-001", "TASK-002"]  # 元の順序で返す
    by_task = {fa.task_id: fa.assigned_member_id for fa in result}
    assert by_task["TASK-002"] == "M-A"  # 10/1までの24hはAに収まる
    assert by_task["TASK-001"] == "M-B"  # Aは10/2までの40hのうち24h使用済み → 残り16h < 24h


@pytest.mark.asyncio
async def test_manager_without_due_dates_accumulates_weekly_load(tmp_path):
    """納期が無くても割当工数は累積され、100%を超える割当は作らない（週40h基準）"""
    a = _member("M-A", hours=40, skills=[Skill(skill="Python", level=5)])
    b = _member("M-B", hours=40, skills=[Skill(skill="Python", level=3)])
    tasks = [_pipeline_task("TASK-001", 24), _pipeline_task("TASK-002", 24)]
    result = await _run_manager_assignments(tmp_path, tasks, [a, b], reference_date=REF)
    # 2件ともAにすると48h/40h=120%になるため、2件目はBに割り当てる
    assert [fa.assigned_member_id for fa in result] == ["M-A", "M-B"]


@pytest.mark.asyncio
async def test_manager_applies_project_due_date(tmp_path):
    a = _member("M-A", hours=40, skills=[Skill(skill="Python", level=5)])
    tasks = [_pipeline_task("TASK-001", 30), _pipeline_task("TASK-002", 30, _days(1))]
    result = await _run_manager_assignments(
        tmp_path, tasks, [a], reference_date=REF, project_due_date=_days(6),
    )
    # TASK-002（期限9/29: 月火の16h）は30hかかるため期限内に終わらない。
    # 計画期間（〜10/4: 40h）の上限には収まるので、理由は期限のみ。
    assert result[1].assigned_member_id is None
    assert result[1].ai_recommendation.unassigned_reason == "DEADLINE_INFEASIBLE"
    # プロジェクト納期(10/4)が適用されたTASK-001は40hの枠に収まる
    assert result[0].assigned_member_id == "M-A"


# --- Project APIの納期フィールド・既存DBへの列追加 ---

async def test_project_api_round_trips_optional_dates(client):
    resp = await client.post("/api/teams", json={"name": "チーム", "admin_display_name": "管理者"})
    assert resp.status_code == 201

    created = await client.post("/api/projects", json={"name": "p", "due_date": "2027-03-31"})
    assert created.status_code == 201
    body = created.json()
    assert body["due_date"] == "2027-03-31"
    assert body["start_date"] is None

    fetched = await client.get(f"/api/projects/{body['id']}")
    assert fetched.json()["due_date"] == "2027-03-31"

    legacy = await client.post("/api/projects", json={"name": "日付なし"})
    assert legacy.json()["due_date"] is None


def test_init_db_adds_date_columns_to_existing_projects_table():
    from sqlalchemy import create_engine, inspect, text

    from backend.db.session import _add_missing_columns

    engine = create_engine("sqlite://")
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE projects (id VARCHAR(36) PRIMARY KEY, team_id VARCHAR(36))"))
        conn.execute(text("INSERT INTO projects (id, team_id) VALUES ('p1', 't1')"))
        _add_missing_columns(conn)
        _add_missing_columns(conn)  # 2回目は何もしない
        columns = {c["name"] for c in inspect(conn).get_columns("projects")}
        row = conn.execute(text("SELECT id, due_date FROM projects")).one()
    assert {"start_date", "due_date"} <= columns
    assert tuple(row) == ("p1", None)
