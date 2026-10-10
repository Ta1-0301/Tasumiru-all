# backend/jobs/manager.py
"""
Phase 10のジョブオーケストレーター。

**ここではPhase 3-9のどの関数も書き換えない。** 各ステージは既存の
`backend.pipeline.*.runner`の関数をそのまま`await`で呼び出すだけで、
その戻り値をそのまま既存の保存関数(save_*)でJSONファイルへ書き出し、
`backend.models.job.JobModel`の進捗フィールドを更新する。

DBセッションの扱いについて重要な設計判断: **1回のジョブ実行の間、1つの
DBセッションを開きっぱなしにしない。** 各ステージの前後で毎回
新しいセッションを開いて即座にコミット・クローズする(`_update`/`_fail`)。
LLM呼び出しのような遅い外部I/Oをまたいでトランザクションを保持するのは
一般的なアンチパターンであることに加え、同じ接続を使い回すテスト用の
インメモリSQLite(StaticPool)環境で、ジョブの進行中に別セッション
（ポーリングしてくるHTTPリクエスト）が同じ接続を使おうとした際の
競合を避けるためでもある。

CLI(`python -m backend.pipeline.*.runner`)とこのジョブマネージャーは、
どちらも同じPhase 3-9の関数を呼ぶ「別々の入口」であり、パイプライン自体は
1つしか存在しない（STEP 18: 唯一の情報源）。
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence, Set, Tuple

from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.session import AsyncSessionLocal
from backend.jobs.errors import classify_exception
from backend.jobs.timing import pipeline_stage, timed_client, timed_embedding_client
from backend.jobs.updates import (
    ItemRef,
    ReassignScope,
    UpdateMode,
    UpdateSummary,
    assign_tasks,
    chunk_key,
    current_assignments,
    mark_removal_candidate,
    match_items,
    next_id,
    plan_chunks,
    save_update_summary,
    select_preserved,
    summarize_assignments,
)
from backend.models.job import JobModel
from backend.models.project import ProjectModel
from backend.pipeline.assignment.audit import summarize_assignment_audit
from backend.pipeline.assignment.schema import FinalAssignment
from backend.pipeline.dependencies.graph import DependencyGraph
from backend.pipeline.dependencies.runner import OUTPUT_DIR as DEPENDENCIES_OUTPUT_DIR
from backend.pipeline.dependencies.runner import run_dependency_pipeline, save_dependencies_document
from backend.pipeline.dependencies.schema import DependencyDocument
from backend.pipeline.dependencies.validator import validate_dependencies
from backend.pipeline.final_output.assembler import assemble_final_output
from backend.pipeline.final_output.runner import OUTPUT_DIR as FINAL_OUTPUT_DIR
from backend.pipeline.final_output.runner import save_final_output
from backend.pipeline.members.runner import load_member_directory
from backend.pipeline.requirements.runner import OUTPUT_DIR as REQUIREMENTS_OUTPUT_DIR
from backend.pipeline.requirements.extractor import extract_requirements_from_chunk
from backend.pipeline.requirements.runner import run_requirements_pipeline, save_requirements_document
from backend.pipeline.requirements.schema import Requirement, RequirementDocument
from backend.pipeline.requirements.schema import ValidationIssue as RequirementIssue
from backend.pipeline.requirements.validator import validate_requirements
from backend.pipeline.tasks.runner import OUTPUT_DIR as TASKS_OUTPUT_DIR
from backend.pipeline.tasks.decomposer import decompose_requirement
from backend.pipeline.tasks.runner import run_task_decomposition_pipeline, save_tasks_document
from backend.pipeline.tasks.schema import Task, TaskDocument
from backend.pipeline.tasks.schema import ValidationIssue as TaskIssue
from backend.pipeline.tasks.skill_evaluation import check_task_skill_consistency
from backend.pipeline.tasks.validator import apply_review_flags, validate_tasks
from backend.pipeline.tasks.skill_vocabulary import build_team_skill_vocabulary
from backend.pipeline.validation.runner import OUTPUT_DIR as VALIDATION_OUTPUT_DIR
from backend.pipeline.validation.runner import (
    save_validation_report,
    validate_project_plan,
    validate_project_plan_with_llm_verification,
)
from backend.services.concurrency import gather_with_concurrency, get_max_concurrency
from backend.services.llm import get_llm_client
from backend.services.pipeline.structure import decompose_document
from backend.services.rag.embeddings import get_embedding_client
from backend.services.rag.index import build_spec_index
from backend.services.rag.schema import SpecIndex

logger = logging.getLogger("tasumiru.jobs")

JOB_OUTPUT_DIR = Path(__file__).resolve().parent / "output"

SessionFactory = Callable[[], AsyncSession]

# ステージ境界(進捗%)。STEP 5: 時間経過ではなく、各ステージの実際の開始/完了
# イベントでのみ更新する。パーセンテージの割り振り自体は「そのステージで
# 何回程度LLM呼び出しが起こりうるか」という構造上の見積りであり、実測値
# ではない（実測はログのdurationを参照。docs/PIPELINE_PERFORMANCE.md参照）。
STAGE_BOUNDS: Dict[str, Tuple[int, int]] = {
    "requirements": (5, 25),    # チャンク数だけLLM呼び出しが起こりうる
    "tasks": (25, 50),          # 要求数だけLLM呼び出しが起こりうる（通常最多）
    "dependencies": (50, 65),   # タスク一覧全体で1回のLLM呼び出し
    "members": (65, 70),        # LLM不使用。決定的なファイルI/Oのみ
    "assignments": (70, 90),    # reasoning有効時、タスク数だけLLM呼び出しが起こりうる
    "validation": (90, 95),     # 既定はLLM不使用（重複検証のみ任意でLLM）
    "finalize": (95, 100),      # LLM不使用
}

STAGE_START_MESSAGES = {
    "requirements": "要求を抽出しています...",
    "tasks": "タスクに分解しています...",
    "dependencies": "依存関係を分析しています...",
    "members": "メンバー情報を取得しています...",
    "assignments": "担当者を割り当てています...",
    "validation": "プロジェクト計画を検証しています...",
    "finalize": "最終結果を組み立てています...",
}

STAGE_DONE_MESSAGES = {
    "requirements": "要求抽出が完了しました。",
    "tasks": "タスク分解が完了しました。",
    "dependencies": "依存関係分析が完了しました。",
    "members": "メンバー情報の取得が完了しました。",
    "assignments": "担当者の割り当てが完了しました。",
    "validation": "検証が完了しました。",
    "finalize": "生成が完了しました。",
}


def resolve_llm_client():
    """`backend.services.llm.get_llm_client`をそのまま呼ぶだけの薄いラッパー。

    テストがこの関数だけを`monkeypatch`することで、ジョブ実行全体を
    FakeLLMClientに差し替えられるようにするための、唯一の意図的な間接層。
    """
    return get_llm_client()


def resolve_embedding_client():
    """`backend.services.rag.embeddings.get_embedding_client`をそのまま呼ぶだけの
    薄いラッパー。`resolve_llm_client`と同じ理由（テストがフェイクEmbeddingクライアント
    に差し替えられるようにするための、唯一の意図的な間接層）。
    """
    return get_embedding_client()


def is_rag_enabled() -> bool:
    """実験的RAG機能のON/OFFフラグ。既定はOFF（既存パイプラインと完全に同じ挙動）。

    呼び出しのたびに環境変数を読む（モジュールimport時に固定しない）ことで、
    テストが`monkeypatch.setenv("ENABLE_RAG", "true")`で切り替えられるようにする。
    """
    return os.getenv("ENABLE_RAG", "false").strip().lower() in ("1", "true", "yes")


class JobManager:
    """
    `session_factory`/`output_root`は、既存の`AsyncSessionLocal`(実DB)と
    各フェーズの既定の`output/`ディレクトリを使うのが既定の（本番の）挙動。
    テストだけがこれらを差し替えて、テスト用DB/一時ディレクトリに
    書き込ませる（本番のコードパス自体は一切変わらない）。
    """

    def __init__(
        self,
        session_factory: Optional[SessionFactory] = None,
        output_root: Optional[Path] = None,
    ) -> None:
        self._background_tasks: Set[asyncio.Task] = set()
        self._session_factory: SessionFactory = session_factory or AsyncSessionLocal
        self._output_root = output_root

    def _resolve_output_dir(self, default_dir: Path, subfolder: str) -> Path:
        if self._output_root is None:
            return default_dir
        return self._output_root / subfolder

    async def create_job(self, project_id: str, team_id: str) -> str:
        async with self._session_factory() as db:
            job = JobModel(project_id=project_id, team_id=team_id, status="queued", progress=0)
            db.add(job)
            await db.commit()
            await db.refresh(job)
            return job.id

    def schedule(
        self,
        job_id: str,
        use_assignment_llm_reasoning: bool = False,
        use_duplicate_llm_verification: bool = False,
    ) -> None:
        """バックグラウンドでジョブを開始する。すぐに戻る
        （HTTPハンドラは`create_job`のjob_idを202で即座に返せる）。
        """
        task = asyncio.create_task(
            self.run_job(job_id, use_assignment_llm_reasoning, use_duplicate_llm_verification)
        )
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)

    async def run_job(
        self,
        job_id: str,
        use_assignment_llm_reasoning: bool = False,
        use_duplicate_llm_verification: bool = False,
    ) -> None:
        project = await self._load_project_for_job(job_id)
        if project is None:
            return  # _load_project_for_jobが既にjob/projectの欠落をハンドリング済み

        if not project.document_text or not project.document_text.strip():
            await self._fail(job_id, "DOCUMENT_NOT_SET", "プロジェクトに仕様書テキストが設定されていません。")
            return
        if not project.members_path:
            await self._fail(job_id, "MEMBERS_NOT_CONFIGURED", "プロジェクトにメンバー情報が設定されていません。")
            return

        try:
            base_client = resolve_llm_client()
        except Exception as e:
            code, message = classify_exception(e)
            await self._fail(job_id, code, message)
            return

        await self._update(job_id, status="running", started_at=datetime.now(timezone.utc))

        # Task生成の参考語彙（チームのスキル名一覧）。Membersステージ自体の位置・
        # 処理は変えず、Assignmentで使うのと同じmembers.jsonを読み取り専用で
        # ジョブ開始時に1回だけ読む（LLM不使用）。
        team_skill_vocabulary = self._load_team_skill_vocabulary(job_id, project)

        try:
            req_doc, spec_index = await self._run_requirements(job_id, project, base_client)
            task_doc = await self._run_tasks(
                job_id, req_doc, base_client, spec_index, team_skill_vocabulary=team_skill_vocabulary,
            )
            dep_doc = await self._run_dependencies(job_id, task_doc, base_client)
            member_dir = await self._run_members(job_id, project)
            # 納期考慮の基準日。プロジェクトの開始日が無ければジョブの実行日。
            # 納期（プロジェクト/タスク）が1つも無ければ使われない（従来と同じ計算）。
            reference_date = project.start_date or date.today()
            final_assignments = await self._run_assignments(
                job_id, task_doc, dep_doc, member_dir, base_client, use_assignment_llm_reasoning,
                project_due_date=project.due_date, reference_date=reference_date,
            )
            report = await self._run_validation(
                job_id, req_doc, task_doc, dep_doc, member_dir, final_assignments, base_client,
                use_duplicate_llm_verification,
                project_due_date=project.due_date, reference_date=reference_date,
            )
            await self._run_finalize(
                job_id, project, req_doc, task_doc, dep_doc, member_dir, final_assignments, report,
                reference_date=reference_date,
            )
        except Exception as e:  # noqa: BLE001 — ジョブを失敗として記録するために意図的に広く捕捉する
            logger.exception("[JOB] %s failed", job_id)
            code, message = classify_exception(e)
            await self._fail(job_id, code, message)

    async def _load_project_for_job(self, job_id: str) -> Optional[ProjectModel]:
        async with self._session_factory() as db:
            job = await db.get(JobModel, job_id)
            if job is None:
                logger.warning("[JOB] %s not found at run time", job_id)
                return None
            project = await db.get(ProjectModel, job.project_id)
        if project is None:
            await self._fail(job_id, "PROJECT_NOT_FOUND", "プロジェクトが見つかりません。")
            return None
        return project

    def _load_team_skill_vocabulary(self, job_id: str, project: ProjectModel) -> Optional[List[str]]:
        """Task生成用のチームスキル語彙を作る。

        読み込みに失敗した場合は、空の語彙を作って成功扱いにはせず、None
        （＝従来と完全に同じTask生成）を返す。members.jsonの読み込み失敗そのものは、
        これまで通り後段のMembersステージ(`_run_members`)が例外としてジョブを
        失敗させる（既存のエラーハンドリングをここで変えない）。
        ログには件数のみを出し、スキル名・メンバー情報は出さない。
        """
        try:
            member_dir = load_member_directory(Path(project.members_path))
        except Exception as e:  # noqa: BLE001 — 参考情報の取得失敗でジョブを止めない（判断はMembersステージに委ねる）
            logger.warning(
                "[ASSIGNMENT] job=%s team_skill_vocabulary unavailable (%s); task generation runs without it",
                job_id, type(e).__name__,
            )
            return None
        vocabulary = build_team_skill_vocabulary(member_dir.members)
        logger.info(
            "[ASSIGNMENT] job=%s members=%d team_skill_vocabulary_count=%d",
            job_id, len(member_dir.members), len(vocabulary),
        )
        return vocabulary or None

    # --- 各ステージ（既存のPhase 3-9関数を呼ぶだけ） ---

    async def _run_requirements(self, job_id, project, base_client) -> Tuple[object, Optional[SpecIndex]]:
        await self._update(job_id, current_step="requirements", progress=STAGE_BOUNDS["requirements"][0],
                            message=STAGE_START_MESSAGES["requirements"])
        with pipeline_stage("requirements"):
            client = timed_client(base_client, "requirements")
            req_doc = await run_requirements_pipeline(project.id, project.document_text, client)

        # 実験的RAG機能（ENABLE_RAG=true時のみ）: 仕様書のベクトルインデックスを
        # ここで一度だけ構築する。既存のrequirements抽出結果には一切影響しない
        # （req_docはRAGの有無にかかわらず同一）。
        spec_index: Optional[SpecIndex] = None
        if is_rag_enabled():
            with pipeline_stage("embedding"):
                embed_client: Optional[object] = None
                try:
                    embed_client = timed_embedding_client(resolve_embedding_client(), "embedding")
                    spec_index = await build_spec_index(project.id, project.document_text, embed_client)
                except Exception:
                    # Embeddingクライアントの構築失敗・API呼び出し失敗のいずれでも
                    # 本体のパイプラインは止めない（RAGは補助機能）。related_sourcesが
                    # 空のまま従来通りのタスクが生成される。
                    logger.exception("[JOB] %s embedding failed, continuing without RAG", job_id)
                    spec_index = None
                if embed_client is not None:
                    logger.info(
                        "[PERF] job=%s embedding_calls=%d embedding_seconds=%.2f chunks=%d",
                        job_id, embed_client.call_count, embed_client.total_duration,
                        len(spec_index.chunks) if spec_index else 0,
                    )

        path = save_requirements_document(
            req_doc, output_dir=self._resolve_output_dir(REQUIREMENTS_OUTPUT_DIR, "requirements")
        )
        await self._update(job_id, progress=STAGE_BOUNDS["requirements"][1],
                            message=STAGE_DONE_MESSAGES["requirements"], requirements_path=str(path))
        return req_doc, spec_index

    async def _run_tasks(
        self, job_id, req_doc, base_client, spec_index: Optional[SpecIndex] = None,
        team_skill_vocabulary: Optional[List[str]] = None,
    ):
        await self._update(job_id, current_step="tasks", progress=STAGE_BOUNDS["tasks"][0],
                            message=STAGE_START_MESSAGES["tasks"])
        embedding_client = timed_embedding_client(resolve_embedding_client(), "tasks") if spec_index else None
        with pipeline_stage("tasks"):
            client = timed_client(base_client, "tasks")
            task_doc = await run_task_decomposition_pipeline(
                req_doc, client, spec_index=spec_index, embedding_client=embedding_client,
                team_skill_vocabulary=team_skill_vocabulary,
            )
        if embedding_client is not None:
            logger.info(
                "[PERF] job=%s task_query_embedding_calls=%d task_query_embedding_seconds=%.2f",
                job_id, embedding_client.call_count, embedding_client.total_duration,
            )
        path = save_tasks_document(task_doc, output_dir=self._resolve_output_dir(TASKS_OUTPUT_DIR, "tasks"))
        await self._update(job_id, progress=STAGE_BOUNDS["tasks"][1],
                            message=STAGE_DONE_MESSAGES["tasks"], tasks_path=str(path))
        return task_doc

    async def _run_dependencies(self, job_id, task_doc, base_client):
        await self._update(job_id, current_step="dependencies", progress=STAGE_BOUNDS["dependencies"][0],
                            message=STAGE_START_MESSAGES["dependencies"])
        with pipeline_stage("dependencies"):
            client = timed_client(base_client, "dependencies")
            dep_doc = await run_dependency_pipeline(task_doc, client)
        path = save_dependencies_document(
            dep_doc, output_dir=self._resolve_output_dir(DEPENDENCIES_OUTPUT_DIR, "dependencies")
        )
        await self._update(job_id, progress=STAGE_BOUNDS["dependencies"][1],
                            message=STAGE_DONE_MESSAGES["dependencies"], dependencies_path=str(path))
        return dep_doc

    async def _run_members(self, job_id, project):
        """member情報の取得(Phase 6)。LLM不使用。既に確定済みのmembers.json
        を1回だけ読み込む（"A. loaded once before assignment"に対応。
        STEP 8参照）。
        """
        await self._update(job_id, current_step="members", progress=STAGE_BOUNDS["members"][0],
                            message=STAGE_START_MESSAGES["members"])
        with pipeline_stage("members"):
            member_dir = load_member_directory(Path(project.members_path))
        await self._update(job_id, progress=STAGE_BOUNDS["members"][1],
                            message=STAGE_DONE_MESSAGES["members"], members_path=project.members_path)
        return member_dir

    async def _run_assignments(
        self, job_id, task_doc, dep_doc, member_dir, base_client, use_llm_reasoning,
        project_due_date: Optional[date] = None, reference_date: Optional[date] = None,
        preserved: Optional[Dict[str, FinalAssignment]] = None,
    ):
        await self._update(job_id, current_step="assignments", progress=STAGE_BOUNDS["assignments"][0],
                            message=STAGE_START_MESSAGES["assignments"])
        assignment_client = timed_client(base_client, "assignments") if use_llm_reasoning else None

        with pipeline_stage("assignments"):
            # 負荷率100%以内・負荷の均一化・期限までの累積負荷は、いずれも前のタスクの
            # 割当結果に依存するため、タスクを期限の早い順（EDF）に1件ずつ逐次実行し、
            # 割り当てた工数を台帳(AssignmentLedger)に記録していく（updates.assign_tasks）。
            # `preserved`（更新時に維持する既存の割り当て）が無ければ初回生成の処理そのもの。
            final_assignments = await assign_tasks(
                task_doc, dep_doc, member_dir, client=assignment_client,
                project_due_date=project_due_date, reference_date=reference_date,
                preserved=preserved,
            )

        path = self._save_assignments(job_id, final_assignments)
        audit_summary = summarize_assignment_audit(final_assignments)
        logger.info(
            "[ASSIGNMENT] job=%s total=%d assigned=%d unassigned=%d success_rate=%.2f%% reasons=%s",
            job_id, audit_summary.total_tasks, audit_summary.assigned_tasks,
            audit_summary.unassigned_tasks, audit_summary.success_rate,
            audit_summary.unassigned_by_reason,
        )
        await self._update(job_id, progress=STAGE_BOUNDS["assignments"][1],
                            message=STAGE_DONE_MESSAGES["assignments"], assignments_path=str(path))
        return final_assignments

    async def _run_validation(
        self, job_id, req_doc, task_doc, dep_doc, member_dir, final_assignments, base_client, use_llm_verification,
        project_due_date: Optional[date] = None, reference_date: Optional[date] = None,
    ):
        await self._update(job_id, current_step="validation", progress=STAGE_BOUNDS["validation"][0],
                            message=STAGE_START_MESSAGES["validation"])
        assignments_map: Dict[str, str] = {
            fa.task_id: fa.assigned_member_id for fa in final_assignments if fa.assigned_member_id
        }
        with pipeline_stage("validation"):
            if use_llm_verification:
                client = timed_client(base_client, "validation")
                report = await validate_project_plan_with_llm_verification(
                    req_doc.requirements, task_doc.tasks, dep_doc.dependencies, member_dir.members,
                    assignments_map, client=client, final_assignments=final_assignments,
                    reference_date=reference_date, default_due_date=project_due_date,
                )
            else:
                report = validate_project_plan(
                    req_doc.requirements, task_doc.tasks, dep_doc.dependencies, member_dir.members, assignments_map,
                    final_assignments=final_assignments,
                    reference_date=reference_date, default_due_date=project_due_date,
                )
        path = save_validation_report(report, output_dir=self._resolve_output_dir(VALIDATION_OUTPUT_DIR, "validation"))
        await self._update(job_id, progress=STAGE_BOUNDS["validation"][1],
                            message=STAGE_DONE_MESSAGES["validation"], validation_path=str(path))
        return report

    async def _run_finalize(
        self, job_id, project, req_doc, task_doc, dep_doc, member_dir, final_assignments, report,
        reference_date: Optional[date] = None,
    ):
        await self._update(job_id, current_step="finalize", progress=STAGE_BOUNDS["finalize"][0],
                            message=STAGE_START_MESSAGES["finalize"])
        with pipeline_stage("finalize"):
            output = assemble_final_output(
                req_doc, task_doc, dep_doc, member_dir, final_assignments, report, project_name=project.name,
                start_date=project.start_date, due_date=project.due_date,
                planning_reference_date=reference_date,
            )
        path = save_final_output(output, output_dir=self._resolve_output_dir(FINAL_OUTPUT_DIR, "final_output"))

        await self._update(
            job_id, status="completed", completed_at=datetime.now(timezone.utc),
            progress=100, message=STAGE_DONE_MESSAGES["finalize"], result_path=str(path),
        )

    # --- 更新（初回生成の結果を再利用して、メンバー変更・仕様変更を反映する） ---

    def update_summary_path(self, job_id: str) -> Path:
        return self._resolve_output_dir(JOB_OUTPUT_DIR, "updates") / f"{job_id}.update.json"

    def schedule_update(self, job_id: str, source_job_id: str, mode: UpdateMode, **kwargs) -> None:
        """更新ジョブをバックグラウンドで開始する（`schedule`と同じく即座に戻る）"""
        task = asyncio.create_task(self.run_update_job(job_id, source_job_id, mode, **kwargs))
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)

    async def run_update_job(
        self,
        job_id: str,
        source_job_id: str,
        mode: UpdateMode,
        *,
        reassign_scope: ReassignScope = "unassigned",
        task_ids: Sequence[str] = (),
        client_overrides: Optional[Dict[str, Optional[str]]] = None,
        old_document_text: Optional[str] = None,
    ) -> None:
        """完了済みのジョブ(`source_job_id`)の結果を再利用して、新しいジョブとして更新する。

        - mode="members": 要件・タスク・依存関係をそのまま再利用し（LLM不使用）、
          現在のメンバー情報で割り当て・検証だけをやり直す。
        - mode="spec": 仕様書の区画を比較し、変更・追加された区画だけ要件抽出と
          タスク分解をやり直す。変わらない区画の要件・タスクはIDごと再利用する。
        どちらも、既存タスクの担当者は`reassign_scope`で明示されない限り変更しない。
        元のジョブの結果ファイルは読むだけで、書き換えない。
        """
        project = await self._load_project_for_job(job_id)
        if project is None:
            return
        if not project.members_path:
            await self._fail(job_id, "MEMBERS_NOT_CONFIGURED", "プロジェクトにメンバー情報が設定されていません。")
            return
        try:
            req_doc, task_doc, dep_doc, source_assignments = await self._load_source_documents(source_job_id)
        except (OSError, ValueError) as e:
            await self._fail(job_id, "SOURCE_NOT_AVAILABLE", f"更新元の分析結果を読み込めませんでした: {e}")
            return

        await self._update(job_id, status="running", started_at=datetime.now(timezone.utc))
        summary = UpdateSummary(mode=mode, source_job_id=source_job_id, reassign_scope=reassign_scope)
        try:
            current = current_assignments(source_assignments, client_overrides)
            before: Dict[str, Optional[str]] = {a.task_id: a.assigned_member_id for a in source_assignments}
            before.update({tid: fa.assigned_member_id for tid, fa in current.items()})

            if mode == "spec":
                base_client = resolve_llm_client()
                req_doc, task_doc, dep_doc = await self._run_spec_update(
                    job_id, project, req_doc, task_doc, dep_doc, base_client, old_document_text, summary,
                )
            else:
                summary.requirements_unchanged = len(req_doc.requirements)
                summary.tasks_unchanged = len(task_doc.tasks)
                source = await self._get_job(source_job_id)
                await self._update(
                    job_id, current_step="dependencies", progress=STAGE_BOUNDS["dependencies"][1],
                    message="前回の要件・タスク・依存関係を再利用しました（要件抽出・タスク分解は再実行していません）。",
                    requirements_path=source.requirements_path, tasks_path=source.tasks_path,
                    dependencies_path=source.dependencies_path,
                )

            member_dir = await self._run_members(job_id, project)
            task_id_set = {t.id for t in task_doc.tasks}
            preserved = {
                tid: fa for tid, fa in select_preserved(current, reassign_scope, task_ids).items()
                if tid in task_id_set
            }
            reference_date = project.start_date or date.today()
            final_assignments = await self._run_assignments(
                job_id, task_doc, dep_doc, member_dir, None, False,
                project_due_date=project.due_date, reference_date=reference_date, preserved=preserved,
            )
            summarize_assignments(summary, before, final_assignments)
            report = await self._run_validation(
                job_id, req_doc, task_doc, dep_doc, member_dir, final_assignments, None, False,
                project_due_date=project.due_date, reference_date=reference_date,
            )
            save_update_summary(summary, self.update_summary_path(job_id))
            await self._run_finalize(
                job_id, project, req_doc, task_doc, dep_doc, member_dir, final_assignments, report,
                reference_date=reference_date,
            )
        except Exception as e:  # noqa: BLE001 — 初回生成と同じく、ジョブを失敗として記録する
            logger.exception("[JOB] update %s failed", job_id)
            code, message = classify_exception(e)
            await self._fail(job_id, code, message)

    async def _get_job(self, job_id: str) -> JobModel:
        async with self._session_factory() as db:
            job = await db.get(JobModel, job_id)
        if job is None:
            raise ValueError(f"ジョブ {job_id} が見つかりません")
        return job

    async def _load_source_documents(self, source_job_id: str):
        source = await self._get_job(source_job_id)
        paths = [source.requirements_path, source.tasks_path, source.dependencies_path, source.assignments_path]
        if source.status != "completed":
            raise ValueError(f"ジョブ {source_job_id} は完了していません（状態: {source.status}）")
        if not all(paths):
            raise ValueError(f"ジョブ {source_job_id} の結果ファイルの記録が不足しています")

        def read(path: str):
            return json.loads(Path(path).read_text(encoding="utf-8"))

        return (
            RequirementDocument.model_validate(read(source.requirements_path)),
            TaskDocument.model_validate(read(source.tasks_path)),
            DependencyDocument.model_validate(read(source.dependencies_path)),
            [FinalAssignment.model_validate(a) for a in read(source.assignments_path)],
        )

    async def _run_spec_update(
        self, job_id, project, req_doc, task_doc, dep_doc, base_client, old_text, summary: UpdateSummary,
    ):
        """仕様変更: 変更・追加された区画だけ要件抽出→タスク分解をやり直し、残りは再利用する。"""
        new_text = project.document_text or ""
        await self._update(job_id, current_step="requirements", progress=STAGE_BOUNDS["requirements"][0],
                            message="前回の解析結果と仕様書を比較し、変更された部分だけ要求を抽出しています...")
        old_reqs = req_doc.requirements
        old_by_src: Dict[str, List[Requirement]] = {}
        for r in old_reqs:
            if r.source_reference and r.source_reference.source_text:
                old_by_src.setdefault(chunk_key(r.source_reference.source_text), []).append(r)

        with pipeline_stage("requirements"):
            plan = plan_chunks(old_reqs, old_text, new_text)
            chunks = plan.analyzed_chunks()
            paired_old = {chunk_key(c.text): chunk_key(old) for old, c in plan.changed}
            client = timed_client(base_client, "requirements")
            results = await gather_with_concurrency(
                [(lambda c=c: extract_requirements_from_chunk(c, client, req_doc.document_id)) for c in chunks],
                get_max_concurrency(),
            )
        summary.llm_requirement_calls = len(chunks)

        next_req = next_id("REQ", [r.id for r in old_reqs])
        reused_req_ids: set = set()
        new_reqs_by_chunk: Dict[str, List[Requirement]] = {}
        extraction_errors: List[str] = []
        for chunk, (candidates, error) in zip(chunks, results):
            if error:
                extraction_errors.append(error)
            old_pool = old_by_src.get(paired_old.get(chunk_key(chunk.text), ""), [])
            mapping = match_items(
                [f"{c.title} {c.description}" for c in candidates],
                [(r.id, f"{r.title} {r.description}") for r in old_pool],
            )
            made: List[Requirement] = []
            for i, c in enumerate(candidates):
                rid = mapping.get(i)
                if rid:
                    reused_req_ids.add(rid)
                    summary.requirements_changed.append(ItemRef(id=rid, title=c.title))
                else:
                    rid = f"REQ-{next_req:03d}"
                    next_req += 1
                    summary.requirements_added.append(ItemRef(id=rid, title=c.title))
                made.append(Requirement(id=rid, **c.model_dump()))
            new_reqs_by_chunk[chunk_key(chunk.text)] = made

        requirements: List[Requirement] = []
        unchanged_req_ids: set = set()
        for chunk in decompose_document(new_text):
            k = chunk_key(chunk.text)
            if k in new_reqs_by_chunk:
                requirements.extend(new_reqs_by_chunk.pop(k))
            elif k in old_by_src:
                for r in old_by_src.pop(k):
                    unchanged_req_ids.add(r.id)
                    requirements.append(r)
        summary.requirements_unchanged = len(unchanged_req_ids)
        current_req_ids = {r.id for r in requirements}
        summary.requirements_removed = [
            ItemRef(id=r.id, title=r.title) for r in old_reqs if r.id not in current_req_ids
        ]
        req_issues = validate_requirements(requirements, document_text=new_text)
        req_issues += [RequirementIssue(code="EXTRACTION_ERROR", message=e) for e in extraction_errors]
        req_doc = RequirementDocument(
            document_id=req_doc.document_id, requirements=requirements, issues=req_issues,
            model=getattr(client, "model", None), generated_at=datetime.now(timezone.utc).isoformat(),
        )
        path = save_requirements_document(req_doc, output_dir=self._resolve_output_dir(REQUIREMENTS_OUTPUT_DIR, "requirements"))
        await self._update(job_id, progress=STAGE_BOUNDS["requirements"][1],
                            message=STAGE_DONE_MESSAGES["requirements"], requirements_path=str(path))

        # --- タスク: 変更・追加された要件だけ分解し、似たタスクにはIDと担当者を引き継ぐ ---
        await self._update(job_id, current_step="tasks", progress=STAGE_BOUNDS["tasks"][0],
                            message="変更・追加された要件だけをタスクに分解しています...")
        to_decompose = [r for r in requirements if r.id not in unchanged_req_ids]
        vocabulary = self._load_team_skill_vocabulary(job_id, project)
        extra = {"team_skill_vocabulary": vocabulary} if vocabulary else {}
        with pipeline_stage("tasks"):
            client = timed_client(base_client, "tasks")
            decomposed = await gather_with_concurrency(
                [(lambda r=r: decompose_requirement(r, client, **extra)) for r in to_decompose],
                get_max_concurrency(),
            )
        summary.llm_task_calls = len(to_decompose)

        old_tasks = task_doc.tasks
        # 変更された区画の古い要件に属していたタスク＝IDを引き継げる候補
        changed_old_req_ids = {
            r.id for old_key in paired_old.values() for r in old_reqs
            if r.source_reference and chunk_key(r.source_reference.source_text or "") == old_key
        }
        next_task = next_id("TASK", [t.id for t in old_tasks])
        reused_task: Dict[str, Task] = {}
        added_tasks: List[Task] = []
        decomposition_errors: List[str] = []
        for req, (candidates, error) in zip(to_decompose, decomposed):
            if error:
                decomposition_errors.append(error)
            pool = [
                t for t in old_tasks
                if t.id not in reused_task and set(t.requirement_ids) & (changed_old_req_ids | {req.id})
            ]
            mapping = match_items([c.title for c in candidates], [(t.id, t.title) for t in pool])
            for i, c in enumerate(candidates):
                tid = mapping.get(i)
                if tid:
                    old = next(t for t in pool if t.id == tid)
                    reused_task[tid] = Task(id=tid, due_date=old.due_date, **c.model_dump())
                    summary.tasks_updated.append(ItemRef(id=tid, title=c.title))
                else:
                    task = Task(id=f"TASK-{next_task:03d}", **c.model_dump())
                    next_task += 1
                    added_tasks.append(task)
                    summary.tasks_added.append(ItemRef(id=task.id, title=task.title))

        # 既存タスク: 変わらない要件に1つでも紐づくものはそのまま残す（複数の要件に
        # 紐づくタスクを、一部の要件の変更だけで削除しない）。紐づく要件がすべて
        # 変更・削除され、新しい分解でも対応するタスクが無いものは「削除候補」として
        # 印を付けて残す（担当者・進捗を失わないよう、自動では削除しない）。
        removal_ids: set = set()
        merged: List[Task] = []
        for t in old_tasks:
            if t.id in reused_task:
                merged.append(reused_task[t.id])
            elif set(t.requirement_ids) & unchanged_req_ids:
                alive = [rid for rid in t.requirement_ids if rid in current_req_ids]
                merged.append(t if alive == t.requirement_ids else t.model_copy(update={"requirement_ids": alive}))
            else:
                removal_ids.add(t.id)
                merged.append(t)
                summary.tasks_removal_candidates.append(ItemRef(id=t.id, title=t.title))
        merged.extend(added_tasks)
        summary.tasks_unchanged = len(merged) - len(reused_task) - len(added_tasks) - len(removal_ids)

        # 検証フラグは全タスクについて付け直す（新旧タスク間の重複も検出するため）
        merged = [t.model_copy(update={"needs_review": False, "review_reasons": []}) for t in merged]
        requirements_by_id = {r.id: r for r in requirements}
        issues = validate_tasks(merged, requirements_by_id=requirements_by_id)
        issues += [TaskIssue(code="DECOMPOSITION_ERROR", message=e) for e in decomposition_errors]
        issues += check_task_skill_consistency(merged)
        merged = apply_review_flags(merged, issues)
        merged = [
            mark_removal_candidate(t, [rid for rid in t.requirement_ids if rid not in current_req_ids])
            if t.id in removal_ids else t
            for t in merged
        ]
        task_doc = TaskDocument(
            document_id=task_doc.document_id, tasks=merged, issues=issues,
            model=getattr(client, "model", None), generated_at=datetime.now(timezone.utc).isoformat(),
        )
        path = save_tasks_document(task_doc, output_dir=self._resolve_output_dir(TASKS_OUTPUT_DIR, "tasks"))
        await self._update(job_id, progress=STAGE_BOUNDS["tasks"][1],
                            message=STAGE_DONE_MESSAGES["tasks"], tasks_path=str(path))

        # --- 依存関係: 既存の依存を再利用し、残ったタスクについて検証し直す ---
        await self._update(job_id, current_step="dependencies", progress=STAGE_BOUNDS["dependencies"][0],
                            message="既存の依存関係を再利用して検証し直しています...")
        task_ids = [t.id for t in merged]
        id_set = set(task_ids)
        dependencies = [d for d in dep_doc.dependencies if d.from_task_id in id_set and d.to_task_id in id_set]
        dep_doc = DependencyDocument(
            document_id=dep_doc.document_id, dependencies=dependencies,
            issues=validate_dependencies(dependencies, task_ids),
            graph=DependencyGraph(task_ids, dependencies).to_dict(),
            model=dep_doc.model, generated_at=datetime.now(timezone.utc).isoformat(),
        )
        if added_tasks:
            summary.notes.append(
                f"追加されたタスク{len(added_tasks)}件の依存関係は自動では提案していません。"
                "必要な場合は「AI分析を開始」で全体を作り直してください。"
            )
        if not chunks and not summary.requirements_removed:
            summary.notes.append("仕様書に変更は見つかりませんでした。要件・タスクはすべて再利用しています。")
        path = save_dependencies_document(dep_doc, output_dir=self._resolve_output_dir(DEPENDENCIES_OUTPUT_DIR, "dependencies"))
        await self._update(job_id, progress=STAGE_BOUNDS["dependencies"][1],
                            message=STAGE_DONE_MESSAGES["dependencies"], dependencies_path=str(path))
        return req_doc, task_doc, dep_doc

    # --- 補助（毎回、短命なセッションを開いて即座にコミット・クローズする） ---

    async def _update(self, job_id: str, **fields) -> None:
        async with self._session_factory() as db:
            job = await db.get(JobModel, job_id)
            if job is None:
                logger.warning("[JOB] %s disappeared mid-run", job_id)
                return
            for key, value in fields.items():
                setattr(job, key, value)
            await db.commit()

    async def _fail(self, job_id: str, code: str, message: str) -> None:
        await self._update(
            job_id, status="failed", completed_at=datetime.now(timezone.utc),
            error_code=code, error_message=message,
        )

    def _save_assignments(self, job_id: str, assignments: List[FinalAssignment]) -> Path:
        output_dir = self._resolve_output_dir(JOB_OUTPUT_DIR, "assignments")
        output_dir.mkdir(parents=True, exist_ok=True)
        path = output_dir / f"{job_id}.assignments.json"
        path.write_text(
            json.dumps([a.model_dump(mode="json") for a in assignments], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return path


job_manager = JobManager()
