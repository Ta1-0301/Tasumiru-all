# backend/pipeline/assignment/filters.py
"""
Step 1: Candidate Filtering。

完全に決定的（LLM不使用）。ハード制約に違反するメンバーを除外する。
依頼のExamplesと1対1で対応する4種類のチェック:

  - insufficient required skill      -> check_skill_requirements
  - unavailable                      -> check_availability
  - workload exceeds maximum         -> check_workload
  - explicit assignment restriction  -> check_explicit_constraints

LLMはこのステップに一切関与しない。ここで除外された候補者は、
Step 2（スコアリング）・Step 3（LLMの補足説明）のどちらにも渡されない
——「LLMはハード制約を回避できない」という要件の構造的な保証。
"""

from __future__ import annotations

from typing import List, Tuple

from backend.pipeline.assignment.schema import AssignmentTask, CandidateRejection
from backend.pipeline.members.schema import Member
from backend.services.skill_normalization import normalize_skill_name


def _find_member_skill(member: Member, skill_name: str):
    """スキル名の表記ゆれ（Part 6: "Python3"→"python"等）を吸収した上で、
    メンバーが持つ完全一致のスキルを探す。あくまで決定的な正規化後の
    完全一致であり、意味的に異なるスキル同士を似ていると判定すること
    （TF-IDFによる曖昧一致）はハード制約の判定には使わない
    ——`backend.services.skill_normalization`のdocstring参照。
    """
    target = normalize_skill_name(skill_name)
    for s in member.skills:
        if normalize_skill_name(s.skill) == target:
            return s
    return None


def check_skill_requirements(task: AssignmentTask, member: Member) -> List[str]:
    """必要スキルを、要求されたレベル以上で持っているかを確認する"""
    reasons: List[str] = []
    for req in task.required_skills:
        skill = _find_member_skill(member, req.skill)
        if skill is None:
            reasons.append(f"必要スキル'{req.skill}'を持っていません")
        elif skill.level < req.min_level:
            reasons.append(
                f"必要スキル'{req.skill}'のレベルが不足しています"
                f"（要求レベル{req.min_level}に対し、現在レベル{skill.level}）"
            )
    return reasons


def check_availability(task: AssignmentTask, member: Member) -> List[str]:
    """メンバーが現在、新しいタスクを受けられる残りキャパシティを持っているかを確認する"""
    if member.availability.remaining_capacity <= 0:
        return ["現在、稼働可能な残りキャパシティがありません（unavailable）"]
    return []


def check_workload(task: AssignmentTask, member: Member) -> List[str]:
    """このタスクの見積り工数が、メンバーの残りキャパシティを超えないかを確認する。

    `check_availability`が既に「残りキャパシティが無い」ケースを検出するため、
    ここでは「残りキャパシティはあるが、このタスク単体では収まらない」ケースを
    区別して報告する。
    """
    remaining = member.availability.remaining_capacity
    if remaining <= 0 or task.estimated_hours is None:
        return []
    if task.estimated_hours > remaining:
        return [
            f"このタスクの見積り工数({task.estimated_hours}h)が"
            f"残りキャパシティ({remaining}h)を超えています（workload exceeds maximum）"
        ]
    return []


def check_explicit_constraints(task: AssignmentTask, member: Member) -> List[str]:
    """メンバーの明示的な制約(Constraint)に違反しないかを確認する。

    - scope_restriction: タスクのdomainが指定されており、制約の対象領域と
      一致しない場合に違反とする（domain未設定のタスクには適用しない）。
    - max_hours_per_week: このタスクを加えた場合の週あたり合計工数が
      制約の上限を超える場合に違反とする。
    - day_unavailable: このフェーズのAssignmentTaskは特定の日付を持たない
      ため判定できない（既知の限界。README参照）。
    - requires_review: ハード制約ではない（レビューが必要というだけで、
      アサイン自体は可能）。ソフトな注意事項として`runner.py`が警告に変換する。
    """
    reasons: List[str] = []
    for c in member.constraints:
        if c.type == "scope_restriction":
            if task.domain and c.value and c.value.strip().lower() != task.domain.strip().lower():
                reasons.append(
                    f"対象領域の制約に違反します（'{c.value}'のみ対応可能、タスクの領域は'{task.domain}'）"
                )
        elif c.type == "max_hours_per_week":
            if c.max_hours is not None and task.estimated_hours is not None:
                projected = member.availability.current_assigned_hours + task.estimated_hours
                if projected > c.max_hours:
                    reasons.append(
                        f"週あたり工数上限({c.max_hours}h)を超えます"
                        f"（現在{member.availability.current_assigned_hours}h + "
                        f"このタスク{task.estimated_hours}h = {projected}h）"
                    )
    return reasons


def filter_candidates(
    task: AssignmentTask, members: List[Member]
) -> Tuple[List[Member], List[CandidateRejection]]:
    """Step 1: ハード制約に違反するメンバーを除外し、(生存者, 除外者)を返す"""
    survivors: List[Member] = []
    rejections: List[CandidateRejection] = []

    for m in members:
        reasons = (
            check_skill_requirements(task, m)
            + check_availability(task, m)
            + check_workload(task, m)
            + check_explicit_constraints(task, m)
        )
        if reasons:
            rejections.append(CandidateRejection(member_id=m.id, reasons=reasons))
        else:
            survivors.append(m)

    return survivors, rejections
