# backend/pipeline/tasks/skill_vocabulary.py
"""
Task生成用の「チームスキル語彙」。

Phase 4のTask生成(decomposer.py)は、これまでチームメンバーが実際に登録して
いるスキル名を一切参照せずに`required_skills`を自由記述させていた。その結果
「API設計」「認証・認可」のような抽象的な語彙と、メンバー側の「Python」
「FastAPI」のような具体的な語彙がずれ、Phase 7のハード制約（正規化後の
完全一致）で候補者が全員除外される(NO_REQUIRED_SKILL)ことが多かった。

ここでは、Phase 6の`Member`一覧（Assignmentで使うのと同じデータ）から、
チーム全員のスキル名を重複なく集めるだけを行う。**LLMは使わない。**

この語彙はTask生成プロンプトに「参考語彙」として渡すだけであり、
担当者の決定・ハード制約の判定（filters.py）には一切使われない。
"""

from __future__ import annotations

from typing import Iterable, List

from backend.pipeline.members.schema import Member
from backend.services.skill_normalization import normalize_skill_name

# プロンプトが過度に長くならないよう、語彙の件数に上限を設ける（出現順で先頭から）。
# チームのスキル数がこれを超えるのは想定外の規模であり、超えた分は参考語彙に
# 含めないだけ（Assignmentの判定には影響しない）。
MAX_TEAM_SKILL_VOCABULARY = 100


def build_team_skill_vocabulary(
    members: Iterable[Member], max_size: int = MAX_TEAM_SKILL_VOCABULARY
) -> List[str]:
    """メンバー全員のスキル名を、重複を除いて出現順に返す。

    重複判定には既存の`normalize_skill_name`（Assignmentのハード制約と同じ
    正規化）を使う。表記ゆれ（例: "Python" と "python3"）は1件にまとめ、
    最初に出現した表記をそのまま残す（語彙の表記をこちらで作り出さない）。
    空のスキル名は無視する。
    """
    vocabulary: List[str] = []
    seen: set = set()
    for member in members:
        for skill in member.skills:
            name = (skill.skill or "").strip()
            if not name:
                continue
            key = normalize_skill_name(name)
            if not key or key in seen:
                continue
            seen.add(key)
            vocabulary.append(name)
            if len(vocabulary) >= max_size:
                return vocabulary
    return vocabulary
