# backend/tests/test_validation_runner.py
"""backend/pipeline/validation/runner.py の結合テスト。"""

import json

import pytest

from backend.pipeline.assignment.schema import AssignmentResult, FinalAssignment
from backend.pipeline.dependencies.schema import Dependency
from backend.pipeline.members.schema import Availability, Constraint, Member, Skill
from backend.pipeline.requirements.schema import Requirement
from backend.pipeline.tasks.schema import Task
from backend.pipeline.validation.runner import (
    assignments_from_final,
    save_validation_report,
    validate_project_plan,
    validate_project_plan_with_llm_verification,
)
from backend.services.llm import BaseLLMClient


def _req(id) -> Requirement:
    return Requirement(id=id, type="functional", title=f"要求{id}", description="説明", confidence=0.9)


def _task(id, requirement_ids=None, title="タスク", required_skills=None, estimated_hours=8) -> Task:
    return Task(
        id=id, requirement_ids=requirement_ids or [], title=title, description="説明",
        required_skills=required_skills or [], estimated_hours=estimated_hours, confidence=0.9,
    )


def _member(id, skills=None, available=40, current=0, constraints=None) -> Member:
    return Member(
        id=id, name=id, skills=skills or [],
        availability=Availability(available_hours_per_week=available, current_assigned_hours=current),
        constraints=constraints or [],
    )


# --- a fully clean plan: valid == True ---

def test_valid_plan_produces_no_issues():
    requirements = [_req("REQ-001")]
    tasks = [_task("TASK-001", requirement_ids=["REQ-001"], required_skills=["Python"])]
    dependencies: list[Dependency] = []
    members = [_member("M-001", skills=[Skill(skill="Python", level=5)])]
    assignments = {"TASK-001": "M-001"}

    report = validate_project_plan(requirements, tasks, dependencies, members, assignments)

    assert report.valid is True
    assert report.missing_requirements == []
    assert report.duplicate_tasks == []
    assert report.dependency_errors == []
    assert report.workload_warnings == []
    assert report.skill_mismatches == []
    assert report.constraint_violations == []
    assert len(report.workload_summaries) == 1


# --- a plan with a problem in every single category: nothing silently ignored ---

def test_broken_plan_surfaces_every_category_of_issue_simultaneously():
    requirements = [_req("REQ-001"), _req("REQ-002")]  # REQ-002はどのタスクにも紐づかない

    tasks = [
        _task("TASK-001", requirement_ids=["REQ-001"], title="認証APIを実装する", required_skills=["Python"], estimated_hours=50),
        _task("TASK-002", requirement_ids=["REQ-001"], title="認証APIを実装すること", required_skills=["Python"]),  # 重複候補
    ]

    dependencies = [
        Dependency(from_task_id="TASK-001", to_task_id="TASK-002", type="required", confidence=0.9),
        Dependency(from_task_id="TASK-002", to_task_id="TASK-001", type="required", confidence=0.9),  # 循環+実行不可能
        Dependency(from_task_id="TASK-001", to_task_id="TASK-999", confidence=0.5),  # 存在しない参照
    ]

    members = [_member("M-001", skills=[], available=40, current=0)]  # Pythonを持たない、過負荷になる

    assignments = {"TASK-001": "M-001"}  # 前提(存在しないTASK-999絡み)は別問題

    report = validate_project_plan(requirements, tasks, dependencies, members, assignments)

    assert report.valid is False
    assert any(m.requirement_id == "REQ-002" for m in report.missing_requirements)
    assert len(report.duplicate_tasks) >= 1
    dep_codes = {e.code for e in report.dependency_errors}
    assert "CIRCULAR_DEPENDENCY" in dep_codes
    assert "IMPOSSIBLE_ORDERING" in dep_codes
    assert "MISSING_DEPENDENCY_REFERENCE" in dep_codes
    assert any(w.code == "OVERLOAD" for w in report.workload_warnings)
    assert any(sm.skill == "Python" for sm in report.skill_mismatches)
    assert any(c.code == "HARD_CONSTRAINT_VIOLATED" for c in report.constraint_violations)


def test_assignment_to_nonexistent_member_is_surfaced_as_constraint_violation():
    requirements = [_req("REQ-001")]
    tasks = [_task("TASK-001", requirement_ids=["REQ-001"])]
    report = validate_project_plan(requirements, tasks, [], [], {"TASK-001": "M-ghost"})
    assert report.valid is False
    assert any(c.code == "UNKNOWN_MEMBER" for c in report.constraint_violations)


# --- assignments_from_final adapter ---

def test_assignments_from_final_extracts_only_assigned_tasks():
    final = [
        FinalAssignment(
            task_id="TASK-001", assigned_member_id="M-001", decided_by="ai",
            ai_recommendation=AssignmentResult(task_id="TASK-001", status="no_suitable_member"),
        ),
        FinalAssignment(
            task_id="TASK-002", assigned_member_id=None, decided_by="human", override_reason="見送り",
            ai_recommendation=AssignmentResult(task_id="TASK-002", status="no_suitable_member"),
        ),
    ]
    assignments = assignments_from_final(final)
    assert assignments == {"TASK-001": "M-001"}


# --- LLM-augmented duplicate verification never changes the number of flagged duplicates ---

class FakeLLMClient(BaseLLMClient):
    async def complete(self, prompt: str, *, json_mode: bool = False) -> str:
        return json.dumps({"duplicate": False, "explanation": "内容は違う"})


@pytest.mark.asyncio
async def test_llm_verification_annotates_but_never_removes_duplicate_candidates():
    requirements = [_req("REQ-001")]
    tasks = [
        _task("TASK-001", requirement_ids=["REQ-001"], title="認証APIを実装する"),
        _task("TASK-002", requirement_ids=["REQ-001"], title="認証APIを実装すること"),
    ]
    members = [_member("M-001")]
    assignments = {}

    report = await validate_project_plan_with_llm_verification(
        requirements, tasks, [], members, assignments, client=FakeLLMClient(),
    )

    assert len(report.duplicate_tasks) == 1
    assert report.duplicate_tasks[0].method == "hybrid"


@pytest.mark.asyncio
async def test_llm_verification_is_skipped_without_a_client():
    requirements = [_req("REQ-001")]
    tasks = [
        _task("TASK-001", requirement_ids=["REQ-001"], title="認証APIを実装する"),
        _task("TASK-002", requirement_ids=["REQ-001"], title="認証APIを実装すること"),
    ]
    report = await validate_project_plan_with_llm_verification(requirements, tasks, [], [], {}, client=None)
    assert report.duplicate_tasks[0].method == "rule"


# --- persistence ---

def test_save_validation_report_writes_valid_json(tmp_path):
    report = validate_project_plan([_req("REQ-001")], [], [], [], {})
    out_path = save_validation_report(report, output_dir=tmp_path)

    assert out_path.exists()
    loaded = json.loads(out_path.read_text(encoding="utf-8"))
    assert loaded["valid"] is False  # REQ-001に対応するタスクが無い
    assert len(loaded["missing_requirements"]) == 1
