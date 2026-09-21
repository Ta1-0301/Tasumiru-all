# backend/tests/test_validation_duplicates.py
"""backend/pipeline/validation/duplicates.py の単体テスト（CHECK 2）。"""

import json

import pytest

from backend.pipeline.tasks.schema import Task
from backend.pipeline.validation.duplicates import (
    find_duplicate_candidates,
    verify_duplicate_with_llm,
    verify_duplicates_with_llm,
)
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


def _task(id, title, description="d") -> Task:
    return Task(id=id, title=title, description=description, confidence=0.9)


def test_similar_titles_are_flagged_as_duplicate_candidates():
    tasks = [_task("TASK-001", "認証APIを実装する"), _task("TASK-002", "認証APIを実装すること")]
    groups = find_duplicate_candidates(tasks)
    assert len(groups) == 1
    assert set(groups[0].task_ids) == {"TASK-001", "TASK-002"}
    assert groups[0].method == "rule"


def test_dissimilar_titles_are_not_flagged():
    tasks = [_task("TASK-001", "認証APIを実装する"), _task("TASK-002", "Kanban画面のデザインを作成する")]
    assert find_duplicate_candidates(tasks) == []


def test_threshold_is_configurable():
    tasks = [_task("TASK-001", "認証APIを実装する"), _task("TASK-002", "認証APIのバリデーションを実装する")]
    assert find_duplicate_candidates(tasks, threshold=0.95) == []
    assert len(find_duplicate_candidates(tasks, threshold=0.5)) == 1


@pytest.mark.asyncio
async def test_verify_duplicate_with_llm_returns_true_for_confirmed_duplicate():
    task_a, task_b = _task("TASK-001", "認証APIを実装する"), _task("TASK-002", "認証APIを実装すること")
    client = FakeLLMClient(responses={"タスクA": json.dumps({"duplicate": True, "explanation": "同じ"})})
    assert await verify_duplicate_with_llm(task_a, task_b, client) is True


@pytest.mark.asyncio
async def test_verify_duplicate_with_llm_returns_none_on_malformed_response():
    task_a, task_b = _task("TASK-001", "A"), _task("TASK-002", "B")
    client = FakeLLMClient(default="これはJSONではありません")
    assert await verify_duplicate_with_llm(task_a, task_b, client) is None


@pytest.mark.asyncio
async def test_verify_duplicates_with_llm_never_changes_the_number_of_candidates():
    """LLMが「重複ではない」と判定しても、候補は削除されない（レビュー対象として残る）"""
    tasks = [_task("TASK-001", "認証APIを実装する"), _task("TASK-002", "認証APIを実装すること")]
    tasks_by_id = {t.id: t for t in tasks}
    candidates = find_duplicate_candidates(tasks)
    assert len(candidates) == 1

    client = FakeLLMClient(responses={"タスクA": json.dumps({"duplicate": False, "explanation": "実は違う"})})
    verified = await verify_duplicates_with_llm(tasks_by_id, candidates, client)

    assert len(verified) == len(candidates)  # 削除されていない
    assert verified[0].task_ids == candidates[0].task_ids
    assert verified[0].method == "hybrid"
    assert "重複ではない" in verified[0].reason or "異なる可能性" in verified[0].reason


@pytest.mark.asyncio
async def test_verify_duplicates_with_llm_preserves_candidate_when_llm_fails():
    tasks = [_task("TASK-001", "認証APIを実装する"), _task("TASK-002", "認証APIを実装すること")]
    tasks_by_id = {t.id: t for t in tasks}
    candidates = find_duplicate_candidates(tasks)

    client = FakeLLMClient(default="これはJSONではありません")
    verified = await verify_duplicates_with_llm(tasks_by_id, candidates, client)

    assert len(verified) == 1  # LLM失敗でも候補は残る
