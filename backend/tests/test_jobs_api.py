# backend/tests/test_jobs_api.py
"""
Phase 10: ジョブ/プロジェクトAPIの統合テスト。

実際のLLM呼び出しはせず、FakeLLMClient(backend/tests/test_pipeline.py等と
同じキーワード応答型)に置き換える。ジョブはバックグラウンドの
asyncio.create_task()として実行されるため、テストではポーリングして
完了を待つ（実際のフロントエンドの利用方法と同じ）。

`backend.jobs.manager.job_manager`のDBセッション/出力先ディレクトリを
テスト用のものに差し替える（本番のコードパス自体は変更しない —
`JobManager.__init__`の`session_factory`/`output_root`引数を使うだけ）。

NOTE (テストDBについて): `backend/tests/conftest.py`の`db_engine`は
インメモリSQLite + `StaticPool`（全セッションが単一の物理接続を共有する）
を使っている。これは「1リクエストが完了してから次のリクエストが始まる」
という、既存のテストスイート全体が前提としてきた逐次アクセスでは問題ない。
しかしこのフェーズのバックグラウンドジョブは、フォアグラウンドのHTTP
リクエストと**本当に同時に**DBへアクセスする。単一の物理コネクションを
複数の非同期セッションが同時にまたぐと、SQLite側のトランザクション境界が
壊れ、コミット済みのはずの行が別セッションから見えなくなる等の不具合が
実際に発生することを確認した（本番のDBエンジンは`StaticPool`を使っておらず、
ファイルDBに対する通常の接続プールなので、この問題は本番では起こらない —
`backend/db/session.py`参照）。

そのため、このファイルのテストだけは`db_engine`を一時ファイルDB +
通常の接続プール（本番と同じ方式）で上書きする
（pytestのfixture解決規則により、このモジュール内のテストは
conftest.pyのものではなく、ここで定義した`db_engine`を使う）。
"""

import asyncio
import json

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from backend.db.base import Base
from backend.jobs.manager import job_manager
from backend.services.llm import BaseLLMClient
from backend.services.rag.embeddings import BaseEmbeddingClient

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def db_engine(tmp_path):
    """本番と同じ、ファイルDB + 通常の接続プール（StaticPoolではない）。
    このファイルの`client`/`db_session`フィクスチャ(conftest.py由来)は
    引数名で`db_engine`を解決するため、自動的にこちらが使われる。
    """
    db_path = tmp_path / "test_jobs.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}", connect_args={"check_same_thread": False})
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    try:
        yield engine
    finally:
        await engine.dispose()


class FakeLLMClient(BaseLLMClient):
    """各パイプラインステージのプロンプトに含まれる特徴的な文言で分岐する
    テスト用クライアント（実際のOllamaは一切呼ばない）。"""

    def __init__(self):
        self.model = "fake-model-v1"
        self.calls = []

    async def complete(self, prompt: str, *, json_mode: bool = False) -> str:
        self.calls.append(prompt)

        if "要求・情報を過不足なく抽出してください" in prompt:  # Phase 3 extractor
            return json.dumps({"requirements": [{
                "type": "functional", "title": "認証APIを実装する",
                "description": "招待URL方式の認証APIを実装する",
                "priority": "high", "origin": "explicit", "confidence": 0.9,
            }]}, ensure_ascii=False)

        if "実行可能な作業タスクに分解してください" in prompt:  # Phase 4 decomposer
            return json.dumps({"tasks": [{
                "title": "認証APIを実装する", "description": "APIを実装する",
                "priority": "high", "estimated_hours": 8, "required_skills": ["Python"],
                "acceptance_criteria": ["ログインできること"], "confidence": 0.9,
            }]}, ensure_ascii=False)

        if "タスク間の依存関係を提案してください" in prompt:  # Phase 5 proposer
            return json.dumps({"dependencies": []}, ensure_ascii=False)

        return "{}"


