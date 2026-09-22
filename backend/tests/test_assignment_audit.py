# backend/tests/test_assignment_audit.py
"""backend/pipeline/assignment/audit.py の単体テスト。

`filters.py`の判定ロジック自体は再利用するだけで変更しないため、ここでは
「既存のチェック結果がどう分類されるか」だけを検証する。
"""

from backend.pipeline.assignment.audit import (
    classify_member_rejection,
    determine_unassigned_reason,
    summarize_assignment_audit,
)
from backend.pipeline.assignment.schema import (
    AssignmentResult,
    AssignmentTask,
    CandidateRejection,
    FinalAssignment,
    RequiredSkill,
)
from backend.pipeline.members.schema import Availability, Constraint, Member, Skill


def _member(**overrides) -> Member:
    defaults = dict(
        id="M-001",
        name="山田太郎",
        skills=[Skill(skill="Python", level=5, experience_years=3)],
        availability=Availability(available_hours_per_week=40, working_days=["Monday"], current_assigned_hours=10),
        constraints=[],
    )
    defaults.update(overrides)
    return Member(**defaults)


def _task(**overrides) -> AssignmentTask:
    defaults = dict(
        task_id="TASK-001",
        title="バックエンドAPIを実装する",
        required_skills=[RequiredSkill(skill="Python", min_level=3)],
        estimated_hours=8,
    )
    defaults.update(overrides)
    return AssignmentTask(**defaults)


# --- classify_member_rejection: 既存チェックの再分類 ---

def test_classify_missing_skill_as_no_required_skill():
    member = _member(skills=[Skill(skill="Go", level=5)])
    assert classify_member_rejection(_task(), member) == ["NO_REQUIRED_SKILL"]


def test_classify_zero_capacity_as_no_availability():
    member = _member(availability=Availability(available_hours_per_week=40, current_assigned_hours=40))
    assert classify_member_rejection(_task(), member) == ["NO_AVAILABILITY"]


def test_classify_overloaded_task_as_workload_too_high():
    member = _member(availability=Availability(available_hours_per_week=40, current_assigned_hours=35))
    task = _task(estimated_hours=10)  # 残り5hに対して10h
    assert classify_member_rejection(task, member) == ["WORKLOAD_TOO_HIGH"]


def test_classify_scope_restriction_as_hard_constraint():
    member = _member(constraints=[Constraint(type="scope_restriction", value="backend")])
    task = _task(domain="frontend")
    assert classify_member_rejection(task, member) == ["HARD_CONSTRAINT"]


def test_classify_member_can_have_multiple_codes():
    member = _member(
        skills=[Skill(skill="Go", level=5)],
        availability=Availability(available_hours_per_week=40, current_assigned_hours=40),
    )
    codes = classify_member_rejection(_task(), member)
    assert set(codes) == {"NO_REQUIRED_SKILL", "NO_AVAILABILITY"}


def test_classify_member_meeting_all_constraints_has_no_codes():
    assert classify_member_rejection(_task(), _member()) == []


# --- determine_unassigned_reason ---

def test_no_members_is_no_candidate():
    assert determine_unassigned_reason(_task(), [], []) == "NO_CANDIDATE"


def test_all_rejected_for_skill_is_no_required_skill():
    member = _member(skills=[Skill(skill="Go", level=5)])
    rejections = [CandidateRejection(member_id=member.id, reasons=["必要スキル'Python'を持っていません"])]
    assert determine_unassigned_reason(_task(), [member], rejections) == "NO_REQUIRED_SKILL"


def test_all_rejected_for_availability_is_no_availability():
    member = _member(availability=Availability(available_hours_per_week=40, current_assigned_hours=40))
    rejections = [CandidateRejection(member_id=member.id, reasons=["現在、稼働可能な残りキャパシティがありません（unavailable）"])]
    assert determine_unassigned_reason(_task(), [member], rejections) == "NO_AVAILABILITY"


def test_dominant_reason_wins_when_mixed():
    m1 = _member(id="M-001", skills=[Skill(skill="Go", level=5)])
    m2 = _member(id="M-002", skills=[Skill(skill="Rust", level=5)])
    m3 = _member(id="M-003", availability=Availability(available_hours_per_week=40, current_assigned_hours=40))
    rejections = [
        CandidateRejection(member_id="M-001", reasons=["必要スキル'Python'を持っていません"]),
        CandidateRejection(member_id="M-002", reasons=["必要スキル'Python'を持っていません"]),
        CandidateRejection(member_id="M-003", reasons=["現在、稼働可能な残りキャパシティがありません（unavailable）"]),
    ]
    # 2件 vs 1件 → NO_REQUIRED_SKILLが優勢
    assert determine_unassigned_reason(_task(), [m1, m2, m3], rejections) == "NO_REQUIRED_SKILL"


def test_member_load_errors_flagged_as_invalid_member_data():
    """メンバーは渡されたが、除外理由が1件も無い（読み込みエラーで実質空だった）場合"""
    member = _member()
    assert determine_unassigned_reason(
        _task(), [member], [], member_load_errors=True,
    ) == "INVALID_MEMBER_DATA"


def test_rejection_referencing_unknown_member_id_does_not_crash():
    rejections = [CandidateRejection(member_id="GHOST", reasons=["何か"])]
    # membersに存在しないmember_idを参照しているため分類できず、UNKNOWNへ
    assert determine_unassigned_reason(_task(), [_member()], rejections) == "UNKNOWN"


# --- summarize_assignment_audit ---

def _final_assignment(task_id, assigned_member_id, status="recommended", unassigned_reason=None) -> FinalAssignment:
    return FinalAssignment(
        task_id=task_id,
        assigned_member_id=assigned_member_id,
        decided_by="ai",
        ai_recommendation=AssignmentResult(
            task_id=task_id,
            recommended_member_id=assigned_member_id,
            status=status,
            unassigned_reason=unassigned_reason,
        ),
    )


def test_summarize_counts_total_assigned_unassigned_and_success_rate():
    assignments = [
        _final_assignment("T-1", "M-001"),
        _final_assignment("T-2", "M-002"),
        _final_assignment("T-3", None, status="no_suitable_member", unassigned_reason="NO_REQUIRED_SKILL"),
        _final_assignment("T-4", None, status="no_suitable_member", unassigned_reason="NO_AVAILABILITY"),
    ]
    summary = summarize_assignment_audit(assignments)
    assert summary.total_tasks == 4
    assert summary.assigned_tasks == 2
    assert summary.unassigned_tasks == 2
    assert summary.success_rate == 50.0
    assert summary.unassigned_by_reason == {"NO_REQUIRED_SKILL": 1, "NO_AVAILABILITY": 1}


def test_summarize_empty_list_does_not_crash():
    summary = summarize_assignment_audit([])
    assert summary.total_tasks == 0
    assert summary.success_rate == 0.0
    assert summary.unassigned_by_reason == {}


def test_summarize_missing_unassigned_reason_falls_back_to_unknown_not_fabricated():
    assignments = [_final_assignment("T-1", None, status="no_suitable_member", unassigned_reason=None)]
    summary = summarize_assignment_audit(assignments)
    assert summary.unassigned_by_reason == {"UNKNOWN": 1}
