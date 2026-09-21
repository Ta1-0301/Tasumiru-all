# backend/tests/test_assignment_reasoning.py
"""backend/pipeline/assignment/reasoning.py の単体テスト（Step 3、任意のLLM）。

実際のLLM呼び出しはせず、FakeLLMClientで置き換える。
"""

import json

import pytest

from backend.pipeline.assignment.reasoning import generate_llm_reasoning
from backend.pipeline.assignment.schema import AssignmentTask, CandidateScore
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


def _task() -> AssignmentTask:
    return AssignmentTask(task_id="TASK-001", title="バックエンドAPIを実装する")


def _score(member_id, score) -> CandidateScore:
    return CandidateScore(
        member_id=member_id, skill_match=0.9, workload_score=0.8,
        experience_score=0.7, availability_score=0.6, score=score,
    )


@pytest.mark.asyncio
async def test_generate_llm_reasoning_returns_reasons_and_warnings():
    candidates = [_score("M-001", 91.0), _score("M-002", 88.0)]
    client = FakeLLMClient(responses={
        "バックエンドAPIを実装する": json.dumps({
            "reasons": ["M-001はスキルレベルがより高い"],
            "warnings": ["スコアが僅差のため確認を推奨"],
        }, ensure_ascii=False)
    })

    reasons, warnings = await generate_llm_reasoning(_task(), candidates, client)

    assert reasons == ["M-001はスキルレベルがより高い"]
    assert warnings == ["スコアが僅差のため確認を推奨"]


@pytest.mark.asyncio
async def test_generate_llm_reasoning_only_returns_text_never_a_member_choice():
    """LLMの戻り値の型そのものが reasons/warnings の文字列リストだけであり、
    recommended_member_idを書き換える経路が構造的に存在しないことを確認する"""
    candidates = [_score("M-001", 91.0)]
    client = FakeLLMClient(responses={
        "バックエンドAPIを実装する": json.dumps({
            "reasons": ["説明"], "warnings": [],
            "recommended_member_id": "M-999",  # 万一LLMがこれを返しても無視される
        }, ensure_ascii=False)
    })

    reasons, warnings = await generate_llm_reasoning(_task(), candidates, client)

    assert reasons == ["説明"]
    assert warnings == []
    # 戻り値はタプル(reasons, warnings)のみで、"M-999"はどこにも現れない
    assert "M-999" not in reasons and "M-999" not in warnings


@pytest.mark.asyncio
async def test_generate_llm_reasoning_returns_empty_for_no_candidates():
    client = FakeLLMClient()
    reasons, warnings = await generate_llm_reasoning(_task(), [], client)
    assert reasons == []
    assert warnings == []


@pytest.mark.asyncio
async def test_generate_llm_reasoning_handles_malformed_response_without_crashing():
    candidates = [_score("M-001", 91.0)]
    client = FakeLLMClient(default="これはJSONではありません")
    reasons, warnings = await generate_llm_reasoning(_task(), candidates, client)
    assert reasons == []
    assert warnings and "失敗" in warnings[0]


@pytest.mark.asyncio
async def test_generate_llm_reasoning_ignores_non_list_fields():
    candidates = [_score("M-001", 91.0)]
    client = FakeLLMClient(responses={
        "バックエンドAPIを実装する": json.dumps({"reasons": "not-a-list", "warnings": None})
    })
    reasons, warnings = await generate_llm_reasoning(_task(), candidates, client)
    assert reasons == []
    assert warnings == []
