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
from typing import Callable, Dict, List, Optional, Set, Tuple

from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.session import AsyncSessionLocal
from backend.jobs.adapters import task_to_assignment_task
from backend.jobs.errors import classify_exception
from backend.jobs.timing import pipeline_stage, timed_client, timed_embedding_client
from backend.models.job import JobModel
from backend.models.project import ProjectModel
from backend.pipeline.assignment.audit import summarize_assignment_audit
from backend.pipeline.assignment.deadline import AssignmentLedger
from backend.pipeline.assignment.override import accept_recommendation
from backend.pipeline.assignment.runner import run_assignment
from backend.pipeline.assignment.schema import FinalAssignment
from backend.pipeline.dependencies.runner import OUTPUT_DIR as DEPENDENCIES_OUTPUT_DIR
from backend.pipeline.dependencies.runner import run_dependency_pipeline, save_dependencies_document
from backend.pipeline.final_output.assembler import assemble_final_output
from backend.pipeline.final_output.runner import OUTPUT_DIR as FINAL_OUTPUT_DIR
from backend.pipeline.final_output.runner import save_final_output
from backend.pipeline.members.runner import load_member_directory
from backend.pipeline.requirements.runner import OUTPUT_DIR as REQUIREMENTS_OUTPUT_DIR
from backend.pipeline.requirements.runner import run_requirements_pipeline, save_requirements_document
from backend.pipeline.tasks.runner import OUTPUT_DIR as TASKS_OUTPUT_DIR
from backend.pipeline.tasks.runner import run_task_decomposition_pipeline, save_tasks_document
from backend.pipeline.tasks.skill_vocabulary import build_team_skill_vocabulary
from backend.pipeline.validation.runner import OUTPUT_DIR as VALIDATION_OUTPUT_DIR
from backend.pipeline.validation.runner import (
    save_validation_report,
    validate_project_plan,
    validate_project_plan_with_llm_verification,
)
from backend.services.llm import get_llm_client
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
    ):
        await self._update(job_id, current_step="assignments", progress=STAGE_BOUNDS["assignments"][0],
                            message=STAGE_START_MESSAGES["assignments"])
        assignment_client = timed_client(base_client, "assignments") if use_llm_reasoning else None

        # Assignment Audit用: メンバーディレクトリの読み込み時に無効なレコードが
        # あったかどうか（LOAD_ERROR）を、未割当理由の分類に使う。判定ロジック
        # 自体（filters.py/scoring.py/workload_balancing.py）には影響しない。
        member_load_errors = any(issue.code == "LOAD_ERROR" for issue in member_dir.issues)

        with pipeline_stage("assignments"):
            # member_dir.membersはここで1回だけ読み込まれたリストを、タスクの数だけ
            # 再利用する（B: メンバー情報を毎回DBから読み直したりはしない）。
            assignment_tasks = [
                task_to_assignment_task(task, dep_doc.dependencies, default_due_date=project_due_date)
                for task in task_doc.tasks
            ]

            # 負荷率100%以内・負荷の均一化・期限までの累積負荷は、いずれも前のタスクの
            # 割当結果に依存するため、タスクを1件ずつ逐次実行し、割り当てた工数を
            # 台帳(AssignmentLedger)に記録していく（以前はタスクごとに独立に並列実行して
            # いたため、割当が特定のメンバーに累積しても検出できなかった）。
            # 順序は期限の早い順（EDF。期限なしは最後、同じ期限は元の順）。
            # 負荷の基準は、納期情報があれば計画期間（基準日〜最も遅い期限）、無ければ
            # 従来通り1週間（Validation CHECK 4と同じ定義）。
            # 結果はtask_doc.tasksと同じ順に並べて返す。
            dues = [t.due_date for t in assignment_tasks if t.due_date]
            use_period = reference_date is not None and bool(dues)
            ledger = AssignmentLedger(
                reference_date=reference_date if use_period else None,
                period_end=max(dues) if use_period else None,
            )
            order = sorted(
                range(len(assignment_tasks)),
                key=lambda i: (assignment_tasks[i].due_date or date.max, i),
            )
            results: List[Optional[FinalAssignment]] = [None] * len(assignment_tasks)
            for i in order:
                at = assignment_tasks[i]
                # 以前のgather_with_concurrency（既定の同時実行数1）と同じく、各タスクの
                # 割当を個別のasyncio.Taskとして実行する。LLM補足説明が無効な場合
                # run_assignmentは一度も中断しないため、直接awaitすると割当ループの間
                # イベントループへ制御が戻らず、ジョブ状態のポーリング等に応答できなくなる。
                result = await asyncio.create_task(run_assignment(
                    at, member_dir.members, client=assignment_client,
                    member_load_errors=member_load_errors, ledger=ledger,
                ))
                fa = accept_recommendation(result)
                if fa.assigned_member_id:
                    ledger.commit(fa.assigned_member_id, at.estimated_hours, at.due_date)
                results[i] = fa
            final_assignments: List[FinalAssignment] = results  # type: ignore[assignment]

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
