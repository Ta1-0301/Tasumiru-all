# backend/jobs/updates.py
"""
初回生成済みの結果を再利用して、メンバー変更・仕様変更を反映するための部品。

ここに置くのは「どの要件・タスク・割り当てを再利用し、どれを作り直すか」を
決める決定的な処理（LLM不使用）だけ。LLMの呼び出しやジョブの進捗更新は
`backend.jobs.manager.JobManager.run_update_job`が行う。

方針:
- 既存の結果ファイル（要件・タスク・依存関係・割り当て）は読むだけで上書きしない。
  更新結果は新しいジョブとして別ファイルに保存する（失敗しても元の結果は残る）。
- 仕様変更の差分は、要件抽出と同じ`decompose_document`の区画（チャンク）単位で取る。
  区画の本文が変わっていなければ、その区画から抽出済みの要件とタスクをそのまま使う
  （LLMは毎回同じ文面を返すとは限らないため、要件の文面ではなく原文で比較する）。
- 既存タスクの担当者は、明示的に再割り当てを指示されない限り変更しない。
"""

from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass, field
from datetime import date
from difflib import SequenceMatcher
from pathlib import Path
from typing import Dict, Iterable, List, Literal, Optional, Sequence, Set, Tuple

from pydantic import BaseModel, Field

from backend.jobs.adapters import task_to_assignment_task
from backend.pipeline.assignment.deadline import AssignmentLedger
from backend.pipeline.assignment.override import accept_recommendation, override_recommendation
from backend.pipeline.assignment.runner import run_assignment
from backend.pipeline.assignment.schema import FinalAssignment
from backend.pipeline.dependencies.schema import DependencyDocument
from backend.pipeline.members.schema import MemberDirectory
from backend.pipeline.requirements.schema import Requirement
from backend.pipeline.tasks.schema import Task, TaskDocument
from backend.services.pipeline.schema import DocumentChunk
from backend.services.pipeline.structure import decompose_document

# 変更された区画どうしを「同じ区画の書き換え」とみなす本文の類似度
CHUNK_PAIR_SIMILARITY = 0.5
# 変更された区画の中で、新旧の要件・タスクを「同じもの」とみなしてIDを引き継ぐ類似度
ITEM_MATCH_SIMILARITY = 0.6

REMOVAL_CANDIDATE_CODE = "SOURCE_REQUIREMENT_REMOVED"
MANUAL_OVERRIDE_REASON = "画面で手動変更された担当者を維持"

UpdateMode = Literal["members", "spec"]
ReassignScope = Literal["unassigned", "all", "selected"]


# ─── 割り当て（初回生成と更新で共通） ───────────────────────────────────────

async def assign_tasks(
    task_doc: TaskDocument,
    dep_doc: DependencyDocument,
    member_dir: MemberDirectory,
    *,
    client=None,
    project_due_date: Optional[date] = None,
    reference_date: Optional[date] = None,
    preserved: Optional[Dict[str, FinalAssignment]] = None,
) -> List[FinalAssignment]:
    """タスクを期限の早い順（EDF）に1件ずつ割り当てる。

    `preserved`に含まれるタスクは割り当てを変更せずそのまま返し、担当者がいれば
    その工数を先に台帳(AssignmentLedger)へ記録する（後続タスクの100%上限・
    負荷の均一化・期限判定は、既存の割り当てを含めた負荷で行われる）。
    `preserved`が空なら、初回生成と完全に同じ処理になる。
    結果は`task_doc.tasks`と同じ順に並べて返す。
    """
    preserved = preserved or {}
    member_load_errors = any(issue.code == "LOAD_ERROR" for issue in member_dir.issues)
    member_ids = {m.id for m in member_dir.members}

    assignment_tasks = [
        task_to_assignment_task(task, dep_doc.dependencies, default_due_date=project_due_date)
        for task in task_doc.tasks
    ]
    # 負荷の基準は、納期情報があれば計画期間（基準日〜最も遅い期限）、無ければ1週間。
    dues = [t.due_date for t in assignment_tasks if t.due_date]
    use_period = reference_date is not None and bool(dues)
    ledger = AssignmentLedger(
        reference_date=reference_date if use_period else None,
        period_end=max(dues) if use_period else None,
    )

    results: List[Optional[FinalAssignment]] = [None] * len(assignment_tasks)
    for i, at in enumerate(assignment_tasks):
        kept = preserved.get(at.task_id)
        if kept is None:
            continue
        results[i] = kept
        # 現在のメンバーにいない担当者は台帳に載せない（Validationの制約違反として報告される）
        if kept.assigned_member_id in member_ids:
            ledger.commit(kept.assigned_member_id, at.estimated_hours, at.due_date)

    order = sorted(
        range(len(assignment_tasks)),
        key=lambda i: (assignment_tasks[i].due_date or date.max, i),
    )
    for i in order:
        if results[i] is not None:
            continue
        at = assignment_tasks[i]
        # 各タスクの割当を個別のasyncio.Taskとして実行する。LLM補足説明が無効な場合
        # run_assignmentは一度も中断しないため、直接awaitすると割当ループの間
        # イベントループへ制御が戻らず、ジョブ状態のポーリング等に応答できなくなる。
        result = await asyncio.create_task(run_assignment(
            at, member_dir.members, client=client,
            member_load_errors=member_load_errors, ledger=ledger,
        ))
        fa = accept_recommendation(result)
        if fa.assigned_member_id:
            ledger.commit(fa.assigned_member_id, at.estimated_hours, at.due_date)
        results[i] = fa
    return results  # type: ignore[return-value]


