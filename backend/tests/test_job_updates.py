# backend/tests/test_job_updates.py
"""初回生成の結果を再利用した更新（POST /api/projects/{id}/update）のテスト。

- メンバー変更: 要件抽出・タスク分解を再実行せず（LLM不使用）、既存の担当者を維持したまま
  未割当タスクだけを割り当てる。明示的に指定した範囲だけ割り当て直す。
- 仕様変更: 変更・追加された区画だけ再解析し、変わらない区画の要件・タスクはID・担当者ごと
  再利用する。仕様から消えた要件のタスクは削除せず「削除候補」として残す。
"""

import asyncio
import json
import re

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from backend.db.base import Base
from backend.jobs.manager import job_manager
from backend.jobs.updates import current_assignments, plan_chunks, select_preserved
from backend.pipeline.assignment.schema import AssignmentResult, FinalAssignment
from backend.pipeline.requirements.schema import Requirement, SourceReference
from backend.services.llm import BaseLLMClient

SPEC_V1 = (
    "第1条(募集): 説明会の参加者を募集すること。\n\n"
    "第2条(会場): 説明会の会場を準備すること。\n\n"
    "第3条(集計): 終了後にアンケートを集計すること。"
)


class SpecAwareLLM(BaseLLMClient):
    """区画の本文から要件を、要件のタイトルからタスクを決定的に作るテスト用LLM。"""

    def __init__(self):
        self.model = "fake-update-model"
        self.calls = []

    def count(self, marker):
        return sum(marker in p for p in self.calls)

    async def complete(self, prompt: str, *, json_mode: bool = False) -> str:
        self.calls.append(prompt)
        if "要求・情報を過不足なく抽出してください" in prompt:
            body = prompt.split("## 区画の内容", 1)[1].strip()
            title = re.sub(r"^第\d+条\([^)]*\):\s*", "", body).rstrip("。")
            return json.dumps({"requirements": [{
                "type": "functional", "title": title, "description": body,
                "priority": "high", "origin": "explicit", "confidence": 0.9,
            }]}, ensure_ascii=False)
        if "実行可能な作業タスクに分解してください" in prompt:
            title = re.search(r"タイトル: (.+)", prompt).group(1).strip()
            skill = "Excel" if "集計" in title else "企画"
            return json.dumps({"tasks": [
                {"title": f"{title}の準備をする", "description": f"{title}の準備", "priority": "high",
                 "estimated_hours": 4, "required_skills": [skill], "acceptance_criteria": ["完了"], "confidence": 0.9},
                {"title": f"{title}を実施する", "description": f"{title}の実施", "priority": "high",
                 "estimated_hours": 4, "required_skills": [skill], "acceptance_criteria": ["完了"], "confidence": 0.9},
            ]}, ensure_ascii=False)
        if "タスク間の依存関係を提案してください" in prompt:
            return json.dumps({"dependencies": []})
        return "{}"


class ExplodingLLM(BaseLLMClient):
    model = "exploding"

    async def complete(self, prompt: str, *, json_mode: bool = False) -> str:
        raise RuntimeError("LLMは呼ばれないはず")


def _member(mid, name, skills):
    return {
        "id": mid, "name": name,
        "skills": [{"skill": s, "level": 3} for s in skills],
        "availability": {"available_hours_per_week": 40, "working_days": ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"], "current_assigned_hours": 0},
    }


@pytest_asyncio.fixture
async def db_engine(tmp_path):
    """バックグラウンドのジョブとHTTPリクエストが同時にDBへアクセスするため、
    test_jobs_api.pyと同じく本番と同じ方式（ファイルDB + 通常の接続プール）を使う。"""
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'updates.db'}", connect_args={"check_same_thread": False})
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    try:
        yield engine
    finally:
        await engine.dispose()


