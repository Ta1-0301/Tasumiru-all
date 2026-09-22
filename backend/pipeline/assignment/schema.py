# backend/pipeline/assignment/schema.py
"""
Phase 7のデータ構造。

`Member`（スキル・稼働状況・制約）はPhase 6(`backend.pipeline.members.schema`)
のものをそのまま再利用する。タスク側は、Phase 4の`Task`とは独立した、
このフェーズが必要とする最小限の`AssignmentTask`を定義する
（必要スキルの"レベル"はPhase 4のTaskには無いため）。
"""

from __future__ import annotations

from typing import List, Literal, Optional

from pydantic import BaseModel, Field

from backend.pipeline.requirements.schema import Priority

MIN_SKILL_LEVEL = 1
MAX_SKILL_LEVEL = 5


class RequiredSkill(BaseModel):
    """タスクが要求するスキルと、その最低習熟度"""

    skill: str
    min_level: int = MIN_SKILL_LEVEL  # 1(Beginner) - 5(Expert)


class AssignmentTask(BaseModel):
    """タスクアサインの入力となるタスク情報"""

    task_id: str
    title: str = ""
    required_skills: List[RequiredSkill] = Field(default_factory=list)
    estimated_hours: Optional[float] = None
    priority: Priority = "unknown"
    domain: Optional[str] = Field(
        None,
        description=(
            "scope_restriction制約と比較する対象領域（例: 'frontend'）。"
            "未設定なら、この種の制約はこのタスクには適用されない。"
        ),
    )
    dependencies: List[str] = Field(
        default_factory=list, description="このタスクの前提となるタスクIDの一覧"
    )


class ScoringWeights(BaseModel):
    """Step 2のスコアリング重み。

    依頼のSTEP 2の例をデフォルト値として持つ。**アプリケーション内の
    どこにもこの数値をコピー&ペーストしないこと** —
    重みを変えたい場合は必ずこのクラスのインスタンスを差し替えて渡す。

    `skill_similarity`（Phase 11で追加、TF-IDF cosine類似度ベース）の
    既定値は意図的に0.0にしている。Phase 7時点の`skill_match`（レベルベース、
    正規化後の完全一致）は既にテスト済み・本番実績のある指標であり、
    実データでの効果測定を行わずに既定の本番挙動を変えることは
    Phase 10で確立した「測定なしに最適化しない」方針に反するため。
    有効にするには、呼び出し側が明示的にこの重みを設定する
    （例: `ScoringWeights(skill_similarity=0.15, ...)`）。
    """

    skill_match: float = 0.50
    workload: float = 0.20
    experience: float = 0.20
    availability: float = 0.10
    skill_similarity: float = 0.0

    def normalized(self) -> "ScoringWeights":
        """合計が1.0になるように正規化した重みを返す（合計が1.0でなくても
        最終スコアが0-100の範囲に収まるようにするため）。"""
        total = (
            self.skill_match + self.workload + self.experience
            + self.availability + self.skill_similarity
        )
        if total <= 0:
            raise ValueError("重みの合計が0以下です")
        return ScoringWeights(
            skill_match=self.skill_match / total,
            workload=self.workload / total,
            experience=self.experience / total,
            availability=self.availability / total,
            skill_similarity=self.skill_similarity / total,
        )


class CandidateRejection(BaseModel):
    """Step 1で除外された候補者とその理由"""

    member_id: str
    reasons: List[str]


class CandidateScore(BaseModel):
    """Step 2で計算された、1候補者のスコア明細（0-1の内訳 + 0-100の最終スコア）"""

    member_id: str
    skill_match: float
    workload_score: float
    experience_score: float
    availability_score: float
    skill_similarity: float = 0.0
    score: float


class AssignmentResult(BaseModel):
    """タスクアサインの推薦結果（AIの推薦。人間の最終決定とは別に保持する）"""

    task_id: str
    recommended_member_id: Optional[str] = None
    score: Optional[float] = None
    candidate_scores: List[CandidateScore] = Field(default_factory=list)
    rejected_candidates: List[CandidateRejection] = Field(default_factory=list)
    reasons: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    status: Literal["recommended", "no_suitable_member"]
    # Assignment Audit（既定はOFF、Noneのまま）: 未割当タスクの代表理由。
    # "recommended"の場合は常にNone（既存の挙動を一切変えない）。
    unassigned_reason: Optional[str] = None


class FinalAssignment(BaseModel):
    """人間による最終的な割り当て決定。

    `ai_recommendation`にAIの推薦をそのまま保持することで、
    「AIの推薦」と「最終的な人間の割り当て」を常に分離して追跡できる。
    """

    task_id: str
    assigned_member_id: Optional[str] = None
    decided_by: Literal["ai", "human"]
    overridden: bool = False
    override_reason: Optional[str] = None
    ai_recommendation: AssignmentResult
