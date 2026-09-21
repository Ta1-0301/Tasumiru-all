# backend/tests/test_dependencies_proposer.py
"""backend/pipeline/dependencies/proposer.py の単体テスト。

実際のLLM呼び出しはせず、backend/tests/test_pipeline.py と同じ
FakeLLMClient(キーワード応答型)で置き換える。
"""

import json

import pytest

from backend.pipeline.dependencies.proposer import propose_dependencies
from backend.pipeline.requirements.schema import SourceReference
from backend.pipeline.tasks.schema import Task
from backend.services.llm import BaseLLMClient


class FakeLLMClient(BaseLLMClient):
    def __init__(self, responses: dict[str, str] | None = None, default: str = "{}"):
        self.responses = responses or {}
        self.default = default

    async def complete(self, prompt: str, *, json_mode: bool = False) -> str:
        for key, resp in self.responses.items():
            if key in prompt:
                return resp
        return self.default


def _task(id, title, description="d", requirement_ids=None) -> Task:
    return Task(
        id=id, requirement_ids=requirement_ids or ["REQ-001"], title=title, description=description,
        acceptance_criteria=["条件"],
        source_reference=SourceReference(document_id="doc_1", source_text=description),
        confidence=0.9,
    )


@pytest.mark.asyncio
async def test_propose_dependencies_parses_valid_response():
    tasks = [_task("TASK-001", "データベース設計"), _task("TASK-002", "バックエンドAPI実装")]
    client = FakeLLMClient(responses={
        "データベース設計": json.dumps({
            "dependencies": [{
                "from_task_id": "TASK-001", "to_task_id": "TASK-002", "type": "required",
                "reason": "テーブル定義が無いとAPIを実装できない", "confidence": 0.9,
            }]
        }, ensure_ascii=False)
    })

    deps, error = await propose_dependencies(tasks, client)

    assert error is None
    assert len(deps) == 1
    assert deps[0].from_task_id == "TASK-001"
    assert deps[0].to_task_id == "TASK-002"
    assert deps[0].type == "required"


@pytest.mark.asyncio
async def test_propose_dependencies_returns_empty_for_single_task():
    tasks = [_task("TASK-001", "データベース設計")]
    client = FakeLLMClient()
    deps, error = await propose_dependencies(tasks, client)
    assert deps == []
    assert error is None
    # LLMを呼ぶ必要すらない（2件未満では依存関係は定義できない）


@pytest.mark.asyncio
async def test_propose_dependencies_drops_item_missing_from_or_to():
    tasks = [_task("TASK-001", "A"), _task("TASK-002", "B")]
    client = FakeLLMClient(responses={
        "TASK-001": json.dumps({
            "dependencies": [
                {"from_task_id": "", "to_task_id": "TASK-002", "confidence": 0.5},
                {"to_task_id": "TASK-002", "confidence": 0.5},
            ]
        }, ensure_ascii=False)
    })
    deps, error = await propose_dependencies(tasks, client)
    assert error is None
    assert deps == []


@pytest.mark.asyncio
async def test_propose_dependencies_invalid_type_falls_back_to_optional_with_low_confidence():
    tasks = [_task("TASK-001", "A"), _task("TASK-002", "B")]
    client = FakeLLMClient(responses={
        "TASK-001": json.dumps({
            "dependencies": [{"from_task_id": "TASK-001", "to_task_id": "TASK-002", "type": "critical"}]
        }, ensure_ascii=False)
    })
    deps, error = await propose_dependencies(tasks, client)
    assert deps[0].type == "optional"
    assert deps[0].confidence < 0.5


@pytest.mark.asyncio
async def test_propose_dependencies_does_not_drop_reference_to_nonexistent_task():
    """proposerは自由記述の内容チェックまではしない。存在しないタスクへの参照の
    検出はvalidatorの責務であり、proposerはそれをフィルタしない（責務の分離）"""
    tasks = [_task("TASK-001", "A"), _task("TASK-002", "B")]
    client = FakeLLMClient(responses={
        "TASK-001": json.dumps({
            "dependencies": [{"from_task_id": "TASK-001", "to_task_id": "TASK-999", "confidence": 0.5}]
        }, ensure_ascii=False)
    })
    deps, error = await propose_dependencies(tasks, client)
    assert len(deps) == 1
    assert deps[0].to_task_id == "TASK-999"


@pytest.mark.asyncio
async def test_propose_dependencies_malformed_json_returns_error_not_crash():
    tasks = [_task("TASK-001", "A"), _task("TASK-002", "B")]
    client = FakeLLMClient(default="これはJSONではありません")
    deps, error = await propose_dependencies(tasks, client)
    assert deps == []
    assert error is not None


@pytest.mark.asyncio
async def test_propose_dependencies_non_list_key_returns_error():
    tasks = [_task("TASK-001", "A"), _task("TASK-002", "B")]
    client = FakeLLMClient(responses={"TASK-001": json.dumps({"dependencies": "not-a-list"})})
    deps, error = await propose_dependencies(tasks, client)
    assert deps == []
    assert error is not None
