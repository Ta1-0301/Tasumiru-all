# backend/tests/test_assignment_override.py
"""backend/pipeline/assignment/override.py の単体テスト（Human Override）。"""

from backend.pipeline.assignment.override import accept_recommendation, override_recommendation
from backend.pipeline.assignment.schema import AssignmentResult, CandidateScore


def _recommendation(status="recommended", recommended_member_id="M-001", score=91.0):
    return AssignmentResult(
        task_id="TASK-001",
        recommended_member_id=recommended_member_id if status == "recommended" else None,
        score=score if status == "recommended" else None,
        candidate_scores=[
            CandidateScore(member_id="M-001", skill_match=1, workload_score=1, experience_score=1, availability_score=1, score=91.0)
        ] if status == "recommended" else [],
        status=status,
    )


def test_accept_recommendation_keeps_ai_choice():
    rec = _recommendation()
    final = accept_recommendation(rec)
    assert final.assigned_member_id == "M-001"
    assert final.decided_by == "ai"
    assert final.overridden is False
    assert final.ai_recommendation is rec


def test_override_recommendation_with_different_member_is_marked_overridden():
    rec = _recommendation()
    final = override_recommendation(rec, "M-002", "M-002の方が経験豊富")
    assert final.assigned_member_id == "M-002"
    assert final.decided_by == "human"
    assert final.overridden is True
    assert final.override_reason == "M-002の方が経験豊富"


def test_override_recommendation_confirming_same_member_is_not_marked_overridden():
    rec = _recommendation()
    final = override_recommendation(rec, "M-001", "AIの推薦を確認・承認")
    assert final.assigned_member_id == "M-001"
    assert final.decided_by == "human"
    assert final.overridden is False


def test_override_recommendation_can_force_assign_when_no_suitable_member():
    """AIが候補者無しと判断しても、人間は明示的に誰かを割り当てられる
    （AIはハード制約を回避できないが、人間の最終決定は制限しない）"""
    rec = _recommendation(status="no_suitable_member")
    final = override_recommendation(rec, "M-005", "緊急対応のため経験の浅いメンバーを割り当てる")
    assert final.assigned_member_id == "M-005"
    assert final.overridden is True
    assert final.ai_recommendation.status == "no_suitable_member"


def test_override_recommendation_can_explicitly_leave_unassigned():
    rec = _recommendation()
    final = override_recommendation(rec, None, "今回は見送り")
    assert final.assigned_member_id is None
    assert final.overridden is True


def test_ai_recommendation_is_never_mutated_by_override():
    """AIの推薦と人間の最終決定は常に分離して保持される"""
    rec = _recommendation()
    original_member_id = rec.recommended_member_id
    override_recommendation(rec, "M-999", "変更")
    assert rec.recommended_member_id == original_member_id  # 元のAssignmentResultは不変
