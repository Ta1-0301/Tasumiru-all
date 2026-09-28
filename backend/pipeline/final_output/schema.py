# backend/pipeline/final_output/schema.py
"""
Phase 9の最終出力データ構造。依頼のFINAL JSON節の形状と1対1で対応する。

`requirements`/`tasks`/`dependencies`/`members`/`assignments`は、それぞれ
Phase 3-7の型をそのまま再利用する（このフェーズ独自の再定義はしない
——「新しい情報を生成しない」という方針をスキーマの型そのもので保証する）。
"""

from __future__ import annotations

from datetime import date
from typing import Dict, List, Literal, Optional

from pydantic import BaseModel, Field

from backend.pipeline.assignment.schema import FinalAssignment
from backend.pipeline.dependencies.schema import Dependency
from backend.pipeline.members.schema import Member
from backend.pipeline.requirements.schema import Requirement
from backend.pipeline.tasks.schema import Task
from backend.pipeline.validation.schema import ValidationReport

ValidationStatus = Literal["valid", "warning", "error"]


class ProjectInfo(BaseModel):
    """`project`セクション。仕様書自体の内容は含まない（Requirement/Task等に
    既にすべて含まれている）。"""

    document_id: str
    name: Optional[str] = None
    exported_at: Optional[str] = None
    # 納期考慮（任意）。planning_reference_dateは期限計算の基準日
    # （start_date未設定時は生成ジョブの実行日）。
    start_date: Optional[date] = None
    due_date: Optional[date] = None
    planning_reference_date: Optional[date] = None


class TraceabilityIssue(BaseModel):
    """Requirement -> Task のトレーサビリティが欠落しているタスク
    （Phase 8のCHECK 1とは逆方向の検証。このフェーズ独自）"""

    code: str
    message: str
    task_id: Optional[str] = None


class ValidationSummary(BaseModel):
    """`validation`セクション。Phase 8の`ValidationReport`をそのまま内包し、
    それに加えてvalid/warning/errorの3段階分類を明示する
    （依頼の"Clearly distinguish: valid / warning / error"に対応）。
    """

    status: ValidationStatus
    critical_issue_count: int
    warning_issue_count: int
    traceability_errors: List[TraceabilityIssue] = Field(default_factory=list)
    report: ValidationReport


class ProjectMetadata(BaseModel):
    """`metadata`セクション。依頼のREPRODUCIBILITY節の項目をすべて含む。"""

    generated_at: str
    pipeline_version: str
    model: Optional[str] = None
    model_version: Optional[str] = None
    prompt_versions: Dict[str, str] = Field(default_factory=dict)
    document_id: Optional[str] = None

    # 依頼の例のJSONには無いが、各フェーズで異なるモデルが使われていた場合に
    # それを黒黙に1つへ丸めて捏造しないための補足情報
    models_by_phase: Dict[str, str] = Field(default_factory=dict)


class FinalProjectOutput(BaseModel):
    """依頼のFINAL JSON節に対応する、最終的な構造化プロジェクト出力"""

    project: ProjectInfo
    requirements: List[Requirement]
    tasks: List[Task]
    dependencies: List[Dependency]
    members: List[Member]
    assignments: List[FinalAssignment]
    validation: ValidationSummary
    metadata: ProjectMetadata
