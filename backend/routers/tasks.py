import os
import json
from datetime import date
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.session import get_db
from backend.models.member import MemberModel
from backend.models.schemas import (
    GenerationNotes,
    ProjectOutputSchema,
    SettingsSchema,
    TaskSchema,
    TaskUpdateRequest,
)
from backend.models.task import TaskModel
from backend.services.matcher import compute_assignments
from backend.services.parser import parse_document
# 作成した LLM サービスからファクトリ関数をインポート
from backend.services.llm import get_llm_client
from backend.services.pipeline.runner import run_pipeline

router = APIRouter(prefix="/api")

# 指針1 & 7: ハードコードを排除してenvから制限値を読み込み
raw_max_tasks = os.getenv("MAX_TASKS_FREE")
if raw_max_tasks is None:
    raise RuntimeError("環境変数 'MAX_TASKS_FREE' が設定されていません。")
MAX_TASKS_FREE = int(raw_max_tasks)

# プロジェクトの表示用メタ情報（現状は単一プロジェクトのデモ運用のためメモリ保持で十分）
PROJECT_META: Dict[str, Any] = {
    "project": "名称未設定プロジェクト",
    "exported_at": str(date.today()),
}

SETTINGS_STORE: Dict[str, Any] = {
    "provider": "openai",
    "api_key": "",
    "base_url": None,
    "slack_webhook_url": None,
    "teams_webhook_url": None,
}


@router.post("/tasks/generate", response_model=ProjectOutputSchema)
async def generate_tasks(
    file: UploadFile = File(None),
    text_content: Optional[str] = Form(None),
    members_json: str = Form(..., description="JSON文字列化されたメンバーリスト"),
    db: AsyncSession = Depends(get_db),
):
    """仕様書とメンバー情報からタスクを自動生成・マッチングし、DBに永続化する"""

    # 💡 関数内部にチェックを移動（APIが叩かれた時に初めて判定する）
    raw_max_tasks = os.getenv("MAX_TASKS_FREE")
    if raw_max_tasks is None:
        raise HTTPException(
            status_code=500,
            detail={"code": "CONFIG_ERROR", "message": "サーバーの環境変数 'MAX_TASKS_FREE' が設定されていません。"}
        )
    MAX_TASKS_FREE = int(raw_max_tasks)

    # 1. メンバーJSON文字列をPythonのリストにデコード
    try:
        members = json.loads(members_json)
        # 💡 各メンバーに load_pct が無ければ初期値 0 をセットするガードレールを追加
        for m in members:
            if "load_pct" not in m:
                m["load_pct"] = 0
    except Exception:
        raise HTTPException(
            status_code=400,
            detail={"code": "INVALID_MEMBERS_JSON", "message": "members_json のパースに失敗しました。"}
        )

    # 2. 仕様書ドキュメントのテキスト抽出
    document_text = ""
    if file:
        try:
            file_bytes = await file.read()
            document_text = parse_document(file.filename, file_bytes)
        except ValueError as ve:
            raise HTTPException(
                status_code=400,
                detail={"code": "FILE_PARSE_ERROR", "message": str(ve)}
            )
        except Exception as e:
            raise HTTPException(
                status_code=500,
                detail={"code": "FILE_PARSE_ERROR", "message": f"ファイル解析エラー: {str(e)}"}
            )
    elif text_content:
        document_text = text_content.strip()

    if not document_text:
        raise HTTPException(
            status_code=400,
            detail={"code": "EMPTY_INPUT", "message": "仕様書ファイルまたはテキスト入力を提供してください。"}
        )

    # 3. 構造化タスク抽出パイプライン（文書構造抽出→要求識別→候補タスク化→
    #    正規化→重複検出→検証、の多段パイプライン。詳細は backend/services/pipeline/）
    client = get_llm_client()
    pipeline_result = await run_pipeline(document_text, client)

    llm_tasks = []
    for pt in pipeline_result.tasks:
        llm_tasks.append({
            "task_id": pt.task_id,
            "title": pt.title,
            "description": pt.description,
            # skill_required(文字列)はマッチングエンジン・旧フロント契約向けの互換フィールド
            "skill_required": ", ".join(pt.required_skills) if pt.required_skills else "unknown",
            "required_skills": pt.required_skills,
            "priority": pt.priority.value,
            "estimated_hours": pt.estimated_hours,
            "source_section": (pt.source_reference.excerpt if pt.source_reference else "§ 出典不明"),
            "source_chunk_id": pt.source_reference.chunk_id if pt.source_reference else None,
            "source_excerpt": pt.source_reference.excerpt if pt.source_reference else None,
            "acceptance_criteria": pt.acceptance_criteria,
            "needs_review": pt.needs_review,
            "review_reason": pt.review_reason,
            "status": "TODO",
        })

    # 指針7: 上限チェックのシミュレーション
    if len(llm_tasks) > MAX_TASKS_FREE:
        raise HTTPException(
            status_code=403,
            detail={"code": "PLAN_LIMIT_EXCEEDED", "message": f"生成タスク数が上限（{MAX_TASKS_FREE}件）を超えました。"}
        )

    # 4. スキルマッチングエンジンの実行
    assigned_tasks = compute_assignments(llm_tasks, members)

    # 指針5: 使用量記録（モック呼び出し）
    _mock_record_usage(
        action="task_generate",
        task_count=len(assigned_tasks),
        org_id=None,
        user_id=None,
    )

    # 5. DBへの永続化（単一プロジェクトのデモ運用のため、既存タスク・メンバーを置き換える）
    await db.execute(delete(TaskModel))
    await db.execute(delete(MemberModel))

    for task in assigned_tasks:
        db.add(TaskModel(
            task_id=task["task_id"],
            title=task["title"],
            assignee=task.get("assignee", "未割り当て"),
            skill_required=task.get("skill_required", "unknown"),
            priority=task.get("priority", "unknown"),
            source_section=task.get("source_section", "§ 出典不明"),
            load_pct=task.get("load_pct", 0),
            status=task.get("status", "TODO"),
            description=task.get("description"),
            estimated_hours=task.get("estimated_hours"),
            required_skills=task.get("required_skills"),
            acceptance_criteria=task.get("acceptance_criteria"),
            source_chunk_id=task.get("source_chunk_id"),
            source_excerpt=task.get("source_excerpt"),
            needs_review=task.get("needs_review", False),
            review_reason=task.get("review_reason"),
        ))

    for member in members:
        db.add(MemberModel(
            name=member["name"],
            skills=",".join(member.get("skills", [])),
            load_pct=member.get("load_pct", 0),
        ))

    PROJECT_META["exported_at"] = str(date.today())

    await db.commit()
    output = await _build_project_output(db)
    output["generation_notes"] = GenerationNotes(
        failed_item_count=len(pipeline_result.failed_items),
        dropped_duplicate_titles=pipeline_result.dropped_duplicates,
    )
    return output


