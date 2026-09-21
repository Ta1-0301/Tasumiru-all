# backend/tests/test_requirements_extractor.py
"""backend/pipeline/requirements/extractor.py の単体テスト。

実際のLLM呼び出しはせず、backend/tests/test_pipeline.py と同じ
FakeLLMClient(キーワード応答型)で置き換える。
"""

import json

import pytest

from backend.pipeline.requirements.extractor import extract_requirements_from_chunk
from backend.services.llm import BaseLLMClient
from backend.services.pipeline.schema import DocumentChunk


class FakeLLMClient(BaseLLMClient):
    def __init__(self, responses: dict[str, str] | None = None, default: str = "{}"):
        self.responses = responses or {}
        self.default = default
        self.calls: list[str] = []

    async def complete(self, prompt: str, *, json_mode: bool = False) -> str:
        self.calls.append(prompt)
        for key, resp in self.responses.items():
            if key in prompt:
                return resp
        return self.default


@pytest.mark.asyncio
async def test_extract_requirements_parses_valid_response():
    chunk = DocumentChunk(chunk_id="chunk_1", heading="第1条(認証)", text="招待URLで参加できる認証APIを実装すること。")
    client = FakeLLMClient(responses={
        "招待URLで参加できる認証API": json.dumps({
            "requirements": [{
                "type": "functional", "title": "認証APIを実装する",
                "description": "招待URLで参加できる認証APIを実装する",
                "priority": "high", "origin": "explicit", "confidence": 0.9,
            }]
        }, ensure_ascii=False)
    })

    candidates, error = await extract_requirements_from_chunk(chunk, client, "doc_1")

    assert error is None
    assert len(candidates) == 1
    c = candidates[0]
    assert c.type == "functional"
    assert c.confidence == 0.9
    assert c.source_reference.document_id == "doc_1"
    assert c.source_reference.paragraph == "chunk_1"
    assert c.source_reference.section == "第1条(認証)"
    # 出典はチャンクの実データそのもの（LLMには出典を書かせない）
    assert c.source_reference.source_text == chunk.text


@pytest.mark.asyncio
async def test_extract_requirements_source_reference_ignores_llm_supplied_text():
    """LLMがsource_text的な値を書いてきても採用されず、chunkの実データが使われることを確認する"""
    chunk = DocumentChunk(chunk_id="chunk_1", text="本文はこれだけです。")
    client = FakeLLMClient(responses={
        "本文はこれだけです": json.dumps({
            "requirements": [{
                "type": "constraint", "title": "t", "description": "d",
                "source_text": "LLMが書いた捏造の出典テキスト",
            }]
        }, ensure_ascii=False)
    })

    candidates, error = await extract_requirements_from_chunk(chunk, client, "doc_1")

    assert error is None
    assert candidates[0].source_reference.source_text == chunk.text
    assert "捏造" not in candidates[0].source_reference.source_text


@pytest.mark.asyncio
async def test_extract_requirements_drops_unknown_type():
    chunk = DocumentChunk(chunk_id="chunk_1", text="何かの区画")
    client = FakeLLMClient(responses={
        "何かの区画": json.dumps({
            "requirements": [{"type": "not_a_real_type", "title": "t", "description": "d"}]
        }, ensure_ascii=False)
    })
    candidates, error = await extract_requirements_from_chunk(chunk, client, "doc_1")
    assert error is None
    assert candidates == []


@pytest.mark.asyncio
async def test_extract_requirements_drops_item_missing_title_or_description():
    chunk = DocumentChunk(chunk_id="chunk_1", text="内容")
    client = FakeLLMClient(responses={
        "内容": json.dumps({
            "requirements": [
                {"type": "functional", "title": "", "description": "d"},
                {"type": "functional", "title": "t", "description": ""},
            ]
        }, ensure_ascii=False)
    })
    candidates, error = await extract_requirements_from_chunk(chunk, client, "doc_1")
    assert error is None
    assert candidates == []


@pytest.mark.asyncio
async def test_extract_requirements_invalid_priority_falls_back_to_unknown():
    chunk = DocumentChunk(chunk_id="chunk_1", text="内容")
    client = FakeLLMClient(responses={
        "内容": json.dumps({
            "requirements": [{"type": "functional", "title": "t", "description": "d", "priority": "超緊急"}]
        }, ensure_ascii=False)
    })
    candidates, error = await extract_requirements_from_chunk(chunk, client, "doc_1")
    assert candidates[0].priority == "unknown"


@pytest.mark.asyncio
async def test_extract_requirements_inferred_without_confidence_gets_low_default():
    chunk = DocumentChunk(chunk_id="chunk_1", text="内容")
    client = FakeLLMClient(responses={
        "内容": json.dumps({
            "requirements": [{"type": "assumption", "title": "t", "description": "d", "origin": "inferred"}]
        }, ensure_ascii=False)
    })
    candidates, error = await extract_requirements_from_chunk(chunk, client, "doc_1")
    assert candidates[0].origin == "inferred"
    assert candidates[0].confidence < 0.5


@pytest.mark.asyncio
async def test_extract_requirements_malformed_json_returns_error_not_crash():
    chunk = DocumentChunk(chunk_id="chunk_1", text="内容")
    client = FakeLLMClient(default="これはJSONではありません")
    candidates, error = await extract_requirements_from_chunk(chunk, client, "doc_1")
    assert candidates == []
    assert error is not None


@pytest.mark.asyncio
async def test_extract_requirements_non_list_requirements_key_returns_error():
    chunk = DocumentChunk(chunk_id="chunk_1", text="内容")
    client = FakeLLMClient(responses={"内容": json.dumps({"requirements": "not-a-list"})})
    candidates, error = await extract_requirements_from_chunk(chunk, client, "doc_1")
    assert candidates == []
    assert error is not None