@pytest.fixture
def llm(db_engine, tmp_path, monkeypatch):
    import backend.routers.projects as projects_router
    from backend.pipeline.members.runner import save_member_directory as real_save

    session_maker = async_sessionmaker(bind=db_engine, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr(job_manager, "_session_factory", session_maker)
    monkeypatch.setattr(job_manager, "_output_root", tmp_path)
    monkeypatch.setattr(projects_router, "save_member_directory",
                        lambda d, output_dir=None, **kw: real_save(d, output_dir=tmp_path / "members", **kw))
    client = SpecAwareLLM()
    monkeypatch.setattr("backend.jobs.manager.resolve_llm_client", lambda: client)
    return client


async def _poll(client, job_id):
    for _ in range(300):
        body = (await client.get(f"/api/jobs/{job_id}")).json()
        if body["status"] in ("completed", "failed"):
            return body
        await asyncio.sleep(0.01)
    raise AssertionError("job did not finish")


async def _setup(client, members):
    assert (await client.post("/api/teams", json={"name": "T", "admin_display_name": "A"})).status_code == 201
    project_id = (await client.post("/api/projects", json={"name": "説明会"})).json()["id"]
    assert (await client.put(f"/api/projects/{project_id}/members", json={"members": members})).status_code == 200
    job_id = (await client.post(f"/api/projects/{project_id}/generate", json={"document_text": SPEC_V1})).json()["job_id"]
    assert (await _poll(client, job_id))["status"] == "completed"
    return project_id, job_id


async def _result(client, job_id):
    out = (await client.get(f"/api/jobs/{job_id}/result")).json()
    tasks = {t["id"]: t for t in out["tasks"]}
    assigned = {a["task_id"]: a["assigned_member_id"] for a in out["assignments"]}
    return out, tasks, assigned


async def _update(client, project_id, body):
    resp = await client.post(f"/api/projects/{project_id}/update", json=body)
    assert resp.status_code == 202, resp.text
    job_id = resp.json()["job_id"]
    status = await _poll(client, job_id)
    status["_error"] = (await client.get(f"/api/jobs/{job_id}/error")).json()
    return job_id, status


# ─── メンバー変更 ──────────────────────────────────────────────────────────

async def test_member_added_keeps_existing_assignees_and_fills_unassigned_tasks(client, llm, monkeypatch):
    project_id, job1 = await _setup(client, [_member("M-1", "企画担当", ["企画"])])
    _, tasks1, assigned1 = await _result(client, job1)
    excel_tasks = [tid for tid, t in tasks1.items() if t["required_skills"] == ["Excel"]]
    assert excel_tasks and all(assigned1[t] is None for t in excel_tasks)  # Excel担当がいないので未割当
    kept = {tid: mid for tid, mid in assigned1.items() if mid}
    assert kept

    await client.put(f"/api/projects/{project_id}/members", json={"members": [
        _member("M-1", "企画担当", ["企画"]), _member("M-2", "集計担当", ["Excel", "企画"]),
    ]})
    # メンバー変更だけではLLM（要件抽出・タスク分解）を呼ばない
    monkeypatch.setattr("backend.jobs.manager.resolve_llm_client", lambda: ExplodingLLM())
    calls_before = len(llm.calls)
    job2, status = await _update(client, project_id, {"source_job_id": job1, "mode": "members"})
    assert status["status"] == "completed", status["_error"]
    assert len(llm.calls) == calls_before

    _, tasks2, assigned2 = await _result(client, job2)
    assert set(tasks2) == set(tasks1)  # タスクID・件数は同じ（再生成していない）
    for tid, mid in kept.items():
        assert assigned2[tid] == mid  # M-2の方が空いていても、既存の担当者は変えない
    assert all(assigned2[t] == "M-2" for t in excel_tasks)  # 未割当タスクに新メンバーが入る

    summary = (await client.get(f"/api/jobs/{job2}/update-summary")).json()
    assert summary["mode"] == "members"
    assert summary["assignments_kept"] == len(kept)
    assert {c["task_id"] for c in summary["assignments_changed"]} == set(excel_tasks)
    assert summary["llm_requirement_calls"] == 0 and summary["llm_task_calls"] == 0
    # 元のジョブの結果は変わらない
    _, _, assigned1_again = await _result(client, job1)
    assert assigned1_again == assigned1


async def test_explicit_reassign_only_changes_selected_tasks(client, llm):
    project_id, job1 = await _setup(client, [_member("M-1", "企画担当", ["企画", "Excel"])])
    _, _, assigned1 = await _result(client, job1)
    assert all(assigned1.values())
    await client.put(f"/api/projects/{project_id}/members", json={"members": [
        _member("M-1", "企画担当", ["企画", "Excel"]), _member("M-2", "新人", ["企画", "Excel"]),
    ]})
    target = sorted(assigned1)[-1]
    job2, status = await _update(client, project_id, {
        "source_job_id": job1, "mode": "members", "reassign_scope": "selected", "task_ids": [target],
    })
    assert status["status"] == "completed", status["_error"]
    _, _, assigned2 = await _result(client, job2)
    assert assigned2[target] == "M-2"  # 指定したタスクは負荷の低いM-2に割り当て直される
    assert all(assigned2[t] == "M-1" for t in assigned1 if t != target)


async def test_manual_overrides_from_the_screen_are_kept(client, llm):
    project_id, job1 = await _setup(client, [_member("M-1", "企画担当", ["企画", "Excel"])])
    _, _, assigned1 = await _result(client, job1)
    tid = sorted(assigned1)[0]
    job2, _ = await _update(client, project_id, {
        "source_job_id": job1, "mode": "members", "current_assignments": {tid: None},
    })
    out, _, assigned2 = await _result(client, job2)
    assert assigned2[tid] is None  # 画面で外した担当者を、更新で勝手に戻さない
    fa = next(a for a in out["assignments"] if a["task_id"] == tid)
    assert fa["decided_by"] == "human"


# ─── 仕様変更 ─────────────────────────────────────────────────────────────

async def test_spec_change_reuses_unchanged_parts_and_keeps_removed_tasks_as_candidates(client, llm):
    project_id, job1 = await _setup(client, [_member("M-1", "担当", ["企画", "Excel"])])
    out1, tasks1, assigned1 = await _result(client, job1)
    removed_req = next(r["id"] for r in out1["requirements"] if "アンケートを集計" in r["title"])
    first_article = {tid for tid, t in tasks1.items() if "参加者を募集" in t["title"]}
    third_article = {tid for tid, t in tasks1.items() if "アンケートを集計" in t["title"]}
    assert len(first_article) == 2 and len(third_article) == 2

    spec_v2 = (
        "第1条(募集): 説明会の参加者を募集すること。\n\n"
        "第2条(会場): 説明会の会場を予約し、機材を準備すること。\n\n"
        "第4条(報告): 開催結果を報告書にまとめること。"
    )
    calls_before = len(llm.calls)
    job2, status = await _update(client, project_id, {"source_job_id": job1, "mode": "spec", "document_text": spec_v2})
    assert status["status"] == "completed", status["_error"]
    new_calls = llm.calls[calls_before:]
    # 変更（第2条）と追加（第4条）の2区画だけ要件抽出し、その2要件だけ分解する
    assert sum("要求・情報を過不足なく抽出してください" in p for p in new_calls) == 2
    assert sum("実行可能な作業タスクに分解してください" in p for p in new_calls) == 2
    # 変わらない第1条の区画・要件はLLMに送らない
    assert not any("第1条(募集)" in p for p in new_calls)
    assert not any("タイトル: 説明会の参加者を募集すること" in p for p in new_calls)

    out, tasks2, assigned2 = await _result(client, job2)
    for tid in first_article:  # 変わらない区画のタスクはID・内容・担当者を維持
        assert tasks2[tid]["title"] == tasks1[tid]["title"]
        assert assigned2[tid] == assigned1[tid]
    for tid in third_article:  # 仕様から消えた要件のタスクは削除せず、削除候補として残す
        assert tid in tasks2 and assigned2[tid] == assigned1[tid]
        assert tasks2[tid]["needs_review"]
        assert any("SOURCE_REQUIREMENT_REMOVED" in r for r in tasks2[tid]["review_reasons"])
    assert len(tasks2) == len(set(tasks2))  # IDの重複なし
    assert any("報告書" in t["title"] for t in tasks2.values())
    new_ids = set(tasks2) - set(tasks1)
    assert all(int(t.split("-")[1]) > max(int(x.split("-")[1]) for x in tasks1) for t in new_ids)

    summary = (await client.get(f"/api/jobs/{job2}/update-summary")).json()
    assert summary["llm_requirement_calls"] == 2 and summary["llm_task_calls"] == 2
    assert [r["title"] for r in summary["requirements_added"]] == ["開催結果を報告書にまとめること"]
    assert len(summary["requirements_changed"]) + len(summary["requirements_added"]) == 2
    assert {t["id"] for t in summary["tasks_removal_candidates"]} == third_article
    assert [r["id"] for r in summary["requirements_removed"]] == [removed_req]
    assert removed_req not in {r["id"] for r in out["requirements"]}


async def test_same_spec_update_twice_does_not_duplicate_tasks(client, llm):
    project_id, job1 = await _setup(client, [_member("M-1", "担当", ["企画", "Excel"])])
    _, tasks1, assigned1 = await _result(client, job1)
    calls_before = len(llm.calls)
    job2, _ = await _update(client, project_id, {"source_job_id": job1, "mode": "spec", "document_text": SPEC_V1})
    job3, _ = await _update(client, project_id, {"source_job_id": job2, "mode": "spec", "document_text": SPEC_V1})
    assert len(llm.calls) == calls_before  # 変更が無ければLLMを呼ばない
    _, tasks3, assigned3 = await _result(client, job3)
    assert set(tasks3) == set(tasks1) and assigned3 == assigned1
    summary = (await client.get(f"/api/jobs/{job3}/update-summary")).json()
    assert summary["tasks_added"] == [] and summary["tasks_removal_candidates"] == []


async def test_task_linked_to_another_requirement_is_not_a_removal_candidate(client, llm, tmp_path):
    project_id, job1 = await _setup(client, [_member("M-1", "担当", ["企画", "Excel"])])
    out1, tasks1, _ = await _result(client, job1)
    req_募集 = next(r["id"] for r in out1["requirements"] if "参加者を募集" in r["title"])
    tid = next(t for t, v in tasks1.items() if "アンケートを集計" in v["title"])
    # 第3条のタスクを、第1条の要件にも紐づける（複数要件に関連するタスク）
    from backend.models.job import JobModel
    async with job_manager._session_factory() as db:
        tasks_path = (await db.get(JobModel, job1)).tasks_path
    data = json.loads(open(tasks_path, encoding="utf-8").read())
    for t in data["tasks"]:
        if t["id"] == tid:
            t["requirement_ids"].append(req_募集)
    open(tasks_path, "w", encoding="utf-8").write(json.dumps(data, ensure_ascii=False))

    spec_v2 = SPEC_V1.replace("\n\n第3条(集計): 終了後にアンケートを集計すること。", "")
    job2, _ = await _update(client, project_id, {"source_job_id": job1, "mode": "spec", "document_text": spec_v2})
    _, tasks2, _ = await _result(client, job2)
    assert not any("SOURCE_REQUIREMENT_REMOVED" in r for r in tasks2[tid]["review_reasons"])
    assert tasks2[tid]["requirement_ids"] == [req_募集]  # 消えた要件のIDだけ外れる


async def test_failed_update_leaves_source_job_intact(client, llm, monkeypatch):
    project_id, job1 = await _setup(client, [_member("M-1", "担当", ["企画", "Excel"])])
    before = (await client.get(f"/api/jobs/{job1}/result")).json()

    class Broken(BaseLLMClient):
        model = "broken"

        async def complete(self, prompt, *, json_mode=False):
            raise RuntimeError("simulated crash")

    monkeypatch.setattr("backend.jobs.manager.resolve_llm_client", lambda: Broken())
    job2, status = await _update(client, project_id, {
        "source_job_id": job1, "mode": "spec", "document_text": SPEC_V1 + "\n\n第9条(追加): 追加作業をすること。",
    })
    assert status["status"] == "failed"
    assert (await client.get(f"/api/jobs/{job1}/result")).json() == before
    assert (await client.get(f"/api/jobs/{job2}/result")).status_code == 409


async def test_update_requires_completed_source_job_of_same_project(client, llm):
    project_id, job1 = await _setup(client, [_member("M-1", "担当", ["企画"])])
    other = (await client.post("/api/projects", json={"name": "別"})).json()["id"]
    await client.put(f"/api/projects/{other}/members", json={"members": [_member("M-1", "担当", ["企画"])]})
    resp = await client.post(f"/api/projects/{other}/update", json={"source_job_id": job1, "mode": "members"})
    assert resp.status_code == 404
    resp = await client.post(f"/api/projects/{project_id}/update", json={"source_job_id": job1, "mode": "spec"})
    assert resp.status_code == 400  # 仕様変更には本文が必要
    assert (await client.get(f"/api/jobs/{job1}/update-summary")).status_code == 404  # 初回生成は更新ジョブではない


# ─── 部品の単体テスト ─────────────────────────────────────────────────────

def _req(rid, text, section=None):
    return Requirement(
        id=rid, type="functional", title=rid, description=text, origin="explicit", confidence=0.9,
        source_reference=SourceReference(document_id="d", section=section, paragraph="chunk", source_text=text),
    )


def test_plan_chunks_classifies_unchanged_changed_added_and_removed():
    old = "第1条(A): Aをする。\n\n第2条(B): Bをする。\n\n第3条(C): Cをする。"
    new = "第1条(A): Aをする。\n\n第2条(B): Bを丁寧にする。\n\n第5条(E): 全く別の内容を書く。"
    old_reqs = [_req("REQ-001", "第1条(A): Aをする。", "第1条(A)"),
                _req("REQ-002", "第2条(B): Bをする。", "第2条(B)"),
                _req("REQ-003", "第3条(C): Cをする。", "第3条(C)")]
    plan = plan_chunks(old_reqs, old, new)
    assert [c.text for c in plan.unchanged] == ["第1条(A): Aをする。"]
    assert [(o, c.text) for o, c in plan.changed] == [("第2条(B): Bをする。", "第2条(B): Bを丁寧にする。")]
    assert [c.text for c in plan.added] == ["第5条(E): 全く別の内容を書く。"]
    assert plan.removed == ["第3条(C): Cをする。"]


def test_plan_chunks_with_identical_text_has_nothing_to_analyze():
    text = "第1条(A): Aをする。\n\n第2条(B): Bをする。"
    plan = plan_chunks([_req("REQ-001", "第1条(A): Aをする。")], text, text)
    assert plan.analyzed_chunks() == [] and plan.removed == []


def _fa(tid, mid):
    rec = AssignmentResult(task_id=tid, recommended_member_id=mid, status="recommended" if mid else "no_suitable_member")
    return FinalAssignment(task_id=tid, assigned_member_id=mid, decided_by="ai", ai_recommendation=rec)


def test_current_assignments_and_scope_selection():
    source = [_fa("TASK-001", "M-1"), _fa("TASK-002", None), _fa("TASK-003", "M-1")]
    current = current_assignments(source, {"TASK-003": "M-2", "TASK-404": "M-9"})
    assert set(current) == {"TASK-001", "TASK-003"}  # 未割当は対象外、存在しないタスクの上書きは無視
    assert current["TASK-003"].assigned_member_id == "M-2" and current["TASK-003"].decided_by == "human"
    assert set(select_preserved(current, "unassigned")) == {"TASK-001", "TASK-003"}
    assert set(select_preserved(current, "selected", ["TASK-001"])) == {"TASK-003"}
    assert select_preserved(current, "all") == {}
