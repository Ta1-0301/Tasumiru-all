# backend/tests/test_dependencies_runner.py
"""backend/pipeline/dependencies/runner.py の結合テスト（FakeLLMClient使用）。"""

import json

import pytest

from backend.pipeline.dependencies.runner import run_dependency_pipeline, save_dependencies_document
from backend.pipeline.requirements.schema import SourceReference
from backend.pipeline.tasks.schema import Task, TaskDocument
from backend.services.llm import BaseLLMClient


class FakeLLMClient(BaseLLMClient):
    def __init__(self, responses: dict[str, str] | None = None, default: str = "{}"):
        self.responses = responses or {}
        self.default = default
        self.model = "fake-model-v1"

    async def complete(self, prompt: str, *, json_mode: bool = False) -> str:
        for key, resp in self.responses.items():
            if key in prompt:
                return resp
        return self.default


def _task(id, title) -> Task:
    return Task(
        id=id, requirement_ids=["REQ-001"], title=title, description=title,
        acceptance_criteria=["条件"],
        source_reference=SourceReference(document_id="spec_a", source_text=title),
        confidence=0.9,
    )


def _task_document() -> TaskDocument:
    return TaskDocument(
        document_id="spec_a",
        tasks=[
            _task("TASK-001", "データベース設計"),
            _task("TASK-002", "バックエンドAPI実装"),
            _task("TASK-003", "フロントエンド統合"),
        ],
    )


@pytest.mark.asyncio
async def test_run_dependency_pipeline_linear_chain_end_to_end():
    task_document = _task_document()
    client = FakeLLMClient(responses={
        "TASK-001": json.dumps({
            "dependencies": [
                {"from_task_id": "TASK-001", "to_task_id": "TASK-002", "type": "required",
                 "reason": "DB設計が先", "confidence": 0.9},
                {"from_task_id": "TASK-002", "to_task_id": "TASK-003", "type": "required",
                 "reason": "APIが先", "confidence": 0.9},
            ]
        }, ensure_ascii=False)
    })

    doc = await run_dependency_pipeline(task_document, client)

    assert doc.document_id == "spec_a"
    assert doc.model == "fake-model-v1"
    assert len(doc.dependencies) == 2
    assert doc.issues == []
    assert doc.graph["levels"] == {"TASK-001": 0, "TASK-002": 1, "TASK-003": 2}


@pytest.mark.asyncio
async def test_run_dependency_pipeline_flags_circular_dependency_without_dropping_it():
    task_document = _task_document()
    client = FakeLLMClient(responses={
        "TASK-001": json.dumps({
            "dependencies": [
                {"from_task_id": "TASK-001", "to_task_id": "TASK-002", "type": "required", "reason": "a", "confidence": 0.9},
                {"from_task_id": "TASK-002", "to_task_id": "TASK-003", "type": "required", "reason": "b", "confidence": 0.9},
                {"from_task_id": "TASK-003", "to_task_id": "TASK-001", "type": "required", "reason": "c", "confidence": 0.9},
            ]
        }, ensure_ascii=False)
    })

    doc = await run_dependency_pipeline(task_document, client)

    codes = {i.code for i in doc.issues}
    assert "CIRCULAR_DEPENDENCY" in codes
    assert "IMPOSSIBLE_DEPENDENCY_GRAPH" in codes
    # 無効な依存関係を黙って削除しない: そのまま出力に残る
    assert len(doc.dependencies) == 3


@pytest.mark.asyncio
async def test_run_dependency_pipeline_flags_self_and_nonexistent_dependencies():
    task_document = _task_document()
    client = FakeLLMClient(responses={
        "TASK-001": json.dumps({
            "dependencies": [
                {"from_task_id": "TASK-001", "to_task_id": "TASK-001", "reason": "a", "confidence": 0.5},
                {"from_task_id": "TASK-001", "to_task_id": "TASK-999", "reason": "b", "confidence": 0.5},
            ]
        }, ensure_ascii=False)
    })

    doc = await run_dependency_pipeline(task_document, client)

    codes = {i.code for i in doc.issues}
    assert "SELF_DEPENDENCY" in codes
    assert "NONEXISTENT_TASK_REFERENCE" in codes


@pytest.mark.asyncio
async def test_run_dependency_pipeline_does_not_assign_members():
    task_document = _task_document()
    client = FakeLLMClient()
    doc = await run_dependency_pipeline(task_document, client)
    dumped = json.dumps(doc.model_dump(mode="json"), ensure_ascii=False)
    assert "assignee" not in dumped


@pytest.mark.asyncio
async def test_run_dependency_pipeline_records_proposal_errors_without_crashing():
    task_document = _task_document()
    client = FakeLLMClient(default="これはJSONではありません")
    doc = await run_dependency_pipeline(task_document, client)
    assert doc.dependencies == []
    assert any(i.code == "PROPOSAL_ERROR" for i in doc.issues)


def test_save_dependencies_document_writes_valid_json(tmp_path):
    from backend.pipeline.dependencies.schema import DependencyDocument

    doc = DependencyDocument(document_id="spec_a", dependencies=[], issues=[], graph={"nodes": []})
    out_path = save_dependencies_document(doc, output_dir=tmp_path)

    assert out_path.exists()
    loaded = json.loads(out_path.read_text(encoding="utf-8"))
    assert loaded["document_id"] == "spec_a"
    assert loaded["dependencies"] == []
