# backend/tests/test_validation_score_anomaly.py
"""backend/pipeline/validation/score_anomaly.py の単体テスト（CHECK 8、決定的）。"""

from backend.pipeline.assignment.schema import AssignmentResult, CandidateScore, FinalAssignment
from backend.pipeline.validation.score_anomaly import check_assignment_score_anomalies


def _candidate(member_id, score):
    return CandidateScore(
        member_id=member_id, skill_match=0.5, workload_score=0.5,
        experience_score=0.5, availability_score=0.5, score=score,
    )


def _final_assignment(task_id, assigned_member_id, candidate_scores, recommended_member_id=None, decided_by="ai"):
    return FinalAssignment(
        task_id=task_id,
        assigned_member_id=assigned_member_id,
        decided_by=decided_by,
        ai_recommendation=AssignmentResult(
            task_id=task_id,
            recommended_member_id=recommended_member_id or (candidate_scores[0].member_id if candidate_scores else None),
            score=candidate_scores[0].score if candidate_scores else None,
            candidate_scores=candidate_scores,
            status="recommended" if candidate_scores else "no_suitable_member",
        ),
    )


def test_low_score_assignment_is_flagged():
    fa = _final_assignment("TASK-001", "M-1", [_candidate("M-1", 25.0)])
    anomalies = check_assignment_score_anomalies([fa], threshold=40.0)
    assert len(anomalies) == 1
    assert anomalies[0].member_id == "M-1"
    assert anomalies[0].score == 25.0


def test_high_score_assignment_is_not_flagged():
    fa = _final_assignment("TASK-001", "M-1", [_candidate("M-1", 90.0)])
    anomalies = check_assignment_score_anomalies([fa], threshold=40.0)
    assert anomalies == []


def test_uses_the_assigned_members_score_not_the_ai_recommendations_top_score():
    """Human overrideで、AIの推薦(M-1, 90点)ではなくM-2(スコア20点)が
    実際に割り当てられた場合、M-2のスコアで異常判定しなければならない"""
    fa = _final_assignment(
        "TASK-001", assigned_member_id="M-2",
        candidate_scores=[_candidate("M-1", 90.0), _candidate("M-2", 20.0)],
        recommended_member_id="M-1", decided_by="human",
    )
    anomalies = check_assignment_score_anomalies([fa], threshold=40.0)
    assert len(anomalies) == 1
    assert anomalies[0].member_id == "M-2"
    assert anomalies[0].score == 20.0


def test_unassigned_member_id_not_in_candidate_scores_is_not_fabricated():
    """人間が候補者一覧に無い誰かを割り当てた場合、スコアが無いので
    捏造せず何も報告しない（ハード制約違反ならCHECK 6が別途検出する）"""
    fa = _final_assignment(
        "TASK-001", assigned_member_id="M-999",
        candidate_scores=[_candidate("M-1", 90.0)],
        recommended_member_id="M-1", decided_by="human",
    )
    anomalies = check_assignment_score_anomalies([fa], threshold=40.0)
    assert anomalies == []


def test_unassigned_task_is_skipped():
    fa = FinalAssignment(
        task_id="TASK-001", assigned_member_id=None, decided_by="ai",
        ai_recommendation=AssignmentResult(task_id="TASK-001", status="no_suitable_member"),
    )
    anomalies = check_assignment_score_anomalies([fa])
    assert anomalies == []


def test_empty_list_returns_empty():
    assert check_assignment_score_anomalies([]) == []
