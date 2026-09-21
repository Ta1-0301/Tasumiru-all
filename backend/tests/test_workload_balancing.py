# backend/tests/test_workload_balancing.py
"""backend/pipeline/assignment/workload_balancing.py の単体テスト（Part 11、決定的）。"""

from backend.pipeline.assignment.schema import AssignmentTask, CandidateScore, RequiredSkill
from backend.pipeline.assignment.workload_balancing import (
    compute_projected_workload_percentage,
    select_recommended_candidate,
)
from backend.pipeline.members.schema import Availability, Member


def _member(id: str, available_hours=40, current_assigned_hours=0.0) -> Member:
    return Member(
        id=id, name=id, skills=[],
        availability=Availability(available_hours_per_week=available_hours, current_assigned_hours=current_assigned_hours),
    )


def _task(estimated_hours=8) -> AssignmentTask:
    return AssignmentTask(task_id="TASK-001", required_skills=[RequiredSkill(skill="Python")], estimated_hours=estimated_hours)


def _score(member_id: str, score: float) -> CandidateScore:
    return CandidateScore(
        member_id=member_id, skill_match=1.0, workload_score=1.0,
        experience_score=1.0, availability_score=1.0, score=score,
    )


# --- projected workload ---

def test_projected_workload_includes_the_new_task():
    task = _task(estimated_hours=8)
    member = _member("M-1", available_hours=40, current_assigned_hours=10)
    assert compute_projected_workload_percentage(task, member) == 45.0


def test_projected_workload_is_100_when_available_hours_is_zero_and_task_has_hours():
    task = _task(estimated_hours=8)
    member = _member("M-1", available_hours=0, current_assigned_hours=0)
    assert compute_projected_workload_percentage(task, member) == 100.0


def test_projected_workload_is_zero_when_available_hours_is_zero_and_no_hours_assigned():
    task = _task(estimated_hours=None)
    member = _member("M-1", available_hours=0, current_assigned_hours=0)
    assert compute_projected_workload_percentage(task, member) == 0.0


# --- selection: below threshold ---

def test_top_scorer_is_selected_when_under_threshold():
    task = _task(estimated_hours=4)
    members = {"M-1": _member("M-1", 40, 5), "M-2": _member("M-2", 40, 5)}
    scores = [_score("M-1", 90.0), _score("M-2", 80.0)]

    chosen, warnings = select_recommended_candidate(task, scores, members)

    assert chosen.member_id == "M-1"
    assert warnings == []


# --- selection: load balancing (Part 11 worked example) ---

def test_prefers_less_loaded_candidate_when_top_scorer_would_be_overloaded():
    task = _task(estimated_hours=8)
    # Member A: 割当後 95%（過負荷）。Member B: 割当後 40%（余裕あり）
    members = {
        "M-A": _member("M-A", available_hours=40, current_assigned_hours=30),
        "M-B": _member("M-B", available_hours=40, current_assigned_hours=8),
    }
    scores = [_score("M-A", 95.0), _score("M-B", 82.0)]

    chosen, warnings = select_recommended_candidate(task, scores, members)

    assert chosen.member_id == "M-B"
    assert len(warnings) == 1
    assert "M-B" in warnings[0] and "load balancing" in warnings[0]


def test_candidate_scores_list_itself_is_not_reordered_by_selection():
    """`select_recommended_candidate`は`candidate_scores`を書き換えない
    （フロントエンドには常に純粋なスコアランキングを見せる、Part 15）。"""
    task = _task(estimated_hours=8)
    members = {
        "M-A": _member("M-A", available_hours=40, current_assigned_hours=30),
        "M-B": _member("M-B", available_hours=40, current_assigned_hours=8),
    }
    scores = [_score("M-A", 95.0), _score("M-B", 82.0)]
    original_order = [c.member_id for c in scores]

    select_recommended_candidate(task, scores, members)

    assert [c.member_id for c in scores] == original_order


# --- selection: everyone overloaded ---

def test_falls_back_to_top_scorer_with_overload_warning_when_all_exceed_threshold():
    task = _task(estimated_hours=20)
    members = {
        "M-A": _member("M-A", available_hours=40, current_assigned_hours=25),
        "M-B": _member("M-B", available_hours=40, current_assigned_hours=30),
    }
    scores = [_score("M-A", 90.0), _score("M-B", 70.0)]

    chosen, warnings = select_recommended_candidate(task, scores, members)

    assert chosen.member_id == "M-A"
    assert len(warnings) == 1
    assert "過負荷" in warnings[0]


# --- edge cases ---

def test_empty_candidate_list_returns_none():
    chosen, warnings = select_recommended_candidate(_task(), [], {})
    assert chosen is None
    assert warnings == []


def test_single_candidate_over_threshold_is_still_selected_with_warning():
    task = _task(estimated_hours=20)
    members = {"M-1": _member("M-1", available_hours=40, current_assigned_hours=30)}
    scores = [_score("M-1", 90.0)]

    chosen, warnings = select_recommended_candidate(task, scores, members)

    assert chosen.member_id == "M-1"
    assert len(warnings) == 1
