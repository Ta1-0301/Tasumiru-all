# backend/pipeline/assignment/scoring.py
"""
Step 2: Scoring。

完全に決定的（LLM不使用）。依頼の例の重み(skill_match*0.50 + workload*0.20 +
experience*0.20 + availability*0.10)を`ScoringWeights`のデフォルト値として
実装し、呼び出し側が差し替えられるようにする。

各コンポーネントの計算方法（採点の根拠を追跡できるようにするため明記する）:

- skill_match       : 各必要スキルについて member_level / 5 の平均。
                       要求レベルをただ満たすだけの候補より、余裕を持って
                       満たす候補を差別化する（"perfect match" vs
                       "partial match"を数値で区別するための設計）。
- workload_score    : このタスクを割り当てた後に残るキャパシティの割合。
                       多く残るほど高得点（無理な詰め込みを避ける）。
- experience_score  : 必要スキルの経験年数（無ければ全体の経験年数、
                       どちらも無ければ中立値0.5。無い情報を捏造しない）。
- availability_score: 稼働可能日数の広さ（週5日を基準に正規化）。
"""

from __future__ import annotations

from typing import List, Optional

from backend.pipeline.assignment.schema import (
    AssignmentTask,
    CandidateScore,
    MAX_SKILL_LEVEL,
    ScoringWeights,
)
from backend.pipeline.members.schema import Member
from backend.services.skill_matching import skill_similarity
from backend.services.skill_normalization import normalize_skill_name

EXPERIENCE_YEARS_CEILING = 5.0
OVERALL_EXPERIENCE_YEARS_CEILING = 10.0
AVAILABILITY_DAYS_CEILING = 5  # 週5日を「稼働可能日数として完全」の基準とする
NEUTRAL_EXPERIENCE_SCORE = 0.5  # 経験年数の情報が無い場合の中立値
CLOSE_SCORE_MARGIN = 2.0  # 上位2候補のスコア差がこの値以下なら「僅差」とみなす


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


def _skills_by_name(member: Member):
    return {normalize_skill_name(s.skill): s for s in member.skills}


def score_skill_match(task: AssignmentTask, member: Member) -> float:
    if not task.required_skills:
        return 1.0

    skills = _skills_by_name(member)
    scores = []
    for req in task.required_skills:
        skill = skills.get(normalize_skill_name(req.skill))
        level = skill.level if skill else 0
        scores.append(_clamp01(level / MAX_SKILL_LEVEL))
    return sum(scores) / len(scores)


def score_skill_similarity(task: AssignmentTask, member: Member) -> float:
    """Part 5/9: TF-IDF cosine類似度による、スキル名集合ベースの補完シグナル。

    `score_skill_match`（要求レベルを満たしているかどうかの厳密な判定）とは
    独立した、別種の情報を捉える。こちらはスキルの"レベル"を見ない
    かわりに、要求スキル一覧とメンバーの保有スキル一覧全体の近さを見る
    ——`score_skill_match`が完全一致（正規化後）でしか拾えない
    「タスクが3つのスキルを要求し、メンバーがそのうち2つを持つ」ような
    部分的な近さも数値化できる。
    """
    return skill_similarity(
        [r.skill for r in task.required_skills],
        [s.skill for s in member.skills],
    )


def score_workload(task: AssignmentTask, member: Member) -> float:
    available = member.availability.available_hours_per_week
    if available <= 0:
        return 0.0
    projected_remaining = member.availability.remaining_capacity - (task.estimated_hours or 0.0)
    return _clamp01(projected_remaining / available)


def score_experience(task: AssignmentTask, member: Member) -> float:
    skills = _skills_by_name(member)
    years: List[float] = []
    for req in task.required_skills:
        skill = skills.get(normalize_skill_name(req.skill))
        if skill and skill.experience_years is not None:
            years.append(skill.experience_years)

    if years:
        return _clamp01((sum(years) / len(years)) / EXPERIENCE_YEARS_CEILING)
    if member.experience_years is not None:
        return _clamp01(member.experience_years / OVERALL_EXPERIENCE_YEARS_CEILING)
    return NEUTRAL_EXPERIENCE_SCORE


def score_availability(member: Member) -> float:
    return _clamp01(len(member.availability.working_days) / AVAILABILITY_DAYS_CEILING)


def score_candidate(
    task: AssignmentTask, member: Member, weights: Optional[ScoringWeights] = None
) -> CandidateScore:
    """1候補者のスコア明細を計算する（final_score = 0-100）"""
    w = (weights or ScoringWeights()).normalized()

    skill_match = score_skill_match(task, member)
    workload_score = score_workload(task, member)
    experience_score = score_experience(task, member)
    availability_score = score_availability(member)
    skill_sim = score_skill_similarity(task, member)

    final = (
        skill_match * w.skill_match
        + workload_score * w.workload
        + experience_score * w.experience
        + availability_score * w.availability
        + skill_sim * w.skill_similarity
    )

    return CandidateScore(
        member_id=member.id,
        skill_match=round(skill_match, 4),
        workload_score=round(workload_score, 4),
        experience_score=round(experience_score, 4),
        availability_score=round(availability_score, 4),
        skill_similarity=round(skill_sim, 4),
        score=round(final * 100, 2),
    )


def score_candidates(
    task: AssignmentTask, members: List[Member], weights: Optional[ScoringWeights] = None
) -> List[CandidateScore]:
    """候補者一覧をスコアリングし、スコアの降順（同点はmember_id昇順）で返す"""
    scored = [score_candidate(task, m, weights) for m in members]
    return sorted(scored, key=lambda c: (-c.score, c.member_id))


def detect_close_scores(
    candidates: List[CandidateScore], margin: float = CLOSE_SCORE_MARGIN
) -> Optional[str]:
    """上位2候補のスコアが僅差の場合、人による確認を促す警告文を返す（無ければNone）。

    "flag ambiguous assignments"という要件を、LLMを使わずに決定的に満たす部分。
    """
    if len(candidates) < 2:
        return None
    top, second = candidates[0], candidates[1]
    if abs(top.score - second.score) <= margin:
        return (
            f"上位候補のスコアが僅差です（{top.member_id}: {top.score}点 / "
            f"{second.member_id}: {second.score}点）。人による確認を推奨します。"
        )
    return None
