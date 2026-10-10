# backend/routers/jobs.py
"""
Phase 10: ジョブ状態・結果・各ステージ成果物を取得するAPI。

**ここにビジネスロジックは無い。** JobModelの行を読み、各フェーズが
既に書き出したJSONファイルを既存のスキーマで読み込んで返すだけ
（STEP 7: Requirements/Tasks/Dependencies/Members/Assignments/Validation/
Final project resultのAPI公開）。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import List, Type, TypeVar

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from backend.auth.dependencies import get_current_member
from backend.auth.models import TeamMember
from backend.jobs.manager import job_manager
from backend.jobs.updates import UpdateSummary, load_update_summary
from backend.db.session import get_db
from backend.models.job import JobModel
from backend.models.job_schemas import ErrorDetail, JobStatusResponse
from backend.pipeline.assignment.schema import FinalAssignment
from backend.pipeline.dependencies.schema import DependencyDocument
from backend.pipeline.final_output.runner import load_final_output
from backend.pipeline.final_output.schema import FinalProjectOutput
from backend.pipeline.requirements.schema import RequirementDocument
from backend.pipeline.tasks.schema import TaskDocument
from backend.pipeline.validation.schema import ValidationReport

router = APIRouter(prefix="/api", tags=["jobs"])

T = TypeVar("T", bound=BaseModel)


async def _get_authorized_job(job_id: str, member: TeamMember, db: AsyncSession) -> JobModel:
    job = await db.get(JobModel, job_id)
    if job is None or job.team_id != member.team_id:
        # 他チームのjob_idを推測されても存在有無を漏らさない（他ルーターと同じパターン）
        raise HTTPException(
            status_code=404,
            detail={"code": "JOB_NOT_FOUND", "message": "ジョブが見つかりません。"},
        )
    return job


def _to_status_response(job: JobModel) -> JobStatusResponse:
    error = None
    if job.status == "failed":
        error = ErrorDetail(code=job.error_code or "INTERNAL_ERROR", message=job.error_message or "エラーが発生しました。")
    return JobStatusResponse(
        job_id=job.id,
        project_id=job.project_id,
        team_id=job.team_id,
        status=job.status,
        progress=job.progress,
        current_step=job.current_step,
        message=job.message,
        created_at=job.created_at,
        started_at=job.started_at,
        completed_at=job.completed_at,
        error=error,
    )


def _load_stage_document(path_value: str | None, model_cls: Type[T], stage_name: str) -> T:
    if not path_value:
        raise HTTPException(
            status_code=409,
            detail={"code": "STAGE_NOT_READY", "message": f"'{stage_name}'ステージはまだ完了していません。"},
        )
    try:
        data = json.loads(Path(path_value).read_text(encoding="utf-8"))
        return model_cls.model_validate(data)
    except (OSError, ValidationError) as e:
        raise HTTPException(
            status_code=500,
            detail={"code": "RESULT_READ_ERROR", "message": f"保存済み結果の読み込みに失敗しました: {e}"},
        )


@router.get("/jobs/{job_id}", response_model=JobStatusResponse)
async def get_job_status(
    job_id: str,
    member: TeamMember = Depends(get_current_member),
    db: AsyncSession = Depends(get_db),
):
    job = await _get_authorized_job(job_id, member, db)
    return _to_status_response(job)


@router.get("/jobs/{job_id}/error", response_model=ErrorDetail)
async def get_job_error(
    job_id: str,
    member: TeamMember = Depends(get_current_member),
    db: AsyncSession = Depends(get_db),
):
    job = await _get_authorized_job(job_id, member, db)
    if job.status != "failed":
        raise HTTPException(
            status_code=404,
            detail={"code": "NO_ERROR", "message": "このジョブは失敗していません。"},
        )
    return ErrorDetail(code=job.error_code or "INTERNAL_ERROR", message=job.error_message or "エラーが発生しました。")


@router.get("/jobs/{job_id}/result", response_model=FinalProjectOutput)
async def get_job_result(
    job_id: str,
    member: TeamMember = Depends(get_current_member),
    db: AsyncSession = Depends(get_db),
):
    job = await _get_authorized_job(job_id, member, db)

    if job.status == "failed":
        raise HTTPException(
            status_code=409,
            detail={
                "code": job.error_code or "JOB_FAILED",
                "message": job.error_message or "ジョブが失敗しました。",
            },
        )
    if job.status != "completed":
        raise HTTPException(
            status_code=409,
            detail={"code": "JOB_NOT_COMPLETED", "message": f"ジョブはまだ完了していません（status={job.status}）。"},
        )
    if not job.result_path:
        raise HTTPException(
            status_code=500,
            detail={"code": "RESULT_MISSING", "message": "完了済みのジョブに結果ファイルがありません。"},
        )
    return load_final_output(Path(job.result_path))


@router.get("/jobs/{job_id}/requirements", response_model=RequirementDocument)
async def get_job_requirements(
    job_id: str,
    member: TeamMember = Depends(get_current_member),
    db: AsyncSession = Depends(get_db),
):
    job = await _get_authorized_job(job_id, member, db)
    return _load_stage_document(job.requirements_path, RequirementDocument, "requirements")


@router.get("/jobs/{job_id}/tasks", response_model=TaskDocument)
async def get_job_tasks(
    job_id: str,
    member: TeamMember = Depends(get_current_member),
    db: AsyncSession = Depends(get_db),
):
    job = await _get_authorized_job(job_id, member, db)
    return _load_stage_document(job.tasks_path, TaskDocument, "tasks")


@router.get("/jobs/{job_id}/dependencies", response_model=DependencyDocument)
async def get_job_dependencies(
    job_id: str,
    member: TeamMember = Depends(get_current_member),
    db: AsyncSession = Depends(get_db),
):
    job = await _get_authorized_job(job_id, member, db)
    return _load_stage_document(job.dependencies_path, DependencyDocument, "dependencies")


@router.get("/jobs/{job_id}/validation", response_model=ValidationReport)
async def get_job_validation(
    job_id: str,
    member: TeamMember = Depends(get_current_member),
    db: AsyncSession = Depends(get_db),
):
    job = await _get_authorized_job(job_id, member, db)
    return _load_stage_document(job.validation_path, ValidationReport, "validation")


@router.get("/jobs/{job_id}/assignments", response_model=List[FinalAssignment])
async def get_job_assignments(
    job_id: str,
    member: TeamMember = Depends(get_current_member),
    db: AsyncSession = Depends(get_db),
):
    job = await _get_authorized_job(job_id, member, db)
    if not job.assignments_path:
        raise HTTPException(
            status_code=409,
            detail={"code": "STAGE_NOT_READY", "message": "'assignments'ステージはまだ完了していません。"},
        )
    try:
        raw = json.loads(Path(job.assignments_path).read_text(encoding="utf-8"))
        return [FinalAssignment.model_validate(item) for item in raw]
    except (OSError, ValidationError) as e:
        raise HTTPException(
            status_code=500,
            detail={"code": "RESULT_READ_ERROR", "message": f"保存済み結果の読み込みに失敗しました: {e}"},
        )


@router.get("/jobs/{job_id}/update-summary", response_model=UpdateSummary)
async def get_job_update_summary(
    job_id: str,
    member: TeamMember = Depends(get_current_member),
    db: AsyncSession = Depends(get_db),
):
    """更新ジョブ（POST /api/projects/{id}/update）で、何を再利用し何を作り直したか"""
    await _get_authorized_job(job_id, member, db)
    summary = load_update_summary(job_manager.update_summary_path(job_id))
    if summary is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "NOT_AN_UPDATE", "message": "このジョブは更新ジョブではないか、まだ完了していません。"},
        )
    return summary