def current_assignments(
    source: Sequence[FinalAssignment],
    client_overrides: Optional[Dict[str, Optional[str]]] = None,
) -> Dict[str, FinalAssignment]:
    """更新前の「現在の割り当て」を作る。

    - 保存済みの割り当て（担当者がいるもの）をそのまま使う。
    - 画面で手動変更された担当者（`client_overrides`、未割当にした場合はNone）を
      上書きとして反映する（画面の手動変更はブラウザにしか保存されていないため）。
    - 担当者がいない保存済みの割り当ては含めない（＝更新時に割り当て直す対象になる）。
    """
    by_task = {a.task_id: a for a in source}
    current: Dict[str, FinalAssignment] = {
        a.task_id: a for a in source if a.assigned_member_id
    }
    for task_id, member_id in (client_overrides or {}).items():
        base = by_task.get(task_id)
        if base is None:
            continue
        current[task_id] = override_recommendation(base.ai_recommendation, member_id or None, MANUAL_OVERRIDE_REASON)
    return current


def select_preserved(
    current: Dict[str, FinalAssignment],
    scope: ReassignScope,
    task_ids: Iterable[str] = (),
) -> Dict[str, FinalAssignment]:
    """再割り当ての範囲に応じて、変更しない割り当てを選ぶ。

    - unassigned: 現在の割り当てをすべて維持する（未割当・新規タスクだけ割り当てる）
    - selected:   指定されたタスクだけ割り当て直し、それ以外は維持する
    - all:        すべて割り当て直す（ユーザーが明示的に指示した場合のみ）
    """
    if scope == "all":
        return {}
    if scope == "selected":
        selected = set(task_ids)
        return {tid: a for tid, a in current.items() if tid not in selected}
    return dict(current)


# ─── 仕様変更の差分（区画単位） ────────────────────────────────────────────

def chunk_key(text: str) -> str:
    """区画本文の比較用キー（空白の違いだけは無視する）"""
    return re.sub(r"\s+", " ", text or "").strip()


def _similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, a, b).ratio()


def _body(text: str, heading: Optional[str]) -> str:
    """区画の本文から先頭の見出し（第N条(…)など）を除く。見出しの書式が共通なだけの
    無関係な区画どうしを「似ている」と判定しないため。"""
    k = chunk_key(text)
    if heading and k.startswith(heading):
        k = k[len(heading):].lstrip(":： ")
    return k


@dataclass
class ChunkPlan:
    """新しい仕様書の各区画を、前回の解析結果と照らし合わせた結果"""

    unchanged: List[DocumentChunk] = field(default_factory=list)
    changed: List[Tuple[str, DocumentChunk]] = field(default_factory=list)  # (前回の区画本文, 新しい区画)
    added: List[DocumentChunk] = field(default_factory=list)
    removed: List[str] = field(default_factory=list)  # 前回の区画本文

    def analyzed_chunks(self) -> List[DocumentChunk]:
        """LLMで要件を抽出し直す区画（変更・追加された区画）"""
        return [c for _, c in self.changed] + self.added


def plan_chunks(old_requirements: Sequence[Requirement], old_text: Optional[str], new_text: str) -> ChunkPlan:
    """新旧の仕様書を区画単位で比較する。

    前回どの区画を解析したかは、要件の`source_reference.source_text`（＝区画の本文）
    から分かる。要件が1件も抽出されなかった区画は`old_text`（更新前のプロジェクトの
    仕様書本文）から判断し、本文が同じなら再解析しない。
    """
    old_with_reqs: Dict[str, str] = {}
    old_headings: Dict[str, Optional[str]] = {}
    for r in old_requirements:
        src = r.source_reference
        if src and src.source_text:
            k = chunk_key(src.source_text)
            old_with_reqs.setdefault(k, src.source_text)
            old_headings.setdefault(k, src.section)
    known = set(old_with_reqs)
    if old_text:
        known |= {chunk_key(c.text) for c in decompose_document(old_text)}

    plan = ChunkPlan()
    pending: List[DocumentChunk] = []
    new_keys: Set[str] = set()
    for chunk in decompose_document(new_text):
        k = chunk_key(chunk.text)
        new_keys.add(k)
        if k in known:
            plan.unchanged.append(chunk)
        else:
            pending.append(chunk)

    gone = [k for k in old_with_reqs if k not in new_keys]
    # 1. 見出し（第N条など）が同じ区画は、同じ区画の書き換えとみなす
    for chunk in list(pending):
        if not chunk.heading:
            continue
        match = next((k for k in gone if old_headings.get(k) == chunk.heading), None)
        if match is not None:
            plan.changed.append((old_with_reqs[match], chunk))
            gone.remove(match)
            pending.remove(chunk)
    # 2. 本文が十分に似ている区画どうしを、似ている順に対応づける
    pairs = sorted(
        (
            (_similarity(_body(c.text, c.heading), _body(k, old_headings.get(k))), i, k)
            for i, c in enumerate(pending) for k in gone
        ),
        key=lambda x: -x[0],
    )
    used_new: Set[int] = set()
    for score, i, k in pairs:
        if score < CHUNK_PAIR_SIMILARITY or i in used_new or k not in gone:
            continue
        plan.changed.append((old_with_reqs[k], pending[i]))
        used_new.add(i)
        gone.remove(k)
    plan.added = [c for i, c in enumerate(pending) if i not in used_new]
    plan.removed = [old_with_reqs[k] for k in gone]
    return plan


