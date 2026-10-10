# backend/routers/projects.py
"""
Phase 10: プロジェクト（仕様書 + 確定済みメンバー情報）とジョブ起動のAPI。

**ビジネスロジックはここには無い。** 仕様書テキストとメンバー情報の
永続化、既存のPhase 6取り込み関数の呼び出し、ジョブの起動だけを行う。
既存のチーム/デバイストークン認証(backend.auth)をそのまま再利用する
——新しい認証の仕組みは作らない。
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from backend.auth.dependencies import get_current_member
from backend.auth.models import TeamMember
from backend.db.session import get_db
from backend.jobs.manager import job_manager
from backend.models.job_schemas import (
    GenerateRequest,
    GenerateResponse,
    ProjectCreateRequest,
    ProjectResponse,
    SetMembersRequest,
    UpdateRequest,
)
from backend.models.job import JobModel
from backend.models.project import ProjectModel
from backend.pipeline.members.runner import build_member_directory, load_member_directory, save_member_directory
from backend.pipeline.members.schema import MemberDirectory

router = APIRouter(prefix="/api", tags=["projects"])


def _to_project_response(project: ProjectModel) -> ProjectResponse:
    return ProjectResponse(
        id=project.id,
        team_id=project.team_id,
        name=project.name,
        has_document=bool(project.document_text and project.document_text.strip()),
        has_members=bool(project.members_path),
        start_date=project.start_date,
        due_date=project.due_date,
        created_at=project.created_at,
        updated_at=project.updated_at,
    )


async def _get_authorized_project(project_id: str, member: TeamMember, db: AsyncSession) -> ProjectModel:
    project = await db.get(ProjectModel, project_id)
    if project is None or project.team_id != member.team_id:
        # 他チームのプロジェクトIDを推測されても存在有無を漏らさない
        # （backend.auth.dependencies.require_same_teamと同じ404-not-403パターン）
        raise HTTPException(
            status_code=404,
            detail={"code": "PROJECT_NOT_FOUND", "message": "プロジェクトが見つかりません。"},
        )
    return project


@router.post("/projects", response_model=ProjectResponse, status_code=201)
async def create_project(
    body: ProjectCreateRequest,
    member: TeamMember = Depends(get_current_member),
    db: AsyncSession = Depends(get_db),
):
    """プロジェクトを作成する（チームに紐づく）"""
    project = ProjectModel(
        team_id=member.team_id, name=body.name, document_text=body.document_text,
        start_date=body.start_date, due_date=body.due_date,
    )
    db.add(project)
    await db.commit()
    await db.refresh(project)
    return _to_project_response(project)


@router.get("/projects/{project_id}", response_model=ProjectResponse)
async def get_project(
    project_id: str,
    member: TeamMember = Depends(get_current_member),
    db: AsyncSession = Depends(get_db),
):
    project = await _get_authorized_project(project_id, member, db)
    return _to_project_response(project)


@router.put("/projects/{project_id}/members", response_model=MemberDirectory)
async def set_project_members(
    project_id: str,
    body: SetMembersRequest,
    member: TeamMember = Depends(get_current_member),
    db: AsyncSession = Depends(get_db),
):
    """プロジェクトのメンバー情報(Phase 6)を設定する。

    `backend.pipeline.members.runner.build_member_directory`（既存の取り込み
    ロジック）をそのまま呼ぶだけ。スキルレベル等はここでも一切作り出さない
    ——`body.members`に含まれていない情報は現れない。
    """
    project = await _get_authorized_project(project_id, member, db)

    directory = build_member_directory(project.team_id, body.members)
    path = save_member_directory(directory, identifier=project.id)

    project.members_path = str(path)
    await db.commit()

    return directory


@router.get("/projects/{project_id}/members", response_model=MemberDirectory)
async def get_project_members(
    project_id: str,
    member: TeamMember = Depends(get_current_member),
    db: AsyncSession = Depends(get_db),
):
    project = await _get_authorized_project(project_id, member, db)
    if not project.members_path:
        raise HTTPException(
            status_code=404,
            detail={"code": "MEMBERS_NOT_CONFIGURED", "message": "このプロジェクトにはまだメンバー情報が設定されていません。"},
        )
    return load_member_directory(Path(project.members_path))


@router.post("/projects/{project_id}/generate", response_model=GenerateResponse, status_code=202)
async def generate_project(
    project_id: str,
    body: GenerateRequest,
    member: TeamMember = Depends(get_current_member),
    db: AsyncSession = Depends(get_db),
):
    """Phase 3-9パイプライン全体を実行するジョブを開始する。

    **この関数はパイプラインを実行しない。** ジョブレコードを作成して
    バックグラウンドタスクとしてスケジュールし、即座にjob_idを返す
    （依頼の"Avoid making the frontend wait indefinitely for one
    synchronous HTTP request"に対応）。
    """
    project = await _get_authorized_project(project_id, member, db)

    updates = {
        "document_text": body.document_text,
        "start_date": body.start_date,
        "due_date": body.due_date,
    }
    updates = {k: v for k, v in updates.items() if v is not None}
    if updates:
        for key, value in updates.items():
            setattr(project, key, value)
        await db.commit()

    if not project.document_text or not project.document_text.strip():
        raise HTTPException(
            status_code=400,
            detail={"code": "DOCUMENT_NOT_SET", "message": "仕様書テキストが設定されていません。"},
        )
    if not project.members_path:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "MEMBERS_NOT_CONFIGURED",
                "message": "先に PUT /api/projects/{project_id}/members でメンバー情報を設定してください。",
            },
        )

    job_id = await job_manager.create_job(project.id, project.team_id)
    job_manager.schedule(
        job_id,
        use_assignment_llm_reasoning=body.use_assignment_llm_reasoning,
        use_duplicate_llm_verification=body.use_duplicate_llm_verification,
    )

    return GenerateResponse(job_id=job_id, status="queued")


@router.post("/projects/{project_id}/update", response_model=GenerateResponse, status_code=202)
async def update_project(
    project_id: str,
    body: UpdateRequest,
    member: TeamMember = Depends(get_current_member),
    db: AsyncSession = Depends(get_db),
):
    """完了済みジョブの結果を再利用して、メンバー変更・仕様変更を反映するジョブを開始する。

    初回生成(`/generate`)と違い、要件抽出・タスク分解・依存関係を最初から作り直さない。
    元のジョブの結果は変更せず、更新結果は新しいジョブとして保存する。
    """
    project = await _get_authorized_project(project_id, member, db)
    source = await db.get(JobModel, body.source_job_id)
    if source is None or source.project_id != project.id or source.team_id != member.team_id:
        raise HTTPException(
            status_code=404,
            detail={"code": "JOB_NOT_FOUND", "message": "更新元のジョブが見つかりません。"},
        )
    if source.status != "completed":
        raise HTTPException(
            status_code=409,
            detail={"code": "SOURCE_JOB_NOT_COMPLETED", "message": "更新元のジョブが完了していません。"},
        )
    if not project.members_path:
        raise HTTPException(
            status_code=400,
            detail={"code": "MEMBERS_NOT_CONFIGURED", "message": "先にメンバー情報を設定してください。"},
        )
    if body.reassign_scope == "selected" and not body.task_ids:
        raise HTTPException(
            status_code=400,
            detail={"code": "TASK_IDS_REQUIRED", "message": "割り当て直すタスクを指定してください。"},
        )

    old_document_text = project.document_text
    if body.mode == "spec":
        if not body.document_text or not body.document_text.strip():
            raise HTTPException(
                status_code=400,
                detail={"code": "DOCUMENT_NOT_SET", "message": "更新後の仕様書本文を指定してください。"},
            )
        project.document_text = body.document_text
        await db.commit()

    job_id = await job_manager.create_job(project.id, project.team_id)
    job_manager.schedule_update(
        job_id, source.id, body.mode,
        reassign_scope=body.reassign_scope,
        task_ids=body.task_ids,
        client_overrides=body.current_assignments,
        old_document_text=old_document_text,
    )
    return GenerateResponse(job_id=job_id, status="queued")
