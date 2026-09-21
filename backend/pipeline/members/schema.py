# backend/pipeline/members/schema.py
"""
Phase 6のデータ構造（members.json）。

設計方針:
  数値・文字列フィールドの多くは、あえてPydanticレベルでは緩く型付けする
  （負数や範囲外の値もいったん構築できる）。これは
  `backend/pipeline/tasks/schema.py`の`estimated_hours`と同じ方針で、
  「スキーマが黙って弾く／直す」のではなく、`validator.py`の各チェック関数が
  意味のある検証結果（`ValidationIssue`）として明示的に報告できるようにする
  ため。取り込んだ生データ（人手入力・マネージャー入力・外部データ・
  過去の確定データ）をそのまま保持しつつ、問題点だけを別途可視化する。
"""

from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field

# スキルレベルの語彙（依頼のSKILL節に定義された固定語彙）
SKILL_LEVEL_NAMES = {
    1: "Beginner",
    2: "Basic",
    3: "Intermediate",
    4: "Advanced",
    5: "Expert",
}

WEEKDAYS = [
    "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday",
]

CONSTRAINT_TYPES = [
    "scope_restriction",   # 例: frontend only / backend only
    "day_unavailable",     # 例: unavailable Monday
    "max_hours_per_week",  # 例: cannot work more than 8 hours/week
    "requires_review",     # 例: requires review by senior member
]


class Skill(BaseModel):
    """1つのスキルとその習熟度"""

    skill: str
    level: int  # 1(Beginner) - 5(Expert)。範囲チェックはvalidator.pyが行う
    experience_years: Optional[float] = None


class Availability(BaseModel):
    """稼働可能時間・稼働日・現在の割当状況"""

    available_hours_per_week: float
    working_days: List[str] = Field(default_factory=list)
    current_assigned_hours: float = 0.0

    @property
    def remaining_capacity(self) -> float:
        """残り稼働可能時間。

        負数になり得る生の計算値をそのまま返す（隠さない）。
        「決して負の残余キャパシティを許容しない」という要件は、この値を
        黙って0にクランプすることではなく、`validator.check_workload_above_capacity`
        がその状態を明示的な検証エラーとして常に検出することで満たす。
        """
        return self.available_hours_per_week - self.current_assigned_hours


class Constraint(BaseModel):
    """構造化された制約条件（自由記述の文字列ではない）

    typeに応じて意味のあるフィールドが変わる:
      - scope_restriction  : value に対象範囲（例: "frontend"）
      - day_unavailable    : value に曜日名（例: "Monday"）
      - max_hours_per_week : max_hours に週あたりの上限時間
      - requires_review    : value にレビュー要件の説明（例: "senior member"）
    """

    type: str
    value: Optional[str] = None
    max_hours: Optional[float] = None


class Member(BaseModel):
    """タスクアサインの対象となる、構造化されたメンバー情報"""

    id: str
    name: str
    skills: List[Skill] = Field(default_factory=list)
    experience_years: Optional[float] = Field(
        None, description="全体的な業務経験年数（個々のスキルのexperience_yearsとは別）"
    )
    availability: Availability
    constraints: List[Constraint] = Field(default_factory=list)


class ValidationIssue(BaseModel):
    """Member Validationステージが検出した問題点"""

    code: str
    message: str
    member_id: Optional[str] = None


class MemberDirectory(BaseModel):
    """members.json の全体（1チーム分のメンバー一覧）"""

    team_id: Optional[str] = None
    members: List[Member]
    issues: List[ValidationIssue] = Field(default_factory=list)
    updated_at: Optional[str] = Field(None, description="ISO8601形式の更新時刻(UTC)")
