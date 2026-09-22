# backend/pipeline/validation/schema.py
"""
Phase 8の出力データ構造。依頼のRESULT節のJSON形状
(valid/missing_requirements/duplicate_tasks/dependency_errors/
workload_warnings/skill_mismatches/constraint_violations)と1対1で対応する。

各リストの要素は生の文字列ではなく、追跡・表示に必要な情報を持った
構造化オブジェクトにしている（フロントエンドがそのまま表示できるように）。
"""

from __future__ import annotations

from typing import List, Literal, Optional

from pydantic import BaseModel, Field


class MissingRequirement(BaseModel):
    """CHECK 1: 対応するタスクが1つも無い要求"""

    requirement_id: str
    message: str


class DuplicateTaskGroup(BaseModel):
    """CHECK 2: 重複の疑いがあるタスクの組。削除はしない（レビュー対象として保持する）"""

    task_ids: List[str]
    similarity: float
    method: Literal["rule", "llm", "hybrid"]
    reason: str


class DependencyError(BaseModel):
    """CHECK 3: 依存関係グラフの問題"""

    code: str
    message: str
    task_ids: List[str] = Field(default_factory=list)


class WorkloadSummary(BaseModel):
    """CHECK 4: メンバーごとの稼働状況（問題が無い場合も含めて全員分）"""

    member_id: str
    assigned_hours: float
    available_hours: float
    remaining_capacity: float
    workload_percentage: float


class WorkloadWarning(BaseModel):
    """CHECK 4: 過負荷など、稼働状況に関する警告"""

    member_id: str
    assigned_hours: float
    available_hours: float
    remaining_capacity: float
    workload_percentage: float
    code: str
    message: str


class SkillMismatch(BaseModel):
    """CHECK 5: 必要スキルと担当者のスキルの不一致"""

    task_id: str
    member_id: str
    skill: str
    required_level: int
    member_level: int  # スキル自体を持たない場合は0
    message: str


class ConstraintViolation(BaseModel):
    """CHECK 6: 割り当てがハード制約に違反している"""

    task_id: str
    member_id: str
    code: str
    message: str


class TaskQualityIssue(BaseModel):
    """CHECK 7 (Phase 11 Part 14): タスク単体のデータ品質シグナル
    （Phase 4で検出済みのneeds_review・必要スキル未特定）"""

    task_id: str
    code: str
    message: str


class AssignmentScoreAnomaly(BaseModel):
    """CHECK 8 (Phase 11 Part 14): 実際に割り当てられたメンバーの
    決定的スコアが著しく低い割り当て"""

    task_id: str
    member_id: str
    score: float
    threshold: float
    message: str


class UnassignedTaskIssue(BaseModel):
    """CHECK 9: 担当者を割り当てられなかったタスク。

    `reason`は`backend.pipeline.assignment.audit.UnassignedReason`の
    いずれか（NO_CANDIDATE/HARD_CONSTRAINT/NO_REQUIRED_SKILL/
    NO_AVAILABILITY/WORKLOAD_TOO_HIGH/INVALID_MEMBER_DATA/UNKNOWN）。
    候補ごとの詳細は`{job_id}.assignments.json`の
    `ai_recommendation.rejected_candidates`に既に保持されているため、
    ここでは「一覧性」のためのサマリーとして最小限の情報だけを持つ。
    """

    task_id: str
    reason: str
    message: str


class ValidationReport(BaseModel):
    """依頼のRESULT節に対応する検証結果全体"""

    valid: bool
    missing_requirements: List[MissingRequirement] = Field(default_factory=list)
    duplicate_tasks: List[DuplicateTaskGroup] = Field(default_factory=list)
    dependency_errors: List[DependencyError] = Field(default_factory=list)
    workload_warnings: List[WorkloadWarning] = Field(default_factory=list)
    skill_mismatches: List[SkillMismatch] = Field(default_factory=list)
    constraint_violations: List[ConstraintViolation] = Field(default_factory=list)

    # Phase 11 Part 14で追加（CHECK 7/8）。既存フィールドは変更しない
    # （Part 20: 後方互換な追加のみ行う）。
    task_quality_issues: List[TaskQualityIssue] = Field(default_factory=list)
    assignment_score_anomalies: List[AssignmentScoreAnomaly] = Field(default_factory=list)

    # CHECK 9（Assignment未割当問題の調査で追加）。既存フィールドは変更しない。
    unassigned_tasks: List[UnassignedTaskIssue] = Field(default_factory=list)

    # 依頼のRESULT節には無いが、フロントエンドが全メンバーの稼働状況を
    # 表示するために有用な補足情報（問題の有無にかかわらず全員分を含む）
    workload_summaries: List[WorkloadSummary] = Field(default_factory=list)
    generated_at: Optional[str] = Field(None, description="ISO8601形式の生成時刻(UTC)")