@router.get("/tasks", response_model=ProjectOutputSchema)
async def get_tasks(db: AsyncSession = Depends(get_db)):
    """DBに永続化されているタスク一覧を取得する"""
    return await _build_project_output(db)


@router.put("/tasks/{task_id}")
async def update_task(task_id: str, request: TaskUpdateRequest, db: AsyncSession = Depends(get_db)):
    """Kanbanのドラッグ＆ドロップやインライン編集によるタスク更新"""
    result = await db.execute(select(TaskModel).where(TaskModel.task_id == task_id))
    task = result.scalar_one_or_none()

    if task is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "TASK_NOT_FOUND", "message": "指定されたタスクが見つかりません。"}
        )

    if request.title is not None:
        task.title = request.title
    if request.assignee is not None:
        task.assignee = request.assignee
    if request.priority is not None:
        task.priority = request.priority
    if request.source_section is not None:
        task.source_section = request.source_section
    if request.status is not None:
        task.status = request.status

    await db.commit()
    return {"status": "success", "task": TaskSchema.model_validate(task).model_dump()}


@router.get("/tasks/export")
async def export_tasks(db: AsyncSession = Depends(get_db)):
    """JSONファイルエクスポート用のデータを返す"""
    return await _build_project_output(db)


@router.post("/settings")
def update_settings(settings: SettingsSchema):
    """設定画面からのLLM設定や通知設定をメモリに保持する"""
    SETTINGS_STORE.update(settings.model_dump())
    return {
        "status": "success",
        "message": "設定を保存しました",
        "current_settings": SETTINGS_STORE,
    }


@router.get("/settings")
def get_settings():
    """現在の設定情報を取得する (フロントエンドの初期表示用)"""
    return SETTINGS_STORE


async def _build_project_output(db: AsyncSession) -> Dict[str, Any]:
    """DB上の全タスクを ProjectOutputSchema 相当の辞書に組み立てる"""
    result = await db.execute(select(TaskModel).order_by(TaskModel.task_id))
    tasks = result.scalars().all()
    return {
        "project": PROJECT_META["project"],
        "exported_at": PROJECT_META["exported_at"],
        "tasks": [TaskSchema.model_validate(t) for t in tasks],
    }


def _mock_record_usage(action: str, task_count: int, org_id: int = None, user_id: int = None):
    print(f"[USAGE LOG] Action: {action}, Count: {task_count}, Org: {org_id}, User: {user_id}")
