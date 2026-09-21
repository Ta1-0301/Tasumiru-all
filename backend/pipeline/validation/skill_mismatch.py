# backend/pipeline/validation/skill_mismatch.py
"""
CHECK 5: Skill Mismatch。

完全に決定的（LLM不使用）。タスクの必要スキルと、割り当てられたメンバーの
スキルを比較する。

Phase 4の`Task.required_skills`はスキル名の文字列一覧のみで、要求レベルを
持たない。より厳密な最低レベルの情報がある場合（例: Phase 7で使う
`RequiredSkill`）は`required_skill_levels`引数で渡せる。渡されなければ
「レベル1(Beginner)以上でそのスキルを持っていればよい」という最も緩い
既定値にフォールバックする（無い情報を捏造しない）。
"""

from __future__ import annotations

from typing import Dict, List, Optional

from backend.pipeline.assignment.schema import RequiredSkill
from backend.pipeline.members.schema import Member
from backend.pipeline.tasks.schema import Task
from backend.pipeline.validation.schema import SkillMismatch
from backend.services.skill_normalization import normalize_skill_name

UNKNOWN_SKILL_SENTINEL = "unknown"


def default_required_skills(task: Task) -> List[RequiredSkill]:
    """Task.required_skills（文字列一覧）から、要求レベル1のRequiredSkillを
    機械的に組み立てる（'unknown'という明示的な非申告は要求として扱わない）。
    """
    return [
        RequiredSkill(skill=s, min_level=1)
        for s in (task.required_skills or [])
        if s and s.strip().lower() != UNKNOWN_SKILL_SENTINEL
    ]


def check_skill_mismatches(
    tasks: List[Task],
    members: List[Member],
    assignments: Dict[str, str],
    required_skill_levels: Optional[Dict[str, List[RequiredSkill]]] = None,
) -> List[SkillMismatch]:
    member_by_id = {m.id: m for m in members}
    mismatches: List[SkillMismatch] = []

    for t in tasks:
        member_id = assignments.get(t.id)
        if member_id is None:
            continue
        member = member_by_id.get(member_id)
        if member is None:
            continue  # 存在しないメンバーへの割り当てはCHECK 6が扱う

        required = (required_skill_levels or {}).get(t.id)
        if required is None:
            required = default_required_skills(t)

        member_skills = {normalize_skill_name(s.skill): s.level for s in member.skills}

        for req in required:
            level = member_skills.get(normalize_skill_name(req.skill))
            if level is None:
                mismatches.append(SkillMismatch(
                    task_id=t.id, member_id=member_id, skill=req.skill,
                    required_level=req.min_level, member_level=0,
                    message=f"{member.name}は必要スキル'{req.skill}'を持っていません",
                ))
            elif level < req.min_level:
                mismatches.append(SkillMismatch(
                    task_id=t.id, member_id=member_id, skill=req.skill,
                    required_level=req.min_level, member_level=level,
                    message=(
                        f"{member.name}のスキル'{req.skill}'はレベル{level}で、"
                        f"要求レベル{req.min_level}に届きません"
                    ),
                ))

    return mismatches