class FailingLLMClient(BaseLLMClient):
    """呼び出されると必ず(call_llm_jsonのリトライで吸収されない)例外を送出する"""

    model = "failing-model"

    async def complete(self, prompt: str, *, json_mode: bool = False) -> str:
        raise RuntimeError("simulated hard crash inside the LLM client")


@pytest_asyncio.fixture(autouse=True)
async def _redirect_member_output_to_tmp(tmp_path, monkeypatch):
    """PUT /api/projects/{id}/members はjob_managerを経由せず、Phase 6の
    save_member_directory()を直接呼ぶ。既定の(本番の)出力先ディレクトリに
    テストが書き込まないよう、ファイルの全テストで常にtmp_pathへ
    リダイレクトする（呼び出しの有無に関わらず一律に適用するautouse）。
    """
    import backend.routers.projects as projects_router
    from backend.pipeline.members.runner import save_member_directory as _real_save_member_directory

    def _save_member_directory_to_tmp(directory, output_dir=None, **kwargs):
        return _real_save_member_directory(directory, output_dir=tmp_path / "members", **kwargs)

    monkeypatch.setattr(projects_router, "save_member_directory", _save_member_directory_to_tmp)


def _configure_job_manager_for_test(db_engine, tmp_path, monkeypatch, llm_client, embedding_client=None):
    session_maker = async_sessionmaker(bind=db_engine, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr(job_manager, "_session_factory", session_maker)
    monkeypatch.setattr(job_manager, "_output_root", tmp_path)
    monkeypatch.setattr("backend.jobs.manager.resolve_llm_client", lambda: llm_client)
    if embedding_client is not None:
        monkeypatch.setattr("backend.jobs.manager.resolve_embedding_client", lambda: embedding_client)


async def _create_team(client, name="開発チームA", admin_name="管理者"):
    resp = await client.post("/api/teams", json={"name": name, "admin_display_name": admin_name})
    assert resp.status_code == 201
    return resp.json()


async def _create_project_with_members(client, document_text="認証APIを実装してください。招待URLで参加できるようにすること。"):
    resp = await client.post("/api/projects", json={"name": "テストプロジェクト", "document_text": document_text})
    assert resp.status_code == 201
    project_id = resp.json()["id"]

    members_resp = await client.put(
        f"/api/projects/{project_id}/members",
        json={"members": [{
            "id": "M-001", "name": "山田太郎",
            "skills": [{"skill": "Python", "level": 5, "experience_years": 3}],
            "availability": {"available_hours_per_week": 40, "working_days": ["Monday"], "current_assigned_hours": 0},
        }]},
    )
    assert members_resp.status_code == 200
    return project_id


# --- Members保存の衝突バグ (backend/pipeline/members/runner.py save_member_directory) の回帰テスト ---
# 修正前は保存ファイル名が`{team_id}_{秒単位タイムスタンプ}.members.json`のみで
# 決まっており、project_idが含まれていなかった。同一チームの複数プロジェクトが
# 同じ秒にMembersを保存すると、後から保存した方が先に保存した方のmembers.jsonを
# 上書きしてしまっていた。

async def test_members_do_not_leak_between_projects_in_same_team(client, db_engine, tmp_path, monkeypatch):
    """ケース1: 同一TeamにProject A/Bを作り、別々のMembersを登録した場合、
    それぞれのGET /membersが自分自身のMembersだけを返すことを確認する。"""
    await _create_team(client)

    resp_a = await client.post("/api/projects", json={"name": "Project A"})
    project_a = resp_a.json()["id"]
    resp_b = await client.post("/api/projects", json={"name": "Project B"})
    project_b = resp_b.json()["id"]

    put_a = await client.put(
        f"/api/projects/{project_a}/members",
        json={"members": [{
            "id": "M-ALICE", "name": "Alice",
            "availability": {"available_hours_per_week": 40, "working_days": ["Monday"], "current_assigned_hours": 0},
        }]},
    )
    put_b = await client.put(
        f"/api/projects/{project_b}/members",
        json={"members": [{
            "id": "M-BOB", "name": "Bob",
            "availability": {"available_hours_per_week": 30, "working_days": ["Tuesday"], "current_assigned_hours": 0},
        }]},
    )
    assert put_a.status_code == 200
    assert put_b.status_code == 200

    get_a = await client.get(f"/api/projects/{project_a}/members")
    get_b = await client.get(f"/api/projects/{project_b}/members")
    assert get_a.status_code == 200
    assert get_b.status_code == 200
    assert {m["id"] for m in get_a.json()["members"]} == {"M-ALICE"}
    assert {m["id"] for m in get_b.json()["members"]} == {"M-BOB"}


async def test_concurrent_member_saves_across_projects_do_not_collide(client, db_engine, tmp_path, monkeypatch):
    """ケース2: 同一Team内の複数ProjectへのMembers保存をほぼ同時に行っても、
    保存ファイルの衝突で片方が上書きされないことを確認する。"""
    await _create_team(client)

    resp_a = await client.post("/api/projects", json={"name": "Project A"})
    project_a = resp_a.json()["id"]
    resp_b = await client.post("/api/projects", json={"name": "Project B"})
    project_b = resp_b.json()["id"]

    payload_a = {"members": [{
        "id": "M-ALICE", "name": "Alice",
        "availability": {"available_hours_per_week": 40, "working_days": ["Monday"], "current_assigned_hours": 0},
    }]}
    payload_b = {"members": [{
        "id": "M-BOB", "name": "Bob",
        "availability": {"available_hours_per_week": 30, "working_days": ["Tuesday"], "current_assigned_hours": 0},
    }]}

    resp_put_a, resp_put_b = await asyncio.gather(
        client.put(f"/api/projects/{project_a}/members", json=payload_a),
        client.put(f"/api/projects/{project_b}/members", json=payload_b),
    )
    assert resp_put_a.status_code == 200
    assert resp_put_b.status_code == 200

    get_a = await client.get(f"/api/projects/{project_a}/members")
    get_b = await client.get(f"/api/projects/{project_b}/members")
    assert {m["id"] for m in get_a.json()["members"]} == {"M-ALICE"}
    assert {m["id"] for m in get_b.json()["members"]} == {"M-BOB"}


async def test_job_pipeline_reads_only_its_own_project_members(client, db_engine, tmp_path, monkeypatch):
    """ケース4: 同一TeamにProject A/Bが存在する状態でProject Bのジョブを実行しても、
    ジョブが読み込む/最終出力に含まれるMembersはProject B自身のものだけであり、
    Project AのMembers(Alice)が混入しないことを確認する。"""
    _configure_job_manager_for_test(db_engine, tmp_path, monkeypatch, FakeLLMClient())
    await _create_team(client)

    resp_a = await client.post("/api/projects", json={"name": "Project A", "document_text": "ダミー仕様書"})
    project_a = resp_a.json()["id"]
    await client.put(
        f"/api/projects/{project_a}/members",
        json={"members": [{
            "id": "M-ALICE", "name": "Alice",
            "availability": {"available_hours_per_week": 40, "working_days": ["Monday"], "current_assigned_hours": 0},
        }]},
    )

    project_b = await _create_project_with_members(
        client, document_text="認証APIを実装してください。招待URLで参加できるようにすること。"
    )

    gen_resp = await client.post(f"/api/projects/{project_b}/generate", json={})
    assert gen_resp.status_code == 202
    job_id = gen_resp.json()["job_id"]

    final_status, _ = await _poll_until_terminal(client, job_id)
    assert final_status["status"] == "completed"

    result_resp = await client.get(f"/api/jobs/{job_id}/result")
    assert result_resp.status_code == 200
    result_member_ids = {m["id"] for m in result_resp.json()["members"]}
    assert result_member_ids == {"M-001"}  # _create_project_with_membersが登録したProject B自身のMembers
    assert "M-ALICE" not in result_member_ids


async def _poll_until_terminal(client, job_id, timeout_ticks=200):
    statuses_seen = []
    for _ in range(timeout_ticks):
        resp = await client.get(f"/api/jobs/{job_id}")
        assert resp.status_code == 200
        body = resp.json()
        statuses_seen.append(body["status"])
        if body["status"] in ("completed", "failed", "cancelled"):
            return body, statuses_seen
        await asyncio.sleep(0.01)
    raise AssertionError(f"job did not reach a terminal state in time; last seen: {statuses_seen[-5:]}")


# --- 1-5, 12: full lifecycle with a mocked pipeline ---

async def test_full_job_lifecycle_with_mocked_pipeline(client, db_engine, tmp_path, monkeypatch):
    _configure_job_manager_for_test(db_engine, tmp_path, monkeypatch, FakeLLMClient())
    await _create_team(client)
    project_id = await _create_project_with_members(client)

    # 1-2: start job, receive job_id immediately (status=queued, no waiting for the pipeline)
    gen_resp = await client.post(f"/api/projects/{project_id}/generate", json={})
    assert gen_resp.status_code == 202
    body = gen_resp.json()
    assert body["status"] == "queued"
    job_id = body["job_id"]
    assert job_id

    # 3-4: poll job status; status must transition queued -> ... -> completed
    final_status, statuses_seen = await _poll_until_terminal(client, job_id)
    assert final_status["status"] == "completed"
    assert final_status["progress"] == 100
    assert final_status["current_step"] == "finalize"
    assert "queued" in statuses_seen or statuses_seen[0] in ("queued", "running")
    assert final_status["error"] is None

    # 5: retrieve final result
    result_resp = await client.get(f"/api/jobs/{job_id}/result")
    assert result_resp.status_code == 200
    result = result_resp.json()
    assert result["project"]["document_id"] == project_id
    assert len(result["requirements"]) == 1
    assert len(result["tasks"]) == 1
    assert result["validation"]["status"] in ("valid", "warning", "error")
    assert "metadata" in result and result["metadata"]["pipeline_version"]

    # stage-level data endpoints (STEP 7) are also populated
    for stage_path in ("requirements", "tasks", "dependencies", "assignments", "validation"):
        stage_resp = await client.get(f"/api/jobs/{job_id}/{stage_path}")
        assert stage_resp.status_code == 200, f"{stage_path} endpoint failed: {stage_resp.text}"


# --- 6: job failure ---

async def test_job_failure_is_reported_not_silently_swallowed(client, db_engine, tmp_path, monkeypatch):
    _configure_job_manager_for_test(db_engine, tmp_path, monkeypatch, FailingLLMClient())
    await _create_team(client)
    project_id = await _create_project_with_members(client)

    gen_resp = await client.post(f"/api/projects/{project_id}/generate", json={})
    job_id = gen_resp.json()["job_id"]

    final_status, _ = await _poll_until_terminal(client, job_id)
    assert final_status["status"] == "failed"
    assert final_status["error"] is not None
    assert final_status["error"]["code"]
    assert final_status["error"]["message"]

    # result is not available for a failed job — structured error, not the final JSON
    result_resp = await client.get(f"/api/jobs/{job_id}/result")
    assert result_resp.status_code == 409
    assert "code" in result_resp.json()["detail"]

    # the dedicated error endpoint agrees
    error_resp = await client.get(f"/api/jobs/{job_id}/error")
    assert error_resp.status_code == 200
    assert error_resp.json()["code"] == final_status["error"]["code"]


# --- 10: Ollama-style per-call failures are absorbed by the existing pipeline, not a job crash ---

async def test_llm_http_errors_are_absorbed_as_issues_not_a_job_crash(client, db_engine, tmp_path, monkeypatch):
    """既存のcall_llm_json(backend/services/pipeline/llm_json.py)はHTTPException
    をリトライ対象として吸収し、(None, エラー文言)を返す設計になっている
    （Phase 3-9のコードは変更していない）。そのため、Ollamaが504を返し続ける
    ようなケースは、ジョブそのものをクラッシュさせるのではなく、
    ドキュメント内のissuesとして記録されたままジョブは完了する。"""
    from fastapi import HTTPException

    class TimeoutLLMClient(BaseLLMClient):
        model = "timeout-model"

        async def complete(self, prompt: str, *, json_mode: bool = False) -> str:
            raise HTTPException(status_code=504, detail={"code": "LLM_TIMEOUT", "message": "timeout"})

    _configure_job_manager_for_test(db_engine, tmp_path, monkeypatch, TimeoutLLMClient())
    await _create_team(client)
    project_id = await _create_project_with_members(client)

    gen_resp = await client.post(f"/api/projects/{project_id}/generate", json={})
    job_id = gen_resp.json()["job_id"]

    final_status, _ = await _poll_until_terminal(client, job_id)
    assert final_status["status"] == "completed"  # ジョブ自体はクラッシュしない

    req_resp = await client.get(f"/api/jobs/{job_id}/requirements")
    assert req_resp.status_code == 200
    assert req_resp.json()["requirements"] == []  # 抽出できなかった
    assert any("EXTRACTION_ERROR" == i["code"] for i in req_resp.json()["issues"])


# --- 7: job not found ---

async def test_job_not_found_returns_404(client):
    await _create_team(client)
    resp = await client.get("/api/jobs/does-not-exist")
    assert resp.status_code == 404
    assert resp.json()["detail"]["code"] == "JOB_NOT_FOUND"


# --- 8: unauthorized access (missing / invalid token) ---

async def test_missing_session_cookie_is_rejected(client):
    resp = await client.get("/api/jobs/some-job-id")
    assert resp.status_code == 401
    assert resp.json()["detail"]["code"] == "UNAUTHENTICATED"


async def test_invalid_session_cookie_is_rejected(client):
    resp = await client.get("/api/jobs/some-job-id", headers={"Cookie": "tasumiru_session=not-a-real-token"})
    assert resp.status_code == 401
    assert resp.json()["detail"]["code"] == "SESSION_INVALID"


# --- 9: wrong team / valid team access ---

async def test_wrong_team_cannot_access_another_teams_job(client, db_engine, tmp_path, monkeypatch):
    """NOTE: 生成ジョブを完了させてから2つ目のチームを作る。テスト用DBは
    conftest.pyの`db_engine`(インメモリSQLite + StaticPool、単一の物理接続を
    全セッションで共有する)を使っており、バックグラウンドジョブの実行と
    無関係な前景の書き込み(別チームの作成)が本当に同時に走ると、その単一
    接続をまたいだトランザクションの取り合いが起きうる
    （本番のファイルDB接続プールでは発生しない、テスト構成固有の制約）。
    このテストの目的はチームをまたいだ認可境界の検証であり、ジョブの
    実行中に別チームを操作できることの検証ではないため、ここでは
    ジョブを完了させてから進める。
    """
    from backend.tests.conftest import new_client

    _configure_job_manager_for_test(db_engine, tmp_path, monkeypatch, FakeLLMClient())
    await _create_team(client, name="チームA")
    project_id = await _create_project_with_members(client)
    gen_resp = await client.post(f"/api/projects/{project_id}/generate", json={})
    job_id = gen_resp.json()["job_id"]
    await _poll_until_terminal(client, job_id)

    other_client = new_client(db_engine)
    async with other_client:
        await _create_team(other_client, name="チームB")

        job_resp = await other_client.get(f"/api/jobs/{job_id}")
        assert job_resp.status_code == 404
        assert job_resp.json()["detail"]["code"] == "JOB_NOT_FOUND"

        project_resp = await other_client.get(f"/api/projects/{project_id}")
        assert project_resp.status_code == 404
        assert project_resp.json()["detail"]["code"] == "PROJECT_NOT_FOUND"

    # valid (owning) team can still access it
    own_resp = await client.get(f"/api/jobs/{job_id}")
    assert own_resp.status_code == 200


# --- 11: invalid project ---

async def test_generate_for_nonexistent_project_returns_404(client):
    await _create_team(client)
    resp = await client.post("/api/projects/does-not-exist/generate", json={})
    assert resp.status_code == 404
    assert resp.json()["detail"]["code"] == "PROJECT_NOT_FOUND"


# --- preconditions: document / members must be configured before generation ---

async def test_generate_without_document_text_returns_400(client):
    await _create_team(client)
    create_resp = await client.post("/api/projects", json={"name": "空のプロジェクト"})
    project_id = create_resp.json()["id"]

    resp = await client.put(
        f"/api/projects/{project_id}/members",
        json={"members": [{"id": "M-001", "name": "山田太郎", "availability": {"available_hours_per_week": 40}}]},
    )
    assert resp.status_code == 200

    gen_resp = await client.post(f"/api/projects/{project_id}/generate", json={})
    assert gen_resp.status_code == 400
    assert gen_resp.json()["detail"]["code"] == "DOCUMENT_NOT_SET"


async def test_generate_without_members_returns_400(client):
    await _create_team(client)
    create_resp = await client.post("/api/projects", json={"name": "p", "document_text": "仕様書"})
    project_id = create_resp.json()["id"]

    gen_resp = await client.post(f"/api/projects/{project_id}/generate", json={})
    assert gen_resp.status_code == 400
    assert gen_resp.json()["detail"]["code"] == "MEMBERS_NOT_CONFIGURED"


# --- result endpoint before completion ---

async def test_result_before_completion_returns_409(client, db_engine, tmp_path, monkeypatch):
    _configure_job_manager_for_test(db_engine, tmp_path, monkeypatch, FakeLLMClient())
    await _create_team(client)
    project_id = await _create_project_with_members(client)

    gen_resp = await client.post(f"/api/projects/{project_id}/generate", json={})
    job_id = gen_resp.json()["job_id"]

    # ジョブが完了する前に即座に結果を取りに行く（バックグラウンドタスクへの
    # 制御の受け渡しがまだ起きていない可能性が高いタイミング）
    result_resp = await client.get(f"/api/jobs/{job_id}/result")
    assert result_resp.status_code in (200, 409)
    if result_resp.status_code == 409:
        assert result_resp.json()["detail"]["code"] in ("JOB_NOT_COMPLETED",)

    await _poll_until_terminal(client, job_id)


# --- 実験的RAG機能: ENABLE_RAG=false（既定）は従来と完全に同一の挙動 ---


class FakeEmbeddingClient(BaseEmbeddingClient):
    def __init__(self):
        self.model = "fake-embedding-v1"
        self.calls: list[tuple[str, bool]] = []

    async def embed(self, text: str, *, is_query: bool = False) -> list[float]:
        self.calls.append((text, is_query))
        return [1.0, 0.0]


async def test_rag_disabled_by_default_produces_empty_related_sources(
    client, db_engine, tmp_path, monkeypatch,
):
    """ENABLE_RAGを明示的に設定しない（＝既定でOFF）場合、Embedding APIは
    一切呼ばれず、tasksのrelated_sourcesは空配列のまま完了する。"""
    monkeypatch.delenv("ENABLE_RAG", raising=False)
    embedding_client = FakeEmbeddingClient()
    _configure_job_manager_for_test(db_engine, tmp_path, monkeypatch, FakeLLMClient(), embedding_client)
    await _create_team(client)
    project_id = await _create_project_with_members(client)

    gen_resp = await client.post(f"/api/projects/{project_id}/generate", json={})
    job_id = gen_resp.json()["job_id"]
    final_status, _ = await _poll_until_terminal(client, job_id)

    assert final_status["status"] == "completed"
    assert embedding_client.calls == []  # RAG OFFではEmbeddingを一切呼ばない

    tasks_resp = await client.get(f"/api/jobs/{job_id}/tasks")
    assert tasks_resp.status_code == 200
    for task in tasks_resp.json()["tasks"]:
        assert task["related_sources"] == []


async def test_rag_enabled_populates_related_sources_without_breaking_pipeline(
    client, db_engine, tmp_path, monkeypatch,
):
    """ENABLE_RAG=trueでも、既存パイプラインの階層構造・出力は壊れず、
    tasksにrelated_sources(実在のchunk_id/section/similarity)が追加されるだけ
    であることを確認する（既存フィールドは変更されない）。"""
    monkeypatch.setenv("ENABLE_RAG", "true")
    embedding_client = FakeEmbeddingClient()
    _configure_job_manager_for_test(db_engine, tmp_path, monkeypatch, FakeLLMClient(), embedding_client)
    await _create_team(client)
    project_id = await _create_project_with_members(client)

    gen_resp = await client.post(f"/api/projects/{project_id}/generate", json={})
    job_id = gen_resp.json()["job_id"]
    final_status, _ = await _poll_until_terminal(client, job_id)

    assert final_status["status"] == "completed"  # RAG導入で階層構造・完了自体は壊れない
    assert len(embedding_client.calls) > 0  # ドキュメント側/クエリ側のembeddingが実際に呼ばれた

    tasks_resp = await client.get(f"/api/jobs/{job_id}/tasks")
    assert tasks_resp.status_code == 200
    tasks = tasks_resp.json()["tasks"]
    assert len(tasks) == 1
    # 既存フィールド(source_reference等)はRAGの有無に関係なく変わらない
    assert tasks[0]["source_reference"] is not None
    for source in tasks[0]["related_sources"]:
        assert source["page"] is None  # 存在しないページ番号を生成しない
        assert 0.0 <= source["similarity"] <= 1.0


# --- STEP 2: Task生成時のチームスキル語彙 ---

async def test_job_passes_team_skill_vocabulary_to_task_generation_only(client, db_engine, tmp_path, monkeypatch):
    """ジョブ開始時に読んだメンバーのスキル名が、Task分解プロンプトにだけ参考語彙として渡る。
    LLM呼び出し回数は語彙の有無で変わらない（1 Requirement = 1回のまま）。"""
    llm = FakeLLMClient()
    _configure_job_manager_for_test(db_engine, tmp_path, monkeypatch, llm)
    await _create_team(client)
    project_id = await _create_project_with_members(client)

    gen_resp = await client.post(f"/api/projects/{project_id}/generate", json={})
    final_status, _ = await _poll_until_terminal(client, gen_resp.json()["job_id"])
    assert final_status["status"] == "completed"

    task_prompts = [p for p in llm.calls if "実行可能な作業タスクに分解してください" in p]
    other_prompts = [p for p in llm.calls if "実行可能な作業タスクに分解してください" not in p]
    assert len(task_prompts) == 1  # 要件1件 → Task分解のLLM呼び出し1回
    assert "## 表記対応表" in task_prompts[0] and "\nPython\n" in task_prompts[0]
    assert all("表記対応表" not in p for p in other_prompts)
    # requirements 1 + tasks 1（タスクが1件なので依存関係のLLM呼び出しは既存仕様どおり省略される）
    assert len(llm.calls) == 2


async def test_job_runs_task_generation_without_vocabulary_when_members_file_is_unreadable(
    client, db_engine, tmp_path, monkeypatch,
):
    """語彙の読み取りに失敗しても空の語彙で成功扱いにはせず、Task生成は従来通り(語彙なし)で動き、
    members.jsonの読み込み失敗自体は既存のMembersステージがジョブの失敗として報告する。"""
    import backend.jobs.manager as manager_module

    llm = FakeLLMClient()
    _configure_job_manager_for_test(db_engine, tmp_path, monkeypatch, llm)
    await _create_team(client)
    project_id = await _create_project_with_members(client)

    def broken_loader(path):
        raise OSError("simulated unreadable members.json")

    monkeypatch.setattr(manager_module, "load_member_directory", broken_loader)

    gen_resp = await client.post(f"/api/projects/{project_id}/generate", json={})
    final_status, _ = await _poll_until_terminal(client, gen_resp.json()["job_id"])

    task_prompts = [p for p in llm.calls if "実行可能な作業タスクに分解してください" in p]
    assert len(task_prompts) == 1
    assert "表記対応表" not in task_prompts[0]
    assert final_status["status"] == "failed"