def next_id(prefix: str, existing: Iterable[str]) -> int:
    """`REQ-012`/`TASK-034`のような既存IDの最大番号+1を返す（IDの再利用を避ける）"""
    numbers = [int(m.group(1)) for x in existing if (m := re.match(rf"^{prefix}-(\d+)$", x))]
    return max(numbers, default=0) + 1


def match_items(
    new_texts: Sequence[str],
    old_items: Sequence[Tuple[str, str]],
    threshold: float = ITEM_MATCH_SIMILARITY,
) -> Dict[int, str]:
    """新しい項目（文面の一覧）と古い項目（(ID, 文面)の一覧）を、文面の類似度が
    高い順に1対1で対応づける。戻り値は {新しい項目の添字: 引き継ぐ古いID}。
    """
    pairs = sorted(
        ((_similarity(n, o), i, oid) for i, n in enumerate(new_texts) for oid, o in old_items),
        key=lambda x: -x[0],
    )
    result: Dict[int, str] = {}
    used_old: Set[str] = set()
    for score, i, oid in pairs:
        if score < threshold or i in result or oid in used_old:
            continue
        result[i] = oid
        used_old.add(oid)
    return result


def mark_removal_candidate(task: Task, removed_requirement_ids: Sequence[str]) -> Task:
    """元の要件が仕様書から無くなったタスクに、削除候補の印を付ける（削除はしない）"""
    reason = (
        f"{REMOVAL_CANDIDATE_CODE}: 元の要件（{', '.join(removed_requirement_ids) or '不明'}）が"
        "更新後の仕様書に見つかりません。不要であれば手動で削除してください（担当者・進捗は保持しています）。"
    )
    return task.model_copy(update={
        "needs_review": True,
        "review_reasons": [*task.review_reasons, reason],
    })


# ─── 更新内容の記録 ────────────────────────────────────────────────────────

class ItemRef(BaseModel):
    id: str
    title: str = ""


class AssignmentChange(BaseModel):
    task_id: str
    before: Optional[str] = None
    after: Optional[str] = None


class UpdateSummary(BaseModel):
    """1回の更新で何を再利用し、何を作り直したか（GET /api/jobs/{job_id}/update-summary）"""

    mode: UpdateMode
    source_job_id: str
    reassign_scope: ReassignScope = "unassigned"
    requirements_unchanged: int = 0
    requirements_changed: List[ItemRef] = Field(default_factory=list)
    requirements_added: List[ItemRef] = Field(default_factory=list)
    requirements_removed: List[ItemRef] = Field(default_factory=list)
    tasks_unchanged: int = 0
    tasks_updated: List[ItemRef] = Field(default_factory=list)
    tasks_added: List[ItemRef] = Field(default_factory=list)
    tasks_removal_candidates: List[ItemRef] = Field(default_factory=list)
    assignments_kept: int = 0
    assignments_changed: List[AssignmentChange] = Field(default_factory=list)
    unassigned_after: List[str] = Field(default_factory=list)
    llm_requirement_calls: int = 0
    llm_task_calls: int = 0
    notes: List[str] = Field(default_factory=list)


def summarize_assignments(
    summary: UpdateSummary,
    before: Dict[str, Optional[str]],
    after: Sequence[FinalAssignment],
) -> None:
    """更新前後の担当者を比べて、維持・変更・未割当の数を記録する"""
    for fa in after:
        prev = before.get(fa.task_id)
        if fa.task_id in before and prev == fa.assigned_member_id:
            if prev:
                summary.assignments_kept += 1
        elif prev != fa.assigned_member_id:
            summary.assignments_changed.append(
                AssignmentChange(task_id=fa.task_id, before=prev, after=fa.assigned_member_id)
            )
        if not fa.assigned_member_id:
            summary.unassigned_after.append(fa.task_id)


def save_update_summary(summary: UpdateSummary, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(summary.model_dump(mode="json"), ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def load_update_summary(path: Path) -> Optional[UpdateSummary]:
    if not path.exists():
        return None
    return UpdateSummary.model_validate(json.loads(path.read_text(encoding="utf-8")))
