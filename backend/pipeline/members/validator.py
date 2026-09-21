# backend/pipeline/members/validator.py
"""
Stage: Member Validation。

完全に決定的（LLM不使用）。同じ入力に対して常に同じ結果になる。
検出対象は依頼の5項目:
  - invalid skill levels
  - negative hours
  - workload above capacity
  - duplicate skills
  - invalid constraints

いずれの関数も、無効なデータを書き換えたりしない。`ValidationIssue`として
問題点を報告するだけ（呼び出し側がレビュー対象として扱う）。
"""

from __future__ import annotations

from collections import Counter
from typing import List

from backend.pipeline.members.schema import CONSTRAINT_TYPES, Member, ValidationIssue, WEEKDAYS

MIN_SKILL_LEVEL = 1
MAX_SKILL_LEVEL = 5


def check_invalid_skill_levels(members: List[Member]) -> List[ValidationIssue]:
    """スキルレベルが1(Beginner)〜5(Expert)の範囲外の場合を検出する"""
    issues: List[ValidationIssue] = []
    for m in members:
        for s in m.skills:
            if not isinstance(s.level, int) or not (MIN_SKILL_LEVEL <= s.level <= MAX_SKILL_LEVEL):
                issues.append(ValidationIssue(
                    code="INVALID_SKILL_LEVEL",
                    message=f"スキル'{s.skill}'のlevelが範囲外です（1-5である必要があります）: {s.level!r}",
                    member_id=m.id,
                ))
    return issues


def check_negative_hours(members: List[Member]) -> List[ValidationIssue]:
    """稼働可能時間・現在の割当時間・スキル経験年数・工数上限のいずれかが負の値の場合を検出する"""
    issues: List[ValidationIssue] = []
    for m in members:
        a = m.availability
        if a.available_hours_per_week < 0:
            issues.append(ValidationIssue(
                code="NEGATIVE_HOURS",
                message=f"available_hours_per_weekが負の値です: {a.available_hours_per_week}",
                member_id=m.id,
            ))
        if a.current_assigned_hours < 0:
            issues.append(ValidationIssue(
                code="NEGATIVE_HOURS",
                message=f"current_assigned_hoursが負の値です: {a.current_assigned_hours}",
                member_id=m.id,
            ))
        for s in m.skills:
            if s.experience_years is not None and s.experience_years < 0:
                issues.append(ValidationIssue(
                    code="NEGATIVE_HOURS",
                    message=f"スキル'{s.skill}'のexperience_yearsが負の値です: {s.experience_years}",
                    member_id=m.id,
                ))
        if m.experience_years is not None and m.experience_years < 0:
            issues.append(ValidationIssue(
                code="NEGATIVE_HOURS",
                message=f"experience_yearsが負の値です: {m.experience_years}",
                member_id=m.id,
            ))
        for c in m.constraints:
            if c.max_hours is not None and c.max_hours < 0:
                issues.append(ValidationIssue(
                    code="NEGATIVE_HOURS",
                    message=f"制約のmax_hoursが負の値です: {c.max_hours}",
                    member_id=m.id,
                ))
    return issues


def check_workload_above_capacity(members: List[Member]) -> List[ValidationIssue]:
    """現在の割当時間が稼働可能時間を超えている（残りキャパシティが負になる）場合を検出する。

    「決して負のキャパシティを許容しない」という要件はこのチェックで実現する:
    `Availability.remaining_capacity`はマイナス値を計算上返し得るが、その状態は
    常にここで検証エラーとして検出される（黙って0にクランプしたりしない）。
    """
    issues: List[ValidationIssue] = []
    for m in members:
        if m.availability.remaining_capacity < 0:
            issues.append(ValidationIssue(
                code="WORKLOAD_ABOVE_CAPACITY",
                message=(
                    f"現在の割当時間({m.availability.current_assigned_hours})が"
                    f"稼働可能時間({m.availability.available_hours_per_week})を超えています"
                ),
                member_id=m.id,
            ))
    return issues


def check_duplicate_skills(members: List[Member]) -> List[ValidationIssue]:
    """同一メンバーのスキル一覧に、同じスキル名（大文字小文字を無視）が複数回登場する場合を検出する"""
    issues: List[ValidationIssue] = []
    for m in members:
        counts = Counter(s.skill.strip().lower() for s in m.skills if s.skill)
        for skill_name, count in counts.items():
            if count > 1:
                issues.append(ValidationIssue(
                    code="DUPLICATE_SKILL",
                    message=f"スキル'{skill_name}'が{count}回重複して登録されています",
                    member_id=m.id,
                ))
    return issues


def check_invalid_constraints(members: List[Member]) -> List[ValidationIssue]:
    """制約が構造として妥当かを検証する（typeごとに必要な情報が揃っているか）"""
    issues: List[ValidationIssue] = []
    for m in members:
        for c in m.constraints:
            if c.type not in CONSTRAINT_TYPES:
                issues.append(ValidationIssue(
                    code="INVALID_CONSTRAINT",
                    message=f"未知の制約種別です: {c.type!r}",
                    member_id=m.id,
                ))
                continue

            if c.type == "day_unavailable" and (not c.value or c.value not in WEEKDAYS):
                issues.append(ValidationIssue(
                    code="INVALID_CONSTRAINT",
                    message=f"day_unavailable制約のvalueが妥当な曜日名ではありません: {c.value!r}",
                    member_id=m.id,
                ))
            elif c.type == "max_hours_per_week" and (c.max_hours is None or c.max_hours < 0):
                issues.append(ValidationIssue(
                    code="INVALID_CONSTRAINT",
                    message=f"max_hours_per_week制約のmax_hoursが不正です: {c.max_hours!r}",
                    member_id=m.id,
                ))
            elif c.type == "scope_restriction" and (not c.value or not c.value.strip()):
                issues.append(ValidationIssue(
                    code="INVALID_CONSTRAINT",
                    message="scope_restriction制約のvalueが空です",
                    member_id=m.id,
                ))
            elif c.type == "requires_review" and (not c.value or not c.value.strip()):
                issues.append(ValidationIssue(
                    code="INVALID_CONSTRAINT",
                    message="requires_review制約のvalue（レビュー要件の説明）が空です",
                    member_id=m.id,
                ))
    return issues


def validate_members(members: List[Member]) -> List[ValidationIssue]:
    """依頼された5種類の検証すべてを実行し、検出された問題点を1つのリストにまとめる"""
    issues: List[ValidationIssue] = []
    issues += check_invalid_skill_levels(members)
    issues += check_negative_hours(members)
    issues += check_workload_above_capacity(members)
    issues += check_duplicate_skills(members)
    issues += check_invalid_constraints(members)
    return issues
